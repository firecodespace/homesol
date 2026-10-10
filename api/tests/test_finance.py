import pytest

from homesol import finance, policy

MSEDCL = policy.get_discom("msedcl")["tariff"]


@pytest.mark.parametrize("kw,expected", [(1, 30000), (1.65, 49500), (2, 60000), (2.75, 73500), (3, 78000), (5.5, 78000)])
def test_central_subsidy_tiers(kw, expected):
    assert policy.central_subsidy(kw) == expected


def test_slab_bill_charges_each_slab_at_its_own_rate():
    # 130 fixed + 100 x 5.56 + 200 x 12.40 + 50 x 16.64
    assert finance.slab_bill(350, MSEDCL) == pytest.approx(130 + 556 + 2480 + 832)
    assert finance.slab_bill(0, MSEDCL) == 130


def test_fixed_charge_follows_each_distributors_rule():
    delhi = policy.get_discom("delhi")["tariff"]
    gujarat = policy.get_discom("gujarat")["tariff"]
    bescom = policy.get_discom("bescom")["tariff"]
    assert finance.fixed_charge(MSEDCL, 3) == 130
    assert finance.fixed_charge(delhi, 2) == 40 and finance.fixed_charge(delhi, 3) == 150
    assert finance.fixed_charge(gujarat, 3) == 25
    assert finance.fixed_charge(bescom, 3) == 450


def test_percentage_surcharge_applies_to_fixed_and_energy_charges():
    delhi = policy.get_discom("delhi")["tariff"]
    # (3 kW x 50 fixed + 200 x 3.00 + 100 x 4.50) x 1.15
    assert finance.slab_bill(300, delhi, 3) == pytest.approx((150 + 600 + 450) * 1.15)


def test_state_maps_to_discom():
    assert policy.discom_for_state("Maharashtra") == "msedcl"
    assert policy.discom_for_state(" NCT of Delhi ") == "delhi"
    assert policy.discom_for_state("Gujarat") == "gujarat"
    assert policy.discom_for_state("Kerala") is None


def test_system_matching_usage_cuts_the_bill_to_the_fixed_charge():
    f = finance.estimate(system_kw=2.75, monthly_generation=[300] * 12, monthly_usage=300, discom_id="msedcl")
    assert f.subsidy == 73500
    assert f.gross_cost == 165000
    assert f.net_cost == 91500
    assert f.bill_before == round((130 + 556 + 2480) * 12)
    assert f.bill_after == 130 * 12
    assert f.first_year_savings == f.bill_before - f.bill_after
    assert 2 < f.payback_years < 4
    assert f.lifetime_savings > f.net_cost


def test_annual_settlement_carries_summer_surplus_into_monsoon_months():
    seasonal = [400, 400, 400, 400, 400, 400, 200, 200, 200, 200, 200, 200]
    flat = [300] * 12
    kwargs = dict(system_kw=2.75, monthly_usage=300, discom_id="msedcl")
    assert finance.estimate(monthly_generation=seasonal, **kwargs).bill_after == finance.estimate(
        monthly_generation=flat, **kwargs
    ).bill_after


def test_monthly_settlement_pays_each_months_surplus_and_carries_nothing():
    seasonal = [400] * 6 + [200] * 6
    f = finance.estimate(system_kw=2.75, monthly_generation=seasonal, monthly_usage=300, discom_id="bescom")
    # Six months export 100 units each at the 2 to 3 kW rate; six months still buy 100 units.
    assert f.surplus_units == 600
    assert f.surplus_credit == round(600 * 2.14)
    assert f.bill_after == round((450 + 0) * 6 + (450 + 100 * 5.80) * 6)


def test_surplus_rate_depends_on_system_size_where_the_regulator_says_so():
    bescom = policy.get_discom("bescom")
    assert [policy.surplus_rate(bescom, kw) for kw in (1.65, 2.75, 4.4)] == [1.96, 2.14, 2.58]
    assert policy.surplus_rate(policy.get_discom("msedcl"), 5) == 2.82


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


def test_advisor_finances_come_from_the_survey_and_scale_with_size():
    from homesol.agents import baseline_finances

    survey = {
        "household": {"monthly_units": 300, "discom_id": "msedcl", "monthly_bill_rupees": None, "vendor_quote_rupees": None},
        "recommended_system": {"system_kw": 2.75, "monthly_generation_units": [300] * 12},
    }
    base = baseline_finances(survey)
    assert base["system_kw"] == 2.75 and base["subsidy"] == 73500 and base["net_cost"] == 91500

    smaller = baseline_finances(survey, system_kw=1.1)
    assert smaller["subsidy"] == 33000
    assert smaller["first_year_savings"] < base["first_year_savings"]

    assert "error" in baseline_finances({"household": {}, "recommended_system": None})


SURVEY = {
    "roof": {"area_m2": 80, "usable_area_m2": 70, "yearly_sun_reaching_roof": 0.95, "max_system_kw": 7, "height_m": 6, "skyline_scanned": True},
    "obstructions": [{"kind": "tank", "height_m": 2, "height_from": "roof", "height_source": "entered by user"}],
    "household": {"monthly_units": 300, "discom_id": "msedcl", "monthly_bill_rupees": None, "vendor_quote_rupees": 340000},
    "recommended_system": {"system_kw": 2.75, "panels": 5, "monthly_generation_units": [300] * 12, "share_of_usage_covered": 1.0, "limited_by": "usage"},
}


def test_fact_sheet_labels_periods_and_flags_an_overpriced_quote():
    from homesol.agents import fact_sheet

    facts = fact_sheet(SURVEY)
    assert "PER YEAR" in facts and "a month)" in facts
    assert "69% ABOVE the top of the usual range" in facts
    assert "has been done." in facts
    assert "Rs 3,40,000" not in facts and "Rs 340,000" in facts


def test_what_if_size_does_not_reuse_the_quote_for_the_recommended_size():
    from homesol.agents import baseline_finances

    assert baseline_finances(SURVEY)["cost_is_quote"] is True
    assert baseline_finances(SURVEY, system_kw=1.65)["cost_is_quote"] is False


def test_clean_answer_strips_reasoning_markdown_and_unknown_links():
    from homesol.agents import clean_answer

    raw = (
        "<thinking> The household wants the subsidy. </thinking>\n\n"
        "**Subsidy:** Rs 73,500. [Source](https://example.com/made-up) and "
        "[apply here](https://pmsuryaghar.gov.in).\n# Next\n* Get a quote"
    )
    cleaned = clean_answer(raw)
    assert "thinking" not in cleaned and "**" not in cleaned and "#" not in cleaned
    assert "example.com" not in cleaned
    assert "apply here (https://pmsuryaghar.gov.in)" in cleaned
    assert cleaned.endswith("- Get a quote")
