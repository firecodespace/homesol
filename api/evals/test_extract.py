"""Offline tests for the number extractor and matcher. Run: .venv/bin/python -m pytest evals/test_extract.py"""

import pytest

from evals.checks import matches
from evals.extract import language_of, quantities


def found(text):
    return [(q.kind, round(q.value, 3)) for q in quantities(text)]


@pytest.mark.parametrize(
    "text,expected",
    [
        ("It costs ₹1.65 lakh before subsidy.", [("money", 165000)]),
        ("It costs Rs. 1,65,000 before subsidy.", [("money", 165000)]),
        ("It costs Rs.165,000.", [("money", 165000)]),
        ("आपको ₹78,000 की सब्सिडी मिलेगी।", [("money", 78000)]),
        ("आपको ७८,००० रुपये की सब्सिडी मिलेगी।", [("money", 78000)]),
        ("लागत लगभग १.६५ लाख रुपये है", [("money", 165000)]),
        ("लागत लगभग 1.65 लाख है", [("money", 165000)]),
        ("subsidy 78 hazaar rupaye milegi", [("money", 78000)]),
        ("subsidy 78 हज़ार की है", [("money", 78000)]),
        ("kharcha ₹91.5k aayega", [("money", 91500)]),
        ("net cost ₹1.65L", [("money", 165000)]),
        ("kharcha dhai lakh rupaye", [("money", 250000)]),
        ("साढ़े तीन लाख रुपये", [("money", 350000)]),
        ("Subsidy 78,000 milegi", [("bare", 78000)]),
        ("pays back in about 5 years", [("years", 5)]),
        ("pays back in 4.8 years", [("years", 4.8)]),
        ("लगभग ४.८ साल में", [("years", 4.8)]),
        ("lagbhag paanch saal mein", [("years", 5)]),
        ("करीब पाँच साल में", [("years", 5)]),
        ("साढ़े चार साल में", [("years", 4.5)]),
        ("in about five years", [("years", 5)]),
        ("4-5 years", [("years", 4), ("years", 5)]),
        ("4 से 5 साल", [("years", 4), ("years", 5)]),
        ("4 years and 10 months", [("years", 4.833)]),
        ("a 25-year life", [("years", 25)]),
        ("₹1.55 lakh to ₹2.41 lakh", [("money", 155000), ("money", 241000)]),
        ("₹1.55–2.41 lakh", [("money", 155000), ("money", 241000)]),
        ("Rs 2.82 per unit", [("money", 2.82)]),
        ("₹6.14/unit for 300 units on a 2.75 kW system", [("money", 6.14), ("units", 300), ("kw", 2.75)]),
        ("covers 91% of 4,015 kWh", [("percent", 91), ("units", 4015)]),
        ("fixed from April 2026 by MERC", []),
        ("see https://solarquarter.com/2026/07/20/delhi-guidelines-2026 for more", []),
        ("in the 1st year", []),
        ("aap form bhar do aur 2 step follow karo", []),
    ],
)
def test_extraction(text, expected):
    assert found(text) == [(k, pytest.approx(v, abs=0.002)) for k, v in expected]


def q(text):
    return quantities(text)[0]


@pytest.mark.parametrize(
    "text,truth,ok",
    [
        ("about 5 years", 4.8, True),
        ("4.8 years", 4.8, True),
        ("9.6 years", 4.8, False),
        ("4 years", 4.8, False),
        ("₹1.65 lakh", 165000, True),
        ("₹1.6 lakh", 163800, True),
        ("₹2 lakh", 165000, False),
        ("₹91,500", 91532, True),
        ("₹91,000", 91532, False),
        ("₹92,000", 91532, True),
        ("₹1,65,000", 166200, False),
        ("78 हज़ार रुपये", 78000, True),
        ("₹2.8 per unit", 2.82, True),
    ],
)
def test_rounding_tolerance(text, truth, ok):
    assert bool(matches(q(text), [(truth, "t")])) is ok


@pytest.mark.parametrize(
    "text,label",
    [
        ("Yes, solar looks worth it for your home. It should pay for itself in about 5 years.", "en"),
        ("हाँ, आपके घर के लिए सोलर फ़ायदेमंद है। यह लगभग 5 साल में अपनी लागत वसूल कर लेगा। PM Surya Ghar", "hi"),
        ("Haan, aapke ghar ke liye solar sahi rahega. Lagbhag 5 saal mein paisa wasool ho jayega.", "hinglish"),
        ("Yes, solar is worth it. यह लगभग 5 साल में वसूल हो जाएगा।", "mixed"),
        ("You get ₹78,000 under PM Surya Ghar: Muft Bijli Yojana. Apply at the national portal.", "en"),
    ],
)
def test_language(text, label):
    assert language_of(text)["label"] == label
