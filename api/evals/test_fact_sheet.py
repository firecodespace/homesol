"""Offline tests for what the advisor is told and how its tools answer. No model calls.

Run: .venv/bin/python -m pytest evals/test_fact_sheet.py
"""

import json
from pathlib import Path

import pytest

from homesol import agents

SURVEYS = {name: h["survey"] for name, h in json.loads((Path(__file__).parent / "cases.json").read_text())["households"].items()}


def test_every_eval_household_gets_a_fact_sheet():
    for survey in SURVEYS.values():
        assert agents.fact_sheet(survey).startswith("LOCATION")


def test_surface_kinds_are_said_in_plain_words():
    assert "a sloped roof facing south-west, tilted about 24 degrees" in agents.fact_sheet(SURVEYS["us_quote"])
    assert "open, level land on the ground (not a roof)" in agents.fact_sheet(SURVEYS["gj_land"])
    assert "a hillside facing north" in agents.fact_sheet(SURVEYS["au_hillside"])
    assert "ESTIMATES worked out from what the household marked by hand" in agents.fact_sheet(SURVEYS["mh_600_small_roof"])


def test_money_is_in_the_survey_currency():
    us = agents.fact_sheet(SURVEYS["us_quote"])
    assert "USD 21,500" in us and "₹" not in us and "lakh" not in us and "PM Surya Ghar" not in us
    india = agents.fact_sheet(SURVEYS["mh_300"])
    assert "₹1,65,000 (₹1.65 lakh)" in india and "USD" not in india


def test_unknown_price_and_payback_are_said_to_be_unknown():
    facts = agents.fact_sheet(SURVEYS["us_noquote"])
    assert "Price of the system: NOT KNOWN" in facts and "CANNOT be worked out" in facts
    assert "Saved in the first year: USD" in facts
    assert "Years until the system has paid for itself" not in facts
    assert "MONEY: NOT CALCULATED" in agents.fact_sheet(SURVEYS["de_nobill"])


@pytest.mark.parametrize("missing", ["location", "surface", "sun", "obstructions", "panels", "household", "recommended_system"])
def test_a_missing_or_empty_part_of_the_survey_is_coped_with(missing):
    base = SURVEYS["delhi_450"]
    for value in (None, {}):
        facts = agents.fact_sheet({**base, missing: value})
        assert "None" not in facts and "null" not in facts


def test_null_fields_are_named_as_missing_not_filled_in():
    survey = json.loads(json.dumps(SURVEYS["delhi_450"]))
    for part in ("location", "surface", "sun", "panels", "household"):
        survey[part] = {key: None for key in survey[part]}
    survey["obstructions"] = [{key: None for key in survey["obstructions"][0]}]
    facts = agents.fact_sheet(survey)
    assert "None" not in facts
    assert "Where the property is was not recorded." in facts
    assert "How much sun reaches the surface was not worked out." in facts
    assert "MONEY: NOT CALCULATED" in facts
    assert "RECOMMENDED SYSTEM: none yet" in agents.fact_sheet({**survey, "recommended_system": None})


def test_a_survey_with_no_country_is_not_given_indian_subsidies():
    survey = {**SURVEYS["us_quote"], "location": None}
    facts = agents.fact_sheet(survey)
    assert "PM Surya Ghar" not in facts and "₹" not in facts
    # A supported Indian distributor is enough to say the home is in India.
    assert "PM Surya Ghar" in agents.fact_sheet({**SURVEYS["mh_300"], "location": None})


def test_a_recalculation_is_labelled_and_handed_on_word_for_word():
    calculations: list[str] = []
    _, estimate = agents.survey_tools(SURVEYS["mh_600_small_roof"], calculations)
    text = estimate(system_kw=5)
    assert text.startswith("CALCULATION for a 5 kW system") and "does NOT fit" in text and "2.2 kW" in text
    assert calculations == [text]
    _, estimate = agents.survey_tools(SURVEYS["us_noquote"])
    assert "Years until the system has paid for itself: 10.7." in estimate(quoted_cost=14000)
    assert estimate(quoted_cost=-1).startswith("ERROR")


def test_policy_lookup_has_nothing_outside_india():
    lookup, _ = agents.survey_tools(SURVEYS["us_quote"])
    assert "India only" in json.loads(lookup())["error"]
    lookup, _ = agents.survey_tools(SURVEYS["mh_300"])
    assert json.loads(lookup())["distributor"]["state"] == "Maharashtra"
    assert json.loads(lookup(state="Gujarat"))["distributor"]["state"] == "Gujarat"
    assert "distributor_error" in json.loads(lookup(state="Kerala"))


def test_history_becomes_alternating_turns_that_start_with_the_household():
    history = [
        {"role": "assistant", "text": "Hello"},
        {"role": "user", "text": "Is it worth it?"},
        {"role": "user", "text": "For my home"},
        {"role": "assistant", "text": " Yes. "},
        {"role": "assistant", "text": ""},
        {"role": "system", "text": "ignored"},
    ]
    assert agents._turns(history) == [{"role": "user", "text": "Is it worth it?\n\nFor my home"}, {"role": "assistant", "text": "Yes."}]
    assert agents._turns(None) == []


def test_only_claude_46_and_later_are_sent_thinking_and_effort():
    assert agents._TAKES_EFFORT.search("us.anthropic.claude-opus-4-6-v1") and agents._TAKES_EFFORT.search("us.anthropic.claude-sonnet-4-6")
    assert not agents._TAKES_EFFORT.search("us.anthropic.claude-haiku-4-5-20251001-v1:0")
    assert not agents._TAKES_EFFORT.search("us.amazon.nova-pro-v1:0")
