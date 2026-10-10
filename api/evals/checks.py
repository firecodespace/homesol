"""Deterministic checks on one advisor answer. No model calls happen here.

Each check returns {"pass": True | False | None, "detail": ...}; None means the
check does not apply to that case and is left out of the pass rate.
"""

from __future__ import annotations

import json
import re

from homesol import finance, policy
from homesol.agents import baseline_finances

from .extract import Quantity, language_of, normalise, quantities, strip_urls

WORD_LIMIT = 150
#: Kinds that are checked by the two headline number checks.
MONEY_KINDS = ("money",)
YEAR_KINDS = ("years", "months")
OTHER_KINDS = ("units", "kw", "percent", "panels", "area", "metres", "bare")
POOLS = ("money", "years", "units", "kw", "percent", "panels", "area", "metres", "any")

#: Finance fields that depend on the electricity price, so on the tariff slabs when rate_basis is discom_slabs.
SLAB_FIELDS = ("bill_before", "bill_after", "first_year_savings", "payback_years", "lifetime_savings", "surplus_credit")

_UNVERIFIED = re.compile(
    normalise(
        r"unverif|not (?:yet |been |fully |officially )*(?:verified|checked|confirmed)|"
        r"needs? (?:to be |further )?(?:check|verif|confirm)|still needs? check|indicative|provisional|"
        r"yet to be (?:verified|checked|confirmed)|verify|double.check|cross.check|सत्यापि|सत्यापन|पुष्टि|जा[ँं]च|अपुष्ट|सांकेतिक|"
        r"jaa?nch|pakk[ai] nahi|confirm nahi|check (?:nahi|kar)|चेक"
    ),
    re.I,
)

_PRICE_DATA = re.compile(normalise(r"rate|tariff|slab|regulator|net.?meter|surplus|दर|टैरिफ|स्लैब|नियामक|नेट मीटरिंग|अधिशेष"), re.I)
_LINE = re.compile(r"(?<=[.!?।])\s+|\n+")

# ---- what is true for this case -------------------------------------------


def _tolerance(q: Quantity, truth: float) -> float:
    """How far a stated figure may sit from the true one and still be honest rounding.

    Half of the last digit the writer stated ("about 5 years" covers 4.5-5.5,
    "₹1.6 lakh" covers ₹1.55-1.65 lakh). For amounts it is never more than 5%
    of the true figure, so "₹2 lakh" does not cover ₹1.65 lakh, and never less
    than 0.5%, so ₹91,500 covers ₹91,532 whatever the digits look like.
    """
    half = q.step / 2
    if q.kind == "percent":
        return (1.0 if q.step >= 1 else half) + 1e-9  # "75%" for a measured 0.74, but not "10%" for 12
    if q.kind in ("years", "months", "kw", "panels", "metres"):
        return half + 1e-9
    return min(max(half, 0.005 * abs(truth)), max(0.05 * abs(truth), 0.005)) + 1e-9


def matches(q: Quantity, pool: list[tuple[float, str]]) -> list[str]:
    """Labels of the true figures this stated quantity agrees with."""
    return [label for truth, label in pool if abs(q.value - truth) <= _tolerance(q, truth)]


def _finance_truths(fin: dict, tag: str, truth: dict) -> None:
    if not fin or "error" in fin:
        return
    for key in ("gross_cost", "subsidy", "net_cost", "bill_before", "bill_after", "first_year_savings", "surplus_credit", "lifetime_savings"):
        truth["money"].append((fin[key], f"{tag}.{key}"))
    for key in ("bill_before", "bill_after", "first_year_savings"):
        truth["money"].append((fin[key] / 12, f"{tag}.{key}/12"))
    truth["money"].append((fin["gross_cost_range"][0], f"{tag}.gross_cost_range.low"))
    truth["money"].append((fin["gross_cost_range"][1], f"{tag}.gross_cost_range.high"))
    truth["money"].append((fin["lifetime_savings"] + fin["net_cost"], f"{tag}.lifetime_savings+net_cost"))
    if fin["payback_years"] is not None:
        truth["years"].append((fin["payback_years"], f"{tag}.payback_years"))
        truth["years"].append((fin["payback_years"] * 12, f"{tag}.payback_years(months)"))
    truth["kw"].append((fin["system_kw"], f"{tag}.system_kw"))
    truth["units"].append((fin["surplus_units"], f"{tag}.surplus_units"))
    for note in fin["notes"]:
        _text_truths(note, f"{tag}.notes", truth)


