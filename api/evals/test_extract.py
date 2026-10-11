"""Offline tests for the number extractor and matcher. Run: .venv/bin/python -m pytest evals/test_extract.py"""

import pytest

from evals.checks import matches
from evals.extract import language_of, quantities, stopword_shares


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
        ("The quote of $21,500 pays back in 12.7 years", [("money", 21500), ("years", 12.7)]),
        ("you pay about 15 cents a unit", [("money", 0.15)]),
        ("minus 60 paise a unit", [("money", 0.6)]),
        ("tilted 24 degrees, facing south-west", [("degrees", 24)]),
        ("a 24° slope", [("degrees", 24)]),
        ("about 5.8 hours of full sun", [("hours", 5.8)]),
        ("each panel is rated 550 W", [("watts", 550)]),
        ("a 7.7 kW system of 14 panels on 2 floors", [("kw", 7.7), ("panels", 14), ("floors", 2)]),
        ("the tree is 6.5 m away and rises 3.8 m above the roof", [("metres", 6.5), ("metres", 3.8)]),
        ("approval comes within 30 days", [("days", 30)]),
        ("in full sun from 10:00 to 15:50 in winter", [("time", 600), ("time", 950)]),
        ("from 9:40 am to 4:10 pm", [("time", 580), ("time", 970)]),
        ("from about 10 am until 4 pm", [("time", 600), ("time", 960)]),
        ("सुबह 9:40 से शाम 4:10 बजे तक", [("time", 580), ("time", 250)]),
    ],
)
def test_extraction(text, expected):
    assert found(text) == [(k, pytest.approx(v, abs=0.002)) for k, v in expected]


@pytest.mark.parametrize(
    "text,currency",
    [
        ("₹1.65 lakh", "INR"),
        ("Rs. 91,500", "INR"),
        ("1.65 lakh", "INR"),
        ("78,000 rupaye", "INR"),
        ("$21,500", "DOLLAR"),
        ("US$21,500", "USD"),
        ("USD 1,620 a year", "USD"),
        ("0.15 USD a unit", "USD"),
        ("A$9,800", "AUD"),
        ("AUD 2,520", "AUD"),
        ("1,546 dollars", "DOLLAR"),
        ("€4,200", "EUR"),
        ("£900", "GBP"),
        ("$1,546 to $1,620", "DOLLAR"),
    ],
)
def test_currency(text, currency):
    first = quantities(text)[0]
    assert (first.kind, first.currency) == ("money", currency)


def test_afternoon_reading_of_a_bare_clock_time():
    assert quantities("शाम 4:10 बजे")[0].alt == 970
    assert quantities("16:10")[0].alt is None


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


def test_other_languages_by_everyday_words():
    german = stopword_shares("Das kann homesol noch nicht berechnen, weil Sie Ihre monatliche Stromrechnung nicht eingegeben haben.")
    english = stopword_shares("homesol cannot work that out yet, because you have not entered your monthly electricity bill.")
    assert german["de"] > 0.25 > german["en"]
    assert english["en"] > 0.25 > english["de"]
