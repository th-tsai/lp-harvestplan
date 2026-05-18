"""HarvestPlan — Farm-co decade farming plan MILP.

Maximises profit over 10 years via land allocation to crops/cattle,
grain stock management, and optimal calf purchase timing.

Decision variables
------------------
x[t, b, a]  binary   — land block b assigned to activity a in year t
y[t, b]     ≥ 0      — cows on block b in year t (continuous; big-M links to x)
g[t]        ≥ 0      — kg of home-grown grain used as cow feed in year t (t ≥ 1)
h[t]        ≥ 0      — kg of purchased grain used as cow feed in year t

Objective (maximise)
--------------------
  Crop revenue  : Σ_{t,b,a∈crops} x[t,b,a]·size[b]·(yield[a]·price[a] − sow[a])
  Cow value     : Σ_{t,b} f[t]·y[t,b]
  − Grain purchase cost : grain_buy_price · Σ_t h[t]
  − Grain opportunity   : sell_price[grain] · Σ_{t≥1} g[t]
  − Calf cost           : calf_cost · Σ_b y[T−1, b]   (telescoping = total calves bought)

Key constraints
---------------
C1  One activity per block per year        : Σ_a x[t,b,a] = 1
C2  Herd non-decreasing (no mid-decade sell): Σ_b y[t,b] ≥ Σ_b y[t−1,b]
C3  Cow-land lower                         : y[t,b] ≥ 0.1·x[t,b,cows]
C4  Cow-land upper                         : y[t,b] ≤ M_b·x[t,b,cows]
C5  Grain balance year 1                   : q·Σ_b y[0,b] = h[0]
C6  Grain balance years 2–T               : q·Σ_b y[t,b] = g[t] + h[t]
C7  Grain supply from prior planting       : yield[grain]·Σ_b x[t,b,grain]·size[b] ≥ g[t+1]
C8  Land-use cap per activity              : Σ_b x[t,b,a]·size[b] ≤ d·total_land
"""

from __future__ import annotations

import time

import pandas as pd
import pulp

from .data import HarvestPlanStructuredData
from .solution import MIPSolution, SolveMeta


class HarvestPlanSolution(MIPSolution):
    """MILP solution for the HarvestPlan farming model.

    primal["land_allocation"] : (year, block) → activity label
    primal["cow_herd"]        : year → total_cows
    primal["grain_balance"]   : year → demand_kg, from_planting_kg, purchased_kg
    primal["crop_summary"]    : (year, activity) → land_m2, land_pct, yield_kg
    """


