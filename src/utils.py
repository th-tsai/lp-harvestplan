"""Result formatting and printing for HarvestPlan."""

from .solution import MIPSolution


def _section(lines: list[str], title: str) -> None:
    lines.append(f"\n{title}")
    lines.append("-" * len(title))


def print_results(solution: MIPSolution, label: str = "HarvestPlan") -> str:
    lines: list[str] = []
    lines.append(f"{label} — Farm-co Decade Farming Plan")
    lines.append("=" * (len(label) + 30))
    lines.append(f"Status:   {solution.meta.status}")
    if solution.meta.objective is not None:
        lines.append(f"Profit:   £{solution.meta.objective:,.2f}")
    lines.append(f"Runtime:  {solution.meta.runtime_seconds:.3f} s")
    if solution.gap is not None:
        lines.append(f"MIP Gap:  {solution.gap:.4%}")

    if not solution.is_optimal:
        lines.append("No optimal solution found, skipping details.")
        result = "\n".join(lines)
        print(result)
        return result

    _section(lines, "Land Allocation Plan")
    alloc = solution.get_primal("land_allocation")
    year_cols = sorted(alloc.columns, key=lambda c: int(c[1:]))
    lines.append(alloc[year_cols].to_string())

    _section(lines, "Cow Herd by Year")
    herd = solution.get_primal("cow_herd")
    lines.append(herd.to_string())

    _section(lines, "Grain Balance")
    grain = solution.get_primal("grain_balance")
    lines.append(grain.to_string())

    _section(lines, "Crop & Livestock Summary")
    summ = solution.get_primal("crop_summary").copy()
    summ["land_pct"] = summ["land_pct"].map("{:.2f}%".format)
    summ["land_m2"] = summ["land_m2"].map("{:,.1f}".format)
    summ["yield_kg"] = summ["yield_kg"].map("{:,.1f}".format)
    lines.append(summ.to_string(index=False))

    result = "\n".join(lines)
    print(result)
    return result
