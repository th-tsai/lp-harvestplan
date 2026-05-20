# HarvestPlan — Farm-co Decade Farming Plan

**Problem class:** Mixed-integer linear programming · land allocation  
**Solver:** PuLP + HiGHS

---

## Problem

Farm-co Ltd manages **3,665 m²** of agricultural land across **10 blocks**, ranging from 75 m² to 900 m².
The goal is to find the 10-year farming plan that maximises profit by optimally allocating land each year to crops and cattle, managing a self-sufficient grain supply, and timing calf purchases for maximum livestock value.

### Land blocks

|     Block | Size (m²) |
| --------: | --------: |
|         1 |       100 |
|         2 |       250 |
|         3 |       500 |
|         4 |       125 |
|         5 |       800 |
|         6 |        75 |
|         7 |       900 |
|         8 |       360 |
|         9 |       465 |
|        10 |        90 |
| **Total** | **3,665** |

### Crop activities

| Activity | Yield (kg/m²) | Sow cost (£/m²) | Sell price (£/kg) | Net margin (£/m²) |
| -------- | ------------: | --------------: | ----------------: | ----------------: |
| Grain    |           3.0 |            15.0 |               4.5 |              -1.5 |
| Beans    |           2.0 |            10.0 |               6.0 |               2.0 |
| Wheat    |           3.5 |            12.0 |               5.0 |               5.5 |

Grain has a _negative_ margin as a cash crop — it is only planted to supply cow feed at lower cost than purchasing grain at £50/kg.

### Cow pricing (sell value by age at end of decade)

| Age | 1   | 2   | 3   | 4   | 5   | 6   | 7     | 8     | 9     | 10    |
| --- | --- | --- | --- | --- | --- | --- | ----- | ----- | ----- | ----- |
| £   | 350 | 450 | 550 | 600 | 700 | 950 | 1,100 | 1,250 | 1,400 | 1,700 |

### Key parameters

| Parameter                        | Value    |
| -------------------------------- | -------- |
| Land required per cow            | 5 m²     |
| Grain per cow per year           | 15 kg    |
| Calf purchase cost               | £200     |
| Grain purchase price             | £50/kg   |
| Max land fraction (any activity) | 50 %     |
| Planning horizon                 | 10 years |

---

## MILP Formulation

### Sets and indices

| Symbol               | Definition                                 |
| -------------------- | ------------------------------------------ |
| $T = \{0,\ldots,9\}$ | years                                      |
| $B$                  | land blocks                                |
| $A$                  | all activities (grain, beans, wheat, cows) |
| $C \subset A$        | crop activities (grain, beans, wheat)      |

### Parameters

| Symbol             | Meaning                                             |
| ------------------ | --------------------------------------------------- |
| $s_b$              | size of block $b$ (m²)                              |
| $r_a$              | yield of crop $a$ (kg/m²)                           |
| $p_a$              | sell price of crop $a$ (£/kg)                       |
| $w_a$              | sow cost of crop $a$ (£/m²)                         |
| $f_t$              | incremental cow value in inverse year order (£/cow) |
| $q$                | grain required per cow per year (kg)                |
| $\sigma$           | space required per cow (m²)                         |
| $M_b = s_b/\sigma$ | maximum cows on block $b$ (big-M)                   |
| $\kappa$           | calf purchase cost (£)                              |
| $\pi$              | grain purchase price (£/kg)                         |
| $d$                | maximum fraction of total land per activity         |
| $L = \sum_b s_b$   | total land (m²)                                     |

The $f_t$ parameter encodes the incremental value of keeping a calf alive through each additional year in _reverse_ order: a cow purchased in year 0 and sold at age 10 earns $\sum_{t=0}^{9} f_t$.

### Decision variables

| Symbol                  | Type       | Meaning                                                  |
| ----------------------- | ---------- | -------------------------------------------------------- |
| $x_{t,b,a} \in \{0,1\}$ | binary     | block $b$ assigned to activity $a$ in year $t$           |
| $y_{t,b} \ge 0$         | continuous | cows on block $b$ in year $t$                            |
| $g_t \ge 0$             | continuous | home-grown grain fed to cows in year $t$ (kg), $t \ge 1$ |
| $h_t \ge 0$             | continuous | purchased grain fed to cows in year $t$ (kg)             |

### Objective — maximise profit