class HarvestPlan:
    """PuLP/HiGHS MILP for HarvestPlan decade farming plan.

    Build once, call solve() for results.
    """

    def __init__(self, data: HarvestPlanStructuredData) -> None:
        self.data = data
        self.model = pulp.LpProblem("HarvestPlan", pulp.LpMaximize)
        self.x: dict[tuple[int, str, str], pulp.LpVariable] = {}
        self.y: dict[tuple[int, str], pulp.LpVariable] = {}
        self.g: dict[int, pulp.LpVariable] = {}   # years 1..n_years-1
        self.h: dict[int, pulp.LpVariable] = {}   # years 0..n_years-1
        self._build_model()

    def _build_model(self) -> None:
        d = self.data
        T = range(d.n_years)
        B = d.blocks

        # --- Decision variables ---
        for t in T:
            for b in B:
                for a in d.all_activities:
                    self.x[(t, b, a)] = pulp.LpVariable(f"x_{t}_{b}_{a}", cat="Binary")
                self.y[(t, b)] = pulp.LpVariable(f"y_{t}_{b}", lowBound=0)

        for t in T:
            self.h[t] = pulp.LpVariable(f"h_{t}", lowBound=0)
        for t in range(1, d.n_years):
            self.g[t] = pulp.LpVariable(f"g_{t}", lowBound=0)

        # --- Objective ---
        crop_rev = pulp.lpSum(
            self.x[(t, b, a)] * d.size[b] * (d.yield_kg_m2[a] * d.sell_price[a] - d.sow_cost[a])
            for t in T for b in B for a in d.crop_activities
        )
        cow_val = pulp.lpSum(
            d.f[t] * self.y[(t, b)]
            for t in T for b in B
        )
        grain_buy_cost = d.grain_buy_price * pulp.lpSum(self.h[t] for t in T)
        grain_opp_cost = d.sell_price[d.grain_activity] * pulp.lpSum(
            self.g[t] for t in range(1, d.n_years)
        )
        calf_cost = d.calf_cost * pulp.lpSum(self.y[(d.n_years - 1, b)] for b in B)

        self.model += (
            crop_rev + cow_val - grain_buy_cost - grain_opp_cost - calf_cost,
            "Total_Profit",
        )

        # C1: Each block has exactly one activity per year
        for t in T:
            for b in B:
                self.model += (
                    pulp.lpSum(self.x[(t, b, a)] for a in d.all_activities) == 1,
                    f"OneActivity_{t}_{b}",
                )

        # C2: Total herd non-decreasing (no selling during the decade)
        for t in range(1, d.n_years):
            self.model += (
                pulp.lpSum(self.y[(t, b)] for b in B)
                >= pulp.lpSum(self.y[(t - 1, b)] for b in B),
                f"CowNonDecreasing_{t}",
            )

        # C3 & C4: Big-M link between cow count and land assignment.
        # C3: x=1 forces y ≥ 0.1 (no degenerate cow-land with zero cows).
        # C4: x=0 forces y = 0 (no phantom cows on non-cow land).
        for t in T:
            for b in B:
                M = d.max_cows[b]
                self.model += (
                    self.y[(t, b)] >= 0.1 * self.x[(t, b, "cows")],
                    f"CowLower_{t}_{b}",
                )
                self.model += (
                    self.y[(t, b)] <= M * self.x[(t, b, "cows")],
                    f"CowUpper_{t}_{b}",
                )

        # C5: Grain balance year 1 — all feed must be purchased (no prior harvest)
        self.model += (
            d.grain_per_cow * pulp.lpSum(self.y[(0, b)] for b in B) == self.h[0],
            "GrainBalance_0",
        )

        # C6: Grain balance years 2–T — feed from planting and/or purchase
        for t in range(1, d.n_years):
            self.model += (
                d.grain_per_cow * pulp.lpSum(self.y[(t, b)] for b in B)
                == self.g[t] + self.h[t],
                f"GrainBalance_{t}",
            )

        # C7: Grain planted in year t supplies feed g[t+1] for year t+1
        for t in range(d.n_years - 1):
            self.model += (
                d.yield_kg_m2[d.grain_activity]
                * pulp.lpSum(self.x[(t, b, d.grain_activity)] * d.size[b] for b in B)
                >= self.g[t + 1],
                f"GrainSupply_{t}",
            )

        # C8: No single activity may occupy more than max_land_fraction of total land
        for t in T:
            for a in d.all_activities:
                self.model += (
                    pulp.lpSum(self.x[(t, b, a)] * d.size[b] for b in B)
                    <= d.max_land_fraction * d.total_land,
                    f"LandLimit_{t}_{a}",
                )

    def solve(self) -> HarvestPlanSolution:
        """Solve the MILP and return a HarvestPlanSolution."""
        t0 = time.perf_counter()
        # 0.1 % relative gap gives a ~50 s solve within £20 of the £211,797.50 optimum.
        # Tighten to mip_abs_gap=0.4 to prove global optimality (profits are £0.5 multiples)
        # at the cost of ~6 min runtime.
        self.model.solve(pulp.HiGHS(msg=False, mip_rel_gap=0.001))
        runtime = time.perf_counter() - t0

        status = pulp.LpStatus[self.model.status]
        obj_val = pulp.value(self.model.objective)

        primal: dict[str, pd.DataFrame] = {}

        if status == "Optimal":
            d = self.data
            T = range(d.n_years)
            B = d.blocks
            year_labels = [f"Y{t + 1}" for t in T]

            # Land allocation: pivot block × year
            alloc: dict[str, dict[str, str]] = {b: {} for b in B}
            for t in T:
                for b in B:
                    for a in d.all_activities:
                        if float(pulp.value(self.x[(t, b, a)]) or 0.0) > 0.5:
                            if a == "cows":
                                n = round(float(pulp.value(self.y[(t, b)]) or 0.0))
                                alloc[b][year_labels[t]] = f"cows({n})"
                            else:
                                alloc[b][year_labels[t]] = a
                            break
            primal["land_allocation"] = pd.DataFrame(alloc).T
            primal["land_allocation"].index.name = "block"

            # Cow herd by year
            herd_rows = []
            for t in T:
                total = sum(float(pulp.value(self.y[(t, b)]) or 0.0) for b in B)
                herd_rows.append({"year": year_labels[t], "total_cows": round(total)})
            primal["cow_herd"] = pd.DataFrame(herd_rows).set_index("year")

            # Grain balance
            grain_rows = []
            for t in T:
                total_cows = sum(float(pulp.value(self.y[(t, b)]) or 0.0) for b in B)
                demand = d.grain_per_cow * total_cows
                g_val = float(pulp.value(self.g[t]) or 0.0) if t > 0 else 0.0  # type: ignore[arg-type]
                h_val = float(pulp.value(self.h[t]) or 0.0)  # type: ignore[arg-type]
                grain_rows.append({
                    "year": year_labels[t],
                    "demand_kg": round(demand, 1),
                    "from_planting_kg": round(g_val, 1),
                    "purchased_kg": round(h_val, 1),
                })
            primal["grain_balance"] = pd.DataFrame(grain_rows).set_index("year")

            # Crop summary
            summary_rows = []
            for t in T:
                for a in d.all_activities:
                    land = sum(
                        float(pulp.value(self.x[(t, b, a)]) or 0.0) * d.size[b] for b in B
                    )
                    if land < 0.5:
                        continue
                    yield_kg = d.yield_kg_m2[a] * land if a in d.crop_activities else 0.0
                    summary_rows.append({
                        "year": year_labels[t],
                        "activity": a,
                        "land_m2": round(land, 1),
                        "land_pct": round(land / d.total_land * 100, 2),
                        "yield_kg": round(yield_kg, 1),
                    })
            primal["crop_summary"] = pd.DataFrame(summary_rows)

        gap: float | None = None
        try:
            highs = self.model.solverModel
            if highs is not None:
                info = highs.getInfoValue("mip_gap")
                if info[0] == 0:
                    gap = float(info[1])
        except Exception:
            pass

        return HarvestPlanSolution(
            meta=SolveMeta(
                status=status,
                objective=float(obj_val) if obj_val is not None else None,
                runtime_seconds=runtime,
                solver="HiGHS",
            ),
            primal=primal,
            dual={},
            gap=gap,
        )
