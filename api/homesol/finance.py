"""What a rooftop system costs and saves. Pure arithmetic over the policy data."""

from dataclasses import asdict, dataclass

from . import policy

SYSTEM_LIFE_YEARS = 25
#: Share of output panels lose each year.
PANEL_DEGRADATION = 0.005
#: Assumed yearly rise in electricity prices. A stated assumption, not a forecast.
TARIFF_ESCALATION = 0.02


@dataclass
class Finance:
    gross_cost: int
    gross_cost_range: tuple[int, int]
    cost_is_quote: bool
    subsidy: int
    net_cost: int
    bill_before: int
    bill_after: int
    first_year_savings: int
    surplus_units: int
    surplus_credit: int
    payback_years: float | None
    lifetime_savings: int
    rate_basis: str
    notes: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


def slab_bill(units: float, tariff: dict) -> float:
    """Monthly bill in rupees for `units` under a slab tariff, including the fixed charge."""
    total, lower = float(tariff["fixed_charge"]), 0.0
    for slab in tariff["slabs"]:
        upper = slab["up_to"] if slab["up_to"] is not None else float("inf")
        if units > lower:
            total += (min(units, upper) - lower) * slab["rate"]
        lower = upper
    return total


def estimate(
    *,
    system_kw: float,
    monthly_generation: list[float],
    monthly_usage: float,
    discom_id: str | None = None,
    monthly_bill: float | None = None,
    quoted_cost: float | None = None,
) -> Finance:
    """
    Cost, subsidy, bill savings and payback for one system.

    Savings follow net metering: each month's solar units offset that month's
    usage, any excess is carried forward as credit within the year, and what is
    left at year end is paid at the DISCOM's surplus rate when that rate is known.

    Bills are priced from the household's own bill when `monthly_bill` is given
    (its average rate per unit), otherwise from the DISCOM's slab table.
    """
    data = policy.load()
    discom = policy.get_discom(discom_id) if discom_id else None
    notes: list[str] = []

    cost = data["system_cost_per_kw"]
    gross = round(quoted_cost if quoted_cost else system_kw * cost["typical"])
    gross_range = (round(system_kw * cost["low"]), round(system_kw * cost["high"]))
    subsidy = min(policy.central_subsidy(system_kw), gross)

    if monthly_bill and monthly_usage > 0:
        rate = monthly_bill / monthly_usage
        price = lambda units: units * rate  # noqa: E731
        rate_basis = "your_bill"
        notes.append(
            f"Priced at your own average of Rs {rate:.2f} a unit. Solar removes your most expensive "
            "units first, so real savings are usually a little higher."
        )
    elif discom:
        price = lambda units: slab_bill(units, discom["tariff"])  # noqa: E731
        rate_basis = "discom_slabs"
        if not discom["tariff"]["verified"]:
            notes.append(
                f"Uses indicative {discom['name']} slab rates that are not yet checked against the "
                "regulator's order. Enter your bill amount for a figure based on what you actually pay."
            )
        notes.append(f"Leaves out: {discom['tariff']['excludes']}")
    else:
        raise ValueError("Give either a monthly bill amount or a supported DISCOM.")

    bill_before = price(monthly_usage) * 12
    bill_after, credit_units = 0.0, 0.0
    for generated in monthly_generation:
        net = monthly_usage - generated - credit_units
        credit_units = max(0.0, -net)
        bill_after += price(max(0.0, net))

    surplus_rate = discom["net_metering"]["surplus_rate"] if discom else None
    surplus_credit = credit_units * surplus_rate if surplus_rate else 0.0
    if credit_units >= 1 and not surplus_rate:
        notes.append(
            f"About {round(credit_units)} surplus units a year are counted as worth nothing because "
            "the rate your DISCOM pays for them is not confirmed."
        )

    first_year = bill_before - bill_after + surplus_credit
    net_cost = gross - subsidy

    lifetime, payback, cumulative = 0.0, None, 0.0
    for year in range(SYSTEM_LIFE_YEARS):
        savings = first_year * (1 - PANEL_DEGRADATION) ** year * (1 + TARIFF_ESCALATION) ** year
        if payback is None and savings > 0 and cumulative + savings >= net_cost:
            payback = year + (net_cost - cumulative) / savings
        cumulative += savings
        lifetime += savings

    return Finance(
        gross_cost=gross,
        gross_cost_range=gross_range,
        cost_is_quote=bool(quoted_cost),
        subsidy=subsidy,
        net_cost=net_cost,
        bill_before=round(bill_before),
        bill_after=round(bill_after),
        first_year_savings=round(first_year),
        surplus_units=round(credit_units),
        surplus_credit=round(surplus_credit),
        payback_years=round(payback, 1) if payback is not None else None,
        lifetime_savings=round(lifetime - net_cost),
        rate_basis=rate_basis,
        notes=notes,
    )