def _text_truths(text: str, tag: str, truth: dict, any_unit: bool = False) -> None:
    for q in quantities(text):
        bucket = "years" if q.kind in YEAR_KINDS else "any" if q.kind == "bare" else q.kind
        truth[bucket].append((q.value / 12 if q.kind == "months" else q.value, tag))
    if any_unit:  # a plain number the household typed is fair to repeat with a unit attached
        for raw in re.findall(r"\d+(?:\.\d+)?", normalise(text).replace(",", "")):
            truth["any"].append((float(raw), tag))


def _walk(node, path: str):
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _walk(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _walk(v, f"{path}[{i}]")
    else:
        yield path, node


_MONEY_KEYS = ("rate", "fixed_charge", "amount", "surplus_rate", "per_kw_first_2kw", "per_kw_third_kw", "max_total", "low", "typical", "high")


def snapshot(case: dict, survey: dict) -> dict:
    """What is true for this case right now, taken from the live finance code and policy data.

    Stored with each result, so that saved answers can be re-scored later against the figures the advisor was
    actually given, even after the tariff data or the finance code has changed.
    """
    household = survey.get("household") or {}
    what_if = case.get("what_if")
    data = policy.load()
    discom_ids = [d for d in [household.get("discom_id"), *case.get("extra_discoms", [])] if d and policy.get_discom(d)]
    sections = {"central_subsidy": data["central_subsidy"], "system_cost_per_kw": data["system_cost_per_kw"]}
    sections.update({f"discoms.{d}": data["discoms"][d] for d in discom_ids})
    fixed = {}
    for d in discom_ids:
        tariff = data["discoms"][d]["tariff"]
        charge = tariff["fixed_charge"]
        fixed[d] = finance.fixed_charge(tariff, finance.DEFAULT_LOAD_KW) if isinstance(charge, dict) else charge
    return {
        "baseline": baseline_finances(survey),
        "what_if": baseline_finances(survey, what_if.get("system_kw"), what_if.get("quoted_cost")) if what_if else None,
        "policy": sections,
        "subsidy_by_kw": {str(kw): policy.central_subsidy(kw) for kw in (1, 2, 3)},
        "fixed_charge_per_month": fixed,
        "life_years": finance.SYSTEM_LIFE_YEARS,
        "tariff_escalation_percent": finance.TARIFF_ESCALATION * 100,
        "panel_degradation_percent": finance.PANEL_DEGRADATION * 100,
        "known_links": sorted({str(leaf) for path, leaf in _walk(data, "policy") if path.endswith((".source", ".apply_at"))}),
    }


def build_truth(case: dict, survey: dict, tool_calls: list[dict], snap: dict) -> dict:
    """Every figure the advisor could legitimately state for this case, by kind, each with where it comes from."""
    truth: dict = {name: [] for name in POOLS}
    household = survey.get("household") or {}
    system = survey.get("recommended_system") or {}

    baseline = snap["baseline"]
    _finance_truths(baseline, "baseline", truth)
    expected = snap.get("what_if")
    if expected:
        _finance_truths(expected, "whatif", truth)

    # Recalculations the specialist really ran, as the tool returned them. Whether their arguments were
    # justified is a separate check.
    for call in tool_calls:
        if call["tool"] == "estimate_finances":
            try:
                returned = json.loads(call.get("output") or "")
            except ValueError:
                continue
            if isinstance(returned, dict) and "gross_cost" in returned:
                _finance_truths(returned, f"toolcall{_args(call.get('input') or {})}", truth)

    sections = snap["policy"]
    cost = sections["system_cost_per_kw"]
    for name, section in sections.items():
        for path, leaf in _walk(section, f"policy.{name}"):
            if isinstance(leaf, bool) or leaf is None:
                continue
            if isinstance(leaf, (int, float)):
                key = path.rsplit(".", 1)[-1]
                bucket = "money" if key in _MONEY_KEYS else "percent" if "percent" in key else "kw" if key.endswith("_kw") else "units"
                truth[bucket].append((leaf, path))
            elif not path.endswith(".source") and not path.endswith(".apply_at"):
                _text_truths(leaf, path, truth)
    for kw, amount in snap["subsidy_by_kw"].items():
        truth["money"].append((amount, f"policy.central_subsidy for {kw} kW"))
        truth["kw"].append((float(kw), "policy.central_subsidy tier"))
    for d, charge in snap["fixed_charge_per_month"].items():
        truth["money"] += [(charge, f"policy.discoms.{d}.tariff.fixed_charge"), (charge * 12, f"policy.discoms.{d}.tariff.fixed_charge x12")]

    truth["years"] += [(snap["life_years"], "finance.SYSTEM_LIFE_YEARS"), (1, "one year")]
    truth["percent"] += [(snap["tariff_escalation_percent"], "finance.TARIFF_ESCALATION"), (snap["panel_degradation_percent"], "finance.PANEL_DEGRADATION")]

    roof = survey.get("roof") or {}
    for path, leaf in _walk(survey, "survey"):
        if isinstance(leaf, bool) or not isinstance(leaf, (int, float)):
            continue
        key = path.rsplit(".", 1)[-1].split("[")[0]
        bucket = {"area_m2": "area", "usable_area_m2": "area", "height_m": "metres", "max_system_kw": "kw", "system_kw": "kw",
                  "monthly_units": "units", "monthly_generation_units": "units", "panels": "panels"}.get(key)
        if bucket:
            truth[bucket].append((leaf, path))
    for i, o in enumerate(survey.get("obstructions") or []):
        if o.get("height_m") is not None and o.get("height_from") == "ground" and roof.get("height_m") is not None:
            truth["metres"].append((o["height_m"] - roof["height_m"], f"survey.obstructions[{i}] height above the roof"))
    bill, quote, units = household.get("monthly_bill_rupees"), household.get("vendor_quote_rupees"), household.get("monthly_units")
    if bill:
        truth["money"] += [(bill, "survey.household.monthly_bill_rupees"), (bill * 12, "survey.monthly_bill x12")]
        if units:
            truth["money"].append((bill / units, "survey bill / units"))
    if system.get("system_kw"):
        kw = system["system_kw"]
        truth["money"].append((kw * cost["typical"], "policy typical cost x system_kw"))
        if quote:
            truth["money"] += [
                (quote, "survey.household.vendor_quote_rupees"),
                (quote / kw, "quote per kW"),
                (quote - kw * cost["high"], "quote minus top of usual range"),
                (quote - kw * cost["typical"], "quote minus typical cost"),
            ]
            truth["percent"].append(((quote / (kw * cost["high"]) - 1) * 100, "quote % above top of usual range"))
            truth["percent"].append(((quote / (kw * cost["typical"]) - 1) * 100, "quote % above typical cost"))
        gen = system.get("monthly_generation_units") or []
        if gen:
            truth["units"] += [(sum(gen), "survey generation per year"), (sum(gen) / 12, "survey generation per month, average"), (sum(gen) / 365, "survey generation per day, average")]
        if system.get("share_of_usage_covered") is not None:
            share = system["share_of_usage_covered"] * 100
            truth["percent"] += [(share, "survey share_of_usage_covered %"), (100 - share, "survey share of usage not covered %")]
    if units:
        truth["units"].append((units * 12, "survey usage per year"))
    if roof.get("yearly_sun_reaching_roof") is not None:
        sun = roof["yearly_sun_reaching_roof"] * 100
        truth["percent"] += [(sun, "survey yearly_sun %"), (100 - sun, "survey shade %")]
    if roof.get("area_m2") and roof.get("usable_area_m2") is not None:
        truth["percent"].append((roof["usable_area_m2"] / roof["area_m2"] * 100, "survey usable share of roof %"))

    _text_truths(case["question"], "question", truth, any_unit=True)
    return {"pools": truth, "baseline": baseline, "what_if": expected, "snap": snap}


def _args(args: dict) -> str:
    kept = {k: v for k, v in args.items() if v is not None}
    return "(" + ", ".join(f"{k}={v}" for k, v in kept.items()) + ")" if kept else "()"


# ---- the checks ------------------------------------------------------------


def _trace(items: list[Quantity], kinds: tuple, pools: dict) -> tuple[list[dict], list[dict]]:
    """Split the answer's quantities of these kinds into traced and untraced."""
    traced, untraced = [], []
    for q in items:
        if q.kind not in kinds:
            continue
        if q.kind in YEAR_KINDS:
            pool = pools["years"] + pools["any"]
        elif q.kind == "bare":  # a big number with no unit: could be rupees or units
            pool = pools["money"] + pools["units"] + pools["any"]
        else:
            pool = pools[q.kind] + pools["any"]
        probe = q
        if q.kind == "months":
            if q.value <= 12:  # "every month", "12 months": not a payback figure
                traced.append({"text": q.text, "sources": ["a month count within one year"]})
                continue
            pool = [(v, label) for v, label in pool if label.endswith("(months)")]
        elif q.kind == "years":
            pool = [(v, label) for v, label in pool if not label.endswith("(months)")]
        labels = matches(probe, pool)
        if not labels and q.range_with is not None:
            # "4-5 years" for 4.8, "₹35,000-40,000" for ₹37,400: a narrow range that brackets a true figure.
            other = items[q.range_with]
            lo, hi = sorted((q.value, other.value))
            if lo > 0 and (hi / lo <= 1.3 or q.kind == "years" and hi - lo <= 1):
                labels = [f"range brackets {label}" for v, label in pool if lo <= v <= hi]
        entry = {"text": q.text, "value": round(q.value, 3), "kind": q.kind, "context": q.context}
        if labels:
            traced.append({"text": q.text, "sources": sorted(set(labels))})
        else:
            untraced.append(entry)
    return traced, untraced


_THINKING = re.compile(r"<(thinking|reasoning|scratchpad)>.*?(?:</\1>|\Z)", re.S | re.I)
_TAG = re.compile(r"</?[A-Za-z_][\w-]*>")


def visible_answer(answer: str) -> str:
    """The answer without leaked reasoning blocks or wrapper tags, so one leak is not counted against every check."""
    return _TAG.sub("", _THINKING.sub("", answer)).strip()


def check_leak(answer: str) -> dict:
    """The chat window shows the answer as-is, so a <thinking> block or any tag reaches the household."""
    tags = sorted(set(_TAG.findall(answer)))
    return {"pass": not tags, "detail": {"tags": tags, "leaked_words": len(answer.split()) - len(visible_answer(answer).split())}}


_SENTENCE = re.compile(r"(?<=[.!?।:])\s+|\n+")


def check_language(case: dict, answer: str) -> dict:
    """The whole answer is in the question's language, and no long sentence inside it switches to another."""
    got = language_of(answer)
    strays = []
    for part in _SENTENCE.split(strip_urls(answer)):
        if len(re.findall(r"[A-Za-z\u0900-\u097f]{2,}", part)) < 8:
            continue
        seg = language_of(part)
        english = seg["devanagari_share"] == 0 and seg["romanised_hindi_share"] == 0
        wrong = {
            "en": seg["label"] != "en",
            "hi": seg["devanagari_share"] < 0.3,
            "hinglish": english or seg["devanagari_share"] > 0.3,
        }[case["lang"]]
        if wrong:
            strays.append({"sentence": part.strip()[:160], "looks_like": "en" if english else seg["label"]})
    return {"pass": got["label"] == case["lang"] and not strays, "detail": {"expected": case["lang"], **got, "sentences_in_another_language": strays}}


def check_numbers(items: list[Quantity], kinds: tuple, pools: dict) -> dict:
    traced, untraced = _trace(items, kinds, pools)
    if not traced and not untraced:
        return {"pass": None, "detail": "no such figures in the answer"}
    return {"pass": not untraced, "detail": {"untraced": untraced, "traced": traced}}


def _resolve(name, truth: dict):
    """A fact named in a case ("payback_years", "whatif.net_cost", "bill_after/12") as (value, description)."""
    if isinstance(name, (int, float)):
        return float(name), str(name)
    source = truth["baseline"]
    label = name
    if name.startswith("whatif."):
        source, name = truth["what_if"], name[len("whatif.") :]
    divide = 1
    if name.endswith("/12"):
        name, divide = name[:-3], 12
    if not source or "error" in source:
        return None, label
    value = source["gross_cost_range"][int(name.rsplit(".", 1)[1])] if name.startswith("gross_cost_range.") else source.get(name)
    return (None if value is None else value / divide), label


def check_required(case: dict, answer: str, items: list[Quantity], truth: dict) -> dict:
    """The facts a good answer to this question has to contain."""
    required = case.get("must_include") or []
    if not required:
        return {"pass": None, "detail": "nothing required for this case"}
    text = normalise(answer).lower()
    missing, present = [], []
    for need in required:
        kind, spec = next(iter(need.items()))
        options = spec if isinstance(spec, list) else [spec]
        if kind == "text":
            hit = next((o for o in options if normalise(o).lower() in text), None)
            (present if hit else missing).append({"text any of": options} if not hit else {"text": hit})
            continue
        kinds = {"money": MONEY_KINDS + ("bare",), "years": YEAR_KINDS, "other": OTHER_KINDS}[kind]
        wanted = [(v * (12 if q_kind == "months" else 1), label, q_kind) for v, label in map(lambda o: _resolve(o, truth), options) if v is not None for q_kind in kinds]
        hit = None
        if kind == "money" and any(value == 0 for value, _, _ in wanted):
            zero = re.search(normalise(r"\bzero\b|\bnil\b|\bnothing\b|no bill|शून्य|shunya|sifar|कुछ नहीं"), text)
            if zero:
                hit = {"fact": wanted[0][1], "true": 0, "stated": zero.group(0)}
        for q in items:
            for value, label, q_kind in wanted:
                if q.kind == q_kind and matches(q, [(value, label)]):
                    hit = {"fact": label, "true": round(value, 2), "stated": q.text}
            if not hit and q.kind in kinds and q.range_with is not None and q.kind in YEAR_KINDS:
                lo, hi = sorted((q.value, items[q.range_with].value))
                for value, label, q_kind in wanted:
                    if q.kind == q_kind and hi - lo <= 1 and lo <= value <= hi:
                        hit = {"fact": label, "true": round(value, 2), "stated": f"{lo:g}-{hi:g}"}
        if hit:
            present.append(hit)
        else:
            missing.append({"fact": [label for _, label, _ in wanted][:1] or options, "true": [round(v, 2) for v, _, _ in wanted][:1], "kind": kind})
    return {"pass": not missing, "detail": {"missing": missing, "present": present}}


def check_length(case: dict, answer: str) -> dict:
    words = len(answer.split())
    if case.get("detail_requested"):
        return {"pass": None, "detail": {"words": words, "note": "the question asked for detail"}}
    return {"pass": words <= WORD_LIMIT, "detail": {"words": words, "limit": WORD_LIMIT}}


def check_markdown(answer: str) -> dict:
    found = []
    if "*" in answer:
        found.append("asterisk")
    if re.search(r"(?m)^\s{0,3}#{1,6}\s", answer):
        found.append("heading")
    other = [name for name, pat in (("backtick", r"`"), ("link", r"\[[^\]]+\]\([^)]+\)"), ("table", r"(?m)^\s*\|.*\|\s*$")) if re.search(pat, answer)]
    return {"pass": not found, "detail": {"found": found, "other_markdown_not_scored": other}}


def check_unverified(items: list[Quantity], answer: str, truth: dict, survey: dict) -> dict:
    """When a quoted figure rests on policy data marked unverified, the answer must say so.

    Two cases: bill and savings figures priced from a slab table whose `verified` flag is false, and the
    surplus rate or surplus credit when the net-metering entry is unverified.
    """
    discom = truth["snap"]["policy"].get(f"discoms.{(survey.get('household') or {}).get('discom_id')}")
    if not discom:
        return {"pass": None, "detail": "no supported distributor, so no tariff or net-metering entry is used"}
    marks = []
    if truth["baseline"].get("rate_basis") == "discom_slabs" and discom["tariff"].get("verified") is False:
        marks += [f".{field}" for field in SLAB_FIELDS] + [".tariff."]
    if discom["net_metering"].get("verified") is False:
        marks += [".surplus_credit", ".net_metering.surplus_rate"]
    if not marks:
        return {"pass": None, "detail": "savings are priced from the household's own bill or from verified entries"}
    traced, _ = _trace(items, MONEY_KINDS + YEAR_KINDS + ("bare",), truth["pools"])
    leaning = [t["text"] for t in traced if all(any(mark in s for mark in marks) for s in t["sources"])]
    if not leaning:
        return {"pass": None, "detail": "the answer quotes no figure that depends on an unverified entry"}
    # The caveat has to be about the price data: "indicative range" for the system cost does not count.
    flag = next((line.strip() for line in _LINE.split(normalise(answer)) if _UNVERIFIED.search(line) and _PRICE_DATA.search(line)), None)
    return {"pass": bool(flag), "detail": {"figures_resting_on_unverified_data": leaning[:6], "caveat_found": flag[:200] if flag else None}}


_ROLES = [
    # (role, words that announce it, finance fields a figure announced that way may be)
    ("lifetime savings", r"lifetime|life time|over (?:its|the system'?s?|25)|25[- ]year|जीवन ?भर|जीवनकाल|लाइफटाइम|25 साल|zindagi bhar|25 saal",
     ("lifetime_savings", "lifetime_savings+net_cost")),
    ("surplus credit", r"surplus|extra units|export|अधिशेष|अतिरिक्त यूनिट|credit|क्रेडिट", ("surplus_credit", "surplus_rate")),
    ("savings", r"\bsav(?:e|es|ed|ing|ings)\b|बचत|bachat",
     ("first_year_savings", "first_year_savings/12", "lifetime_savings", "lifetime_savings+net_cost")),
    ("cost after subsidy", r"after (?:the |a |central )*subsidy|net cost|out of pocket|सब्सिडी के बाद|नेट लागत|नेट कॉस्ट|शुद्ध लागत|subsidy ke baad|net kharch", ("net_cost",)),
    ("cost before subsidy", r"before (?:the |any |central )*subsidy|gross cost|सब्सिडी से पहले|subsidy se pehle",
     ("gross_cost", "gross_cost_range.low", "gross_cost_range.high", "vendor_quote_rupees", "typical cost x system_kw")),
    ("subsidy", r"subsid|सब्सिडी", ("subsidy", "central_subsidy.max_total", "central_subsidy.per_kw_first_2kw", "central_subsidy.per_kw_third_kw", "kW")),
]
_ROLES = [(name, re.compile(normalise(pattern), re.I), fields) for name, pattern, fields in _ROLES]
_PAYBACK = re.compile(normalise(r"pay(?:s|ing)? (?:for itself|back)|payback|recover|get (?:my|your) money back|वसूल|वापस|wasool|vasool|wapas"), re.I)
def check_labels(answer: str, pools: dict) -> dict:
    """A figure announced as one thing must not be the value of another (the system price given as 'lifetime savings').

    Deliberately narrow: only sentences or bullet lines holding exactly one rupee figure (or one year figure next
    to a payback word), where the wording names what the figure is. Figures that cannot be traced at all are left
    to the traceability checks.
    """
    wrong, looked = [], 0
    for line in _LINE.split(normalise(answer)):
        found = quantities(line)
        money = [q for q in found if q.kind in MONEY_KINDS]
        years = [q for q in found if q.kind == "years"]
        if len(money) == 1:
            role = next(((name, fields) for name, pattern, fields in _ROLES if pattern.search(line)), None)
            traced, _ = _trace(money, MONEY_KINDS, pools)
            if role and traced:
                sources = [s for s in traced[0]["sources"] if not s.startswith("question")]
                if sources:
                    looked += 1
                    if not any(s.endswith(role[1]) for s in sources):
                        wrong.append({"figure": money[0].text, "announced_as": role[0], "is_actually": sources[:3], "sentence": line.strip()[:200]})
        if len(years) == 1 and _PAYBACK.search(line) and not _ROLES[0][1].search(line):
            traced, _ = _trace(years, YEAR_KINDS, pools)
            if traced:
                looked += 1
                if not any("payback_years" in s for s in traced[0]["sources"]):
                    wrong.append({"figure": years[0].text, "announced_as": "payback", "is_actually": traced[0]["sources"][:3], "sentence": line.strip()[:200]})
    if not looked:
        return {"pass": None, "detail": "no single-figure sentence names what its figure is"}
    return {"pass": not wrong, "detail": {"mislabelled": wrong, "sentences_checked": looked}}


def check_unknowns(case: dict, answer: str) -> dict:
    """On a question the advisor has no data for, it must not put a number on the unknown thing."""
    spec = case.get("no_figures_about")
    if not spec:
        return {"pass": None, "detail": "not a no-data case"}
    terms = re.compile("|".join(re.escape(normalise(t)) for t in spec["terms"]), re.I)
    hits = []
    for line in _LINE.split(normalise(answer)):
        if terms.search(line):
            hits += [{"figure": q.text, "sentence": line.strip()[:200]} for q in quantities(line) if q.kind in spec["kinds"]]
    return {"pass": not hits, "detail": {"figures_given_for_something_with_no_data": hits}}


_URL_IN_ANSWER = re.compile(r"https?://[^\s)>\]]+", re.I)


def check_links(answer: str, snap: dict) -> dict:
    """Every link in the answer must be one of the links in the policy data, not made up."""
    known = {link.rstrip("/").lower() for link in snap["known_links"]}
    links = sorted({u.rstrip(".,;:/").lower() for u in _URL_IN_ANSWER.findall(answer)})
    if not links:
        return {"pass": None, "detail": "no links in the answer"}
    unknown = [u for u in links if u not in known]
    return {"pass": not unknown, "detail": {"not_in_policy_data": unknown}}


_INTERNAL = re.compile(r"policy_finance_analyst|site_analyst|estimate_finances|lookup_policy|discom_id|\btools?\b|'(?:msedcl|bescom|delhi)'", re.I)


def check_internals(answer: str) -> dict:
    """The household should never hear about the advisor's tools or internal identifiers."""
    found = sorted({m.group(0).lower() for m in _INTERNAL.finditer(answer)})
    return {"pass": not found, "detail": {"mentions": found}}


_MONTHLY = re.compile(normalise(r"month|mahin|मासिक|महीन|माह|प्रति माह"), re.I)
_YEARLY = re.compile(normalise(r"year|annual|saal|salana|sal mein|साल|वार्षिक|वर्ष"), re.I)
_YEARLY_SOURCES = (".bill_before", ".bill_after", ".first_year_savings", "x12")
_MONTHLY_SOURCES = ("/12", "monthly_bill_rupees", ".fixed_charge")


def check_period(answer: str, pools: dict) -> dict:
    """A yearly rupee figure must not be presented as monthly, or the reverse.

    Works one sentence at a time: when the sentence speaks only of months (or only of years), every rupee figure
    in it that can be traced solely to yearly bill or savings figures (or solely to monthly ones) is a mismatch.
    """
    wrong, looked = [], 0
    for sentence in re.split(r"(?<=[.!?।])\s+|\n+", normalise(answer)):
        monthly, yearly = bool(_MONTHLY.search(sentence)), bool(_YEARLY.search(sentence))
        if monthly == yearly:
            continue
        traced, _ = _trace(quantities(sentence), MONEY_KINDS, pools)
        for t in traced:
            sources = [s for s in t["sources"] if not s.startswith("question")]
            is_yearly = bool(sources) and all(s.endswith(_YEARLY_SOURCES) for s in sources)
            is_monthly = bool(sources) and all(s.endswith(_MONTHLY_SOURCES) for s in sources)
            if is_yearly or is_monthly:
                looked += 1
            if (monthly and is_yearly) or (yearly and is_monthly):
                wrong.append({"figure": t["text"], "is_actually": "a yearly figure" if is_yearly else "a monthly figure", "true_source": sources[:3], "sentence": sentence.strip()[:200]})
    if not looked:
        return {"pass": None, "detail": "no bill or savings figure sits in a sentence that names a period"}
    return {"pass": not wrong, "detail": {"mismatched": wrong}}


def check_what_if(case: dict, survey: dict, tool_calls: list[dict]) -> dict:
    """A what-if question needs a fresh calculation with the asked-for size or price."""
    what_if = case.get("what_if")
    if not what_if:
        return {"pass": None, "detail": "not a what-if case"}
    calls = [dict(c.get("input") or {}) for c in tool_calls if c["tool"] == "estimate_finances"]
    recommended = (survey.get("recommended_system") or {}).get("system_kw")

    def same(args: dict) -> bool:
        if "system_kw" not in what_if and args.get("system_kw") is not None and recommended and abs(float(args["system_kw"]) - recommended) < 0.011:
            args = {**args, "system_kw": None}
        return all(
            (args.get(key) is None) == (what_if.get(key) is None) and (what_if.get(key) is None or abs(float(args[key]) - what_if[key]) < 0.011 * max(1, what_if[key] / 100))
            for key in ("system_kw", "quoted_cost")
        )

    return {"pass": any(same(a) for a in calls), "detail": {"expected": what_if, "estimate_finances_calls": calls}}


def check_tool_args(case: dict, survey: dict, tool_calls: list[dict]) -> dict:
    """Arguments given to estimate_finances must come from the question, the survey or the case, not from nowhere."""
    calls = [c.get("input") or {} for c in tool_calls if c["tool"] == "estimate_finances"]
    if not calls:
        return {"pass": None, "detail": "estimate_finances was not called"}
    asked = [q.value for q in quantities(case["question"])] + [float(n) for n in re.findall(r"\d+(?:\.\d+)?", normalise(case["question"]).replace(",", ""))]
    what_if = case.get("what_if") or {}
    household, system = survey.get("household") or {}, survey.get("recommended_system") or {}
    roof = survey.get("roof") or {}
    ok_kw = [system.get("system_kw"), roof.get("max_system_kw"), what_if.get("system_kw"), *asked]
    ok_cost = [household.get("vendor_quote_rupees"), what_if.get("quoted_cost"), *asked]
    odd = []
    for args in calls:
        kw, cost = args.get("system_kw"), args.get("quoted_cost")
        if kw is not None and not any(v is not None and abs(float(kw) - v) < 0.011 for v in ok_kw):
            odd.append({"system_kw": kw})
        if cost is not None and not any(v is not None and abs(float(cost) - v) < 1 for v in ok_cost):
            odd.append({"quoted_cost": cost})
    return {"pass": not odd, "detail": {"unjustified": odd, "calls": calls}}


def run_all(case: dict, survey: dict, raw_answer: str, tool_calls: list[dict], snap: dict) -> dict:
    truth = build_truth(case, survey, tool_calls, snap)
    answer = visible_answer(raw_answer)
    items = quantities(answer)
    pools = truth["pools"]
    return {
        "language_match": check_language(case, answer),
        "rupee_figures_traceable": check_numbers(items, MONEY_KINDS, pools),
        "year_figures_traceable": check_numbers(items, YEAR_KINDS, pools),
        "other_figures_traceable": check_numbers(items, OTHER_KINDS, pools),
        "required_facts_present": check_required(case, answer, items, truth),
        "figures_match_their_label": check_labels(answer, pools),
        "monthly_yearly_not_confused": check_period(answer, pools),
        "no_figures_for_unknowns": check_unknowns(case, answer),
        "links_from_policy_data": check_links(answer, snap),
        "under_150_words": check_length(case, answer),
        "no_markdown": check_markdown(answer),
        "no_leaked_reasoning": check_leak(raw_answer),
        "no_internal_names": check_internals(answer),
        "unverified_data_flagged": check_unverified(items, answer, truth, survey),
        "what_if_recalculated": check_what_if(case, survey, tool_calls),
        "tool_arguments_justified": check_tool_args(case, survey, tool_calls),
    }


DETERMINISTIC = [
    "language_match",
    "rupee_figures_traceable",
    "year_figures_traceable",
    "other_figures_traceable",
    "figures_match_their_label",
    "monthly_yearly_not_confused",
    "no_figures_for_unknowns",
    "links_from_policy_data",
    "required_facts_present",
    "under_150_words",
    "no_markdown",
    "no_leaked_reasoning",
    "no_internal_names",
    "unverified_data_flagged",
    "what_if_recalculated",
    "tool_arguments_justified",
]