$$
\begin{aligned}
\max \quad & \underbrace{\sum_{t \in T} \sum_{b \in B} \sum_{a \in C} x_{t,b,a} \cdot s_b \cdot (r_a p_a - w_a)}_{\text{crop revenue}} + \underbrace{\sum_{t \in T} \sum_{b \in B} f_t \cdot y_{t,b}}_{\text{cow value}} \\
& - \underbrace{\pi \sum_{t \in T} h_t}_{\text{grain purchase}} - \underbrace{p_{\text{grain}} \sum_{t=1}^{9} g_t}_{\text{grain opportunity cost}} - \underbrace{\kappa \sum_{b \in B} y_{9,b}}_{\text{calf cost (telescoping)}}
\end{aligned}
$$

The calf cost term uses a telescoping argument: since herd size is non-decreasing (C2), the total calves ever purchased equals the final herd size $\sum_b y_{9,b}$, each costing $\kappa$.

### Constraints

**C1 — One activity per block per year**

$$\sum_{a \in A} x_{t,b,a} = 1 \quad \forall\, t \in T,\; b \in B$$

**C2 — Herd non-decreasing** (no mid-decade selling)

$$\sum_{b \in B} y_{t,b} \ge \sum_{b \in B} y_{t-1,b} \quad \forall\, t \ge 1$$

**C3 — Cow–land lower bound** (no degenerate cow blocks with zero cows)

$$y_{t,b} \ge 0.1 \cdot x_{t,b,\text{cows}} \quad \forall\, t,b$$

**C4 — Cow–land upper bound** (big-M: no cows without a cow block)

$$y_{t,b} \le M_b \cdot x_{t,b,\text{cows}} \quad \forall\, t,b$$

**C5 — Grain balance, year 1** (no prior harvest; all feed purchased)

$$q \sum_{b \in B} y_{0,b} = h_0$$

**C6 — Grain balance, years 2–10**

$$q \sum_{b \in B} y_{t,b} = g_t + h_t \quad \forall\, t \ge 1$$

**C7 — Grain supply from prior planting**

$$r_{\text{grain}} \sum_{b \in B} x_{t,b,\text{grain}} \cdot s_b \ge g_{t+1} \quad \forall\, t \le 8$$

**C8 — Land-use cap per activity**

$$\sum_{b \in B} x_{t,b,a} \cdot s_b \le d \cdot L \quad \forall\, t \in T,\; a \in A$$

---

## Results

### Baseline — profit £211,780

Farm-co's optimal strategy is built around cattle, not crops. The solver keeps **350 cows** on roughly half the farm (1,750 m²) throughout the middle eight years, with 15 additional calves added in year 10 to finish the decade at 365 cows. No grain is ever purchased — the plan is entirely self-sufficient, growing just enough grain on the remaining land to feed the herd each year.

The structure repeats with striking regularity: the three large blocks (5, 7, 9 — totalling 2,165 m²) rotate between grain and cows on a two-year cycle, while the smaller blocks fill in wheat and beans around them. Block 10 (90 m²) runs wheat for all ten years, illustrating that small plots are not worth rotating into cows given the 5 m²-per-cow overhead.

| Year  | Cows | Grain grown (kg) | Grain purchased (kg) | Wheat area (m²) |
| :---: | ---: | ---------------: | -------------------: | --------------: |
|  Y1   |    0 |            5,280 |                    — |           1,830 |
| Y2–Y8 |  350 |            5,250 |                    0 |             165 |
|  Y9   |  350 |            5,475 |                    0 |              90 |
|  Y10  |  365 |                — |                    0 |           1,765 |

Wheat fills the blocks not used for grain or cows — at £5.50/m² net margin it earns meaningfully more than beans (£2.00/m²), which appear only in years 1 and 10 on the 75 m² block 6 when that block cannot be efficiently used for cows.

The plan is deliberately designed around the end-of-decade livestock liquidation: calves purchased in year 2 are worth £1,700 ten years later, yielding a net return of £1,500 per calf after the £200 purchase cost. This large livestock appreciation — especially the £300 jump from age 9 to age 10 — anchors the strategy firmly in cattle.

---

### Case 1 — Wheat price raised to £7/kg: profit £328,500 (+55%)

At £7/kg, wheat earns **£12.50/m²** net, more than doubling its attractiveness relative to cows. The solver responds decisively: it cuts the standing herd to just **183 cows** (down from 350) for years 2–9, freeing roughly 900 m² for wheat each year. In the final year it masses up to 352 cows, leveraging the decade-end liquidation bonus.

