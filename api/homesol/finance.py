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


#: Sanctioned load assumed when the household has not given theirs.
DEFAULT_LOAD_KW = 3.0


def fixed_charge(tariff: dict, load_kw: float) -> float:
    """Monthly fixed charge in rupees for a home with this sanctioned load."""
    fixed = tariff["fixed_charge"]
    if fixed["type"] == "flat":
        return float(fixed["amount"])
    band = next(b for b in fixed["bands"] if b["up_to_kw"] is None or load_kw <= b["up_to_kw"])
    return band["rate"] * load_kw if fixed["type"] == "per_kw" else float(band["amount"])


def slab_bill(units: float, tariff: dict, load_kw: float = DEFAULT_LOAD_KW) -> float:
    """
    Monthly bill in rupees for `units` under a slab tariff.

    Each slab's units are charged at that slab's rate. The fixed charge is added,
    then any percentage surcharge is applied to the total.
    """
    total, lower = fixed_charge(tariff, load_kw), 0.0
    for slab in tariff["slabs"]:
        upper = slab["up_to"] if slab["up_to"] is not None else float("inf")
        if units > lower:
            total += (min(units, upper) - lower) * slab["rate"]
        lower = upper
    return total * (1 + tariff.get("surcharge_percent", 0) / 100)


def estimate(
    *,
    system_kw: float,
    monthly_generation: list[float],
    monthly_usage: float,
    discom_id: str | None = None,
    monthly_bill: float | None = None,
    quoted_cost: float | None = None,
    sanctioned_load_kw: float | None = None,
) -> Finance:
    """
    Cost, subsidy, bill savings and payback for one system.

    Savings follow the distributor's net-metering rule. Each month's solar units
    offset that month's usage. Where settlement is annual, excess units carry
    forward as credit and whatever is left at year end is paid at the surplus
    rate. Where settlement is monthly, each month's excess is paid at the
    surplus rate straight away and nothing carries forward. Without a known
    distributor, annual carry-forward is assumed and surplus is worth nothing.

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
        load_kw = sanctioned_load_kw or DEFAULT_LOAD_KW
        price = lambda units: slab_bill(units, discom["tariff"], load_kw)  # noqa: E731
        rate_basis = "discom_slabs"
        notes.append(f"Uses {discom['name']} rates: {discom['tariff']['includes']} ({discom['tariff']['order']}.)")
        notes.append(f"Leaves out: {discom['tariff']['excludes']}")
    else:
        raise ValueError("Give either a monthly bill amount or a supported DISCOM.")

    surplus_rate = policy.surplus_rate(discom, system_kw) if discom else None
    monthly_settlement = bool(discom) and discom["net_metering"]["settlement"] == "monthly"

    bill_before = price(monthly_usage) * 12
    bill_after, credit_units, surplus_units = 0.0, 0.0, 0.0
    for generated in monthly_generation:
        net = monthly_usage - generated - credit_units
        excess = max(0.0, -net)
        if monthly_settlement:
            surplus_units += excess
            credit_units = 0.0
        else:
            credit_units = excess
        bill_after += price(max(0.0, net))
    surplus_units += credit_units

    surplus_credit = surplus_units * surplus_rate if surplus_rate else 0.0
    if surplus_units >= 1 and not surplus_rate:
        notes.append(
            f"About {round(surplus_units)} surplus units a year are counted as worth nothing because "
            "the rate your distributor pays for them is not confirmed."
        )
    if discom and not discom["net_metering"]["verified"]:
        notes.append(f"Net-metering terms need confirming: {discom['net_metering'].get('note', '')}".strip())

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
        surplus_units=round(surplus_units),
        surplus_credit=round(surplus_credit),
        payback_years=round(payback, 1) if payback is not None else None,
        lifetime_savings=round(lifetime - net_cost),
        rate_basis=rate_basis,
        notes=notes,
    )
