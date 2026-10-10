import pytest

from homesol import finance, policy

MSEDCL = policy.get_discom("msedcl")["tariff"]


@pytest.mark.parametrize("kw,expected", [(1, 30000), (1.65, 49500), (2, 60000), (2.75, 73500), (3, 78000), (5.5, 78000)])
def test_central_subsidy_tiers(kw, expected):
    assert policy.central_subsidy(kw) == expected


def test_slab_bill_charges_each_slab_at_its_own_rate():
    # 150 fixed + 100 x 3.25 + 200 x 6.14 + 50 x 8.45
    assert finance.slab_bill(350, MSEDCL) == pytest.approx(150 + 325 + 1228 + 422.5)
    assert finance.slab_bill(0, MSEDCL) == 150


def test_state_maps_to_discom():
    assert policy.discom_for_state("Maharashtra") == "msedcl"
    assert policy.discom_for_state(" NCT of Delhi ") == "delhi"
    assert policy.discom_for_state("Kerala") is None


def test_system_matching_usage_cuts_the_bill_to_the_fixed_charge():
    f = finance.estimate(system_kw=2.75, monthly_generation=[300] * 12, monthly_usage=300, discom_id="msedcl")
    assert f.subsidy == 73500
    assert f.gross_cost == 165000
    assert f.net_cost == 91500
    assert f.bill_after == 150 * 12
    assert f.first_year_savings == f.bill_before - f.bill_after
    assert 3 < f.payback_years < 7
    assert f.lifetime_savings > f.net_cost


def test_summer_surplus_carries_into_monsoon_months():
    seasonal = [400, 400, 400, 400, 400, 400, 200, 200, 200, 200, 200, 200]
    flat = [300] * 12
    kwargs = dict(system_kw=2.75, monthly_usage=300, discom_id="msedcl")
    assert finance.estimate(monthly_generation=seasonal, **kwargs).bill_after == finance.estimate(
        monthly_generation=flat, **kwargs
    ).bill_after


def test_year_end_surplus_is_paid_at_the_discom_rate_or_flagged():
    over = dict(system_kw=3.3, monthly_generation=[400] * 12, monthly_usage=300)
    mh = finance.estimate(discom_id="msedcl", **over)
    assert mh.surplus_units == 1200
    assert mh.surplus_credit == round(1200 * 2.82)

    delhi = finance.estimate(discom_id="delhi", **over)
    assert delhi.surplus_credit == 0
    assert any("surplus units" in n for n in delhi.notes)


def test_own_bill_and_quote_override_the_defaults():
    f = finance.estimate(
        system_kw=2.75, monthly_generation=[300] * 12, monthly_usage=300, monthly_bill=2700, quoted_cost=180000
    )
    assert f.rate_basis == "your_bill"
    assert f.cost_is_quote and f.gross_cost == 180000
    assert f.bill_before == 2700 * 12
    assert f.bill_after == 0


def test_needs_a_bill_or_a_discom():
    with pytest.raises(ValueError):
        finance.estimate(system_kw=2, monthly_generation=[200] * 12, monthly_usage=200)