The shift reflects a fundamental trade-off. The midyear cattle strategy earns mainly from the cow-value accrual term ($f_t \cdot y_{t,b}$) accumulated over eight years, while wheat now earns more per unit of land immediately each year. With wheat at £12.50/m² versus cattle at roughly £6–8/m² in midyear value, the model switches a quarter of the farm to wheat permanently.

| Scenario | Cows (Y2–Y9) | Cows (Y10) |   Profit |
| -------- | -----------: | ---------: | -------: |
| Baseline |          350 |        365 | £211,780 |
| Case 1   |          183 |        352 | £328,500 |

The +£116,720 improvement comes almost entirely from replacing low-margin midyear cows with high-margin wheat, then collecting the full decade-end liquidation value on a slightly smaller herd. The grain demand drops accordingly: 2,745 kg/year in the middle years instead of 5,250 kg, so less land needs to be tied up growing feed.

---

### Case 2 — Land cap relaxed to 60%: profit £213,132 (+0.6%)

Raising the land-use cap from 50% to 60% (from 1,832 m² to 2,199 m²) produces only a **£1,352 improvement** — less than 1%. The reason is structural: the binding constraint in the baseline is not the 50% cap per activity but the joint pressure between the grain supply requirement and the cow-space requirement. The model needs enough grain area to feed the herd _and_ enough cow area to hold the herd, and those two needs together already consume close to 95% of the land. Relaxing the cap on either activity in isolation barely changes the feasible region.

The solver does respond: it bumps the standing herd from 295 cows to 438 in the final year (a much larger terminal surge than in the baseline), suggesting it is using the extra room to defer calves into the final year for maximum appreciation value. But the gain is modest because the extra land freed by the relaxed cap is immediately consumed by the additional grain needed to feed those extra cows.

This case reveals that the 50% cap is **not** the primary binding constraint in the baseline — the interaction between grain self-sufficiency and cow-space requirements is.

---

### Case 3 — Grain yield raised to 4.0 kg/m²: profit £295,347 (+39%)

Increasing grain yield from 3.0 to 4.0 kg/m² does two things at once. First, it makes grain a **profitable crop in its own right**: at 4.0 kg/m² × £4.50/kg − £15/m² = +£3.00/m², grain shifts from a £1.50/m² loss to a £3.00/m² gain. Second, it means the same feed requirement can be satisfied on **25% less land**, freeing area for cows or wheat.

The solver exploits both effects. It raises the standing herd to **366 cows** (slightly more than baseline's 350) and locks most of the large blocks into cows permanently rather than rotating them — block 7 (900 m²) stays in cows from year 2 onwards, and block 9 (465 m²) from year 4 onwards. The farm settles into a stable steady state far sooner than in the baseline, with cows occupying close to 50% of the farm continuously.

| Year  | Cows | Grain area (m²) | Grain yield (kg) |
| :---: | ---: | --------------: | ---------------: |
| Y2–Y3 |  365 |           1,390 |            5,560 |
| Y4–Y9 |  366 |           1,375 |            5,500 |
|  Y10  |  366 |              75 |              300 |

The improvement is larger and more structurally significant than relaxing the land cap (Case 2), because better grain yield simultaneously improves both sides of the farm's constraint: it earns more per m² when sold and requires fewer m² when used as feed.

---

## Key Takeaways

**Cattle appreciation, not crop revenue, drives the baseline strategy.** The jump from £350 for a one-year-old calf to £1,700 for a ten-year-old cow — net £1,500 after the £200 purchase cost — is far higher than any crop margin. The model locks in calves early and holds them.

**Grain is a feed crop, not a cash crop.** At baseline parameters (−£1.50/m² net margin), grain is only grown because buying it at £50/kg would cost even more. The farm is entirely grain self-sufficient in all scenarios — purchased grain never appears in any optimal solution.

**Wheat profitability is the most powerful single lever.** Doubling wheat's margin (Case 1, +£116,720) produces 86 times more uplift than relaxing the land cap (Case 2, +£1,352). If Farm-co can access higher-value wheat markets or varieties, that is by far the most valuable change to pursue.

**Better grain varieties unlock compounding benefits.** Raising grain yield (Case 3, +£83,567) simultaneously turns a loss-making feed crop into a mildly profitable one and compresses the land area needed for feed. The farm reaches a stable, cattle-heavy steady state much earlier in the decade, and the solver no longer needs to rotate grain and cows — it can simply commit land to each role.

**The 50% land cap is not the binding constraint.** Relaxing it to 60% adds less than £1,400. The real bottleneck is the joint requirement for grain area and cow area, which together already consume nearly all available land.
