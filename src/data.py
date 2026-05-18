"""Data schema, loading, and structuring for HarvestPlan."""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pandas as pd


@dataclass
class HarvestPlanRawData:
    """Raw input data for HarvestPlan. Schema-validated but not business-validated.

    Schema:
    - blocks:      DataFrame indexed by block id, column [size]
    - activities:  DataFrame indexed by activity name, columns
                   [yield_kg_m2, sow_cost_per_m2, sell_price_per_kg]
                   (crop activities only: grain, beans, wheat)
    - cow_prices:  DataFrame indexed by age (1..n_years), column [sell_price]
    - cow_space_m2: float, m2 of land required per cow
    - grain_per_cow_kg: float, kg of grain required per cow per year
    - calf_cost: float, cost of buying a calf
    - grain_buy_price_per_kg: float, cost of buying grain per kg
    - max_land_fraction: float in (0,1), max fraction of total land per activity
    - total_years: int, length of planning horizon in years
    """

    blocks: pd.DataFrame
    activities: pd.DataFrame
    cow_prices: pd.DataFrame
    cow_space_m2: float
    grain_per_cow_kg: float
    calf_cost: float
    grain_buy_price_per_kg: float
    max_land_fraction: float
    total_years: int
    result: Path | None = None
    description: str | None = None

    @classmethod
    def load_from_toml(cls, path: Path) -> "HarvestPlanRawData":
        with open(path, "rb") as f:
            data: dict[str, Any] = tomllib.load(f)

        sc = data["scalar"]
        base = path.parent
        tp = data["table_path"]

        result_path: Path | None = None
        description: str | None = None
        if "result" in data:
            result_path = Path(data["result"]["result"])
            description = data["result"].get("description")

        return cls(
            blocks=pd.read_csv(base / tp["block"], index_col="block"),
            activities=pd.read_csv(base / tp["activity"], index_col="activity"),
            cow_prices=pd.read_csv(base / tp["cow_price"], index_col="age"),
            cow_space_m2=float(sc["cow_space_m2"]),
            grain_per_cow_kg=float(sc["grain_per_cow_kg"]),
            calf_cost=float(sc["calf_cost"]),
            grain_buy_price_per_kg=float(sc["grain_buy_price_per_kg"]),
            max_land_fraction=float(sc["max_land_fraction"]),
            total_years=int(sc["total_years"]),
            result=result_path,
            description=description,
        )

    def structured(self) -> "HarvestPlanStructuredData":
        return HarvestPlanStructuredData.from_raw(self)


@dataclass(frozen=True)
class HarvestPlanStructuredData:
    """Validated, immutable data for HarvestPlan model construction.

    The f parameter encodes incremental cow selling value in inverse year order:
    f[t] is the marginal value gained by keeping a cow through year t.
    A cow present in years t..n_years-1 earns sum(f[t:]) when sold at end.

    Use from_raw() to construct. Do not instantiate directly.
    """

    # Index sets
    blocks: tuple[str, ...]
    crop_activities: tuple[str, ...]     # grain, beans, wheat
    all_activities: tuple[str, ...]      # crop_activities + ("cows",)
    n_years: int

    # Block parameters
    size: Mapping[str, float]            # m² per block
    max_cows: Mapping[str, float]        # M_b = size[b] / cow_space_m2

    # Crop activity parameters (keyed by activity name)
    yield_kg_m2: Mapping[str, float]
    sow_cost: Mapping[str, float]        # £/m²
    sell_price: Mapping[str, float]      # £/kg

    # Cow parameters
    f: tuple[float, ...]                 # incremental cow value, length n_years
    calf_cost: float                     # £/calf
    grain_per_cow: float                 # kg/cow/year
    cow_space: float                     # m²/cow

    # Grain purchase
    grain_buy_price: float               # £/kg

    # Constraints
    max_land_fraction: float
    total_land: float

    # Convenience
    grain_activity: str                  # name of the grain crop activity

    @classmethod
    def from_raw(cls, raw: HarvestPlanRawData) -> "HarvestPlanStructuredData":
        blocks_idx = raw.blocks.index
        activities_idx = raw.activities.index
        blocks = tuple(blocks_idx.astype(str))
        crop_activities = tuple(activities_idx.astype(str))
        all_activities = crop_activities + ("cows",)

        n_years = raw.total_years
        cow_space = raw.cow_space_m2
        total_land = float(raw.blocks["size"].sum())

        max_cows = MappingProxyType({
            str(b): float(raw.blocks.at[b, "size"]) / cow_space
            for b in blocks_idx
        })

        # f[t] = incremental value of keeping a cow alive through year t (inverse year order)
        ages = sorted(raw.cow_prices.index)
        prices = [0.0] + [float(raw.cow_prices.at[a, "sell_price"]) for a in ages]
        diffs = [prices[i + 1] - prices[i] for i in range(len(ages))]
        f = tuple(reversed(diffs))

        grain_activity = crop_activities[0]

        return cls(
            blocks=blocks,
            crop_activities=crop_activities,
            all_activities=all_activities,
            n_years=n_years,
            size=MappingProxyType({str(b): float(raw.blocks.at[b, "size"]) for b in blocks_idx}),
            max_cows=max_cows,
            yield_kg_m2=MappingProxyType({
                str(a): float(raw.activities.at[a, "yield_kg_m2"]) for a in activities_idx
            }),
            sow_cost=MappingProxyType({
                str(a): float(raw.activities.at[a, "sow_cost_per_m2"]) for a in activities_idx
            }),
            sell_price=MappingProxyType({
                str(a): float(raw.activities.at[a, "sell_price_per_kg"]) for a in activities_idx
            }),
            f=f,
            calf_cost=raw.calf_cost,
            grain_per_cow=raw.grain_per_cow_kg,
            cow_space=cow_space,
            grain_buy_price=raw.grain_buy_price_per_kg,
            max_land_fraction=raw.max_land_fraction,
            total_land=total_land,
            grain_activity=grain_activity,
        )
