"""Deterministic checks on one advisor answer. No model calls happen here.

Each check returns {"pass": True | False | None, "detail": ...}; None means the
check does not apply to that case and is left out of the pass rate.
"""

from __future__ import annotations

import json
import re

from homesol import agents, finance, policy
from homesol.agents import baseline_finances, largest_system_kw

from .extract import CURRENCY_FITS, Quantity, decimal_commas, language_of, normalise, quantities, stopword_shares, strip_urls

WORD_LIMIT = 150
#: Kinds that are checked by the two headline number checks.
MONEY_KINDS = ("money",)
YEAR_KINDS = ("years", "months")
OTHER_KINDS = ("units", "kw", "watts", "percent", "panels", "floors", "area", "metres", "degrees", "hours", "days", "time", "bare")
POOLS = ("money", "years", "units", "kw", "watts", "percent", "panels", "floors", "area", "metres", "degrees", "hours", "days", "time", "any")
FEET_PER_METRE, SQ_FEET_PER_M2 = 3.281, 10.764
#: Languages that write 4,4 kW and 4.220 kWh.
DECIMAL_COMMA_LANGUAGES = ("de", "es")

#: Finance fields that depend on the electricity price, so on the tariff slabs when rate_basis is discom_slabs.
SLAB_FIELDS = ("bill_before", "bill_after", "first_year_savings", "payback_years", "lifetime_savings", "surplus_credit")

_UNVERIFIED = re.compile(
    normalise(
        r"unverif|unconfirm|(?:not|n't) (?:yet |been |fully |officially |independently )*(?:verified|checked|confirmed)|"
        r"needs? (?:to be |further )?(?:check|verif|confirm)|still needs? check|indicative|provisional|"
        r"(?:yet|still) to be (?:verified|checked|confirmed)|verify|double.check|cross.check|"
        r"worth (?:confirming|checking)|could ?n[o']t (?:be )?(?:locate|find|confirm|verif)\w*|confirm(?:ing)? (?:this|it|that|the rate|with)|"
        r"सत्यापि|सत्यापन|पुष्टि|जा[ँं]च|अपुष्ट|सांकेतिक|"
        r"jaa?nch|pakk[ai] nahi|confirm (?:nahi|nahin|karna|kar|hona)|check (?:nahi|kar)|चेक|कन्फर्म|pushti"
    ),
    re.I,
)

_PRICE_DATA = re.compile(
    normalise(r"rate|tariff|slab|regulator|net.?meter|surplus|extra units?|export|pa(?:y|id|ys)\b|credit|figure|दर|टैरिफ|स्लैब|नियामक|नेट मीटरिंग|अधिशेष|अतिरिक्त यूनिट|यूनिट|unit"),
    re.I,
)
_LINE = re.compile(r"(?<=[.!?।])\s+|\n+")

# ---- what is true for this case -------------------------------------------


def _tolerance(q: Quantity, truth: float) -> float:
    """How far a stated figure may sit from the true one and still be honest rounding.

    Half of the last digit the writer stated ("about 5 years" covers 4.5-5.5,
    "₹1.6 lakh" covers ₹1.55-1.65 lakh). For amounts it is never more than 5%
    of the true figure, so "₹2 lakh" does not cover ₹1.65 lakh, and never less
    than 0.5%, so ₹91,500 covers ₹91,532 whatever the digits look like. Amounts
    under 100 may always be rounded to the nearest whole one.
    """
    half = q.step / 2
    if q.kind == "percent":
        return (1.0 if q.step >= 1 else half) + 1e-9  # "75%" for a measured 0.74, but not "10%" for 12
    if q.kind in ("years", "months", "kw", "watts", "panels", "floors", "metres", "degrees", "hours", "days", "time"):
        return half + 1e-9
    # Small amounts may be rounded to the whole rupee or dollar: "about $4 a month" for $3.75.
    cap = max(0.05 * abs(truth), 0.5 if abs(truth) < 100 else 0.005)
    return min(max(half, 0.005 * abs(truth)), cap) + 1e-9


def matches(q: Quantity, pool: list[tuple[float, str]]) -> list[str]:
    """Labels of the true figures this stated quantity agrees with."""
    readings = [q.value] if q.alt is None else [q.value, q.alt]  # "4:10" may be morning or afternoon
    return [label for truth, label in pool if any(abs(value - truth) <= _tolerance(q, truth) for value in readings)]


def _finance_truths(fin: dict, tag: str, truth: dict) -> None:
    """Every figure in one finance result. Outside India the price, payback and 25-year saving may be None: then there is nothing to match."""
    if not fin or "error" in fin:
        return
    for key in ("gross_cost", "subsidy", "net_cost", "bill_before", "bill_after", "first_year_savings", "surplus_credit", "lifetime_savings"):
        if fin.get(key) is not None:
            truth["money"].append((fin[key], f"{tag}.{key}"))
    for key in ("bill_before", "bill_after", "first_year_savings"):
        truth["money"].append((fin[key] / 12, f"{tag}.{key}/12"))
    if fin.get("gross_cost_range"):
        truth["money"].append((fin["gross_cost_range"][0], f"{tag}.gross_cost_range.low"))
        truth["money"].append((fin["gross_cost_range"][1], f"{tag}.gross_cost_range.high"))
    if fin.get("lifetime_savings") is not None and fin.get("net_cost") is not None:
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
    country_code, _, currency = agents._place(survey)
    india = country_code == "IN"
    # homesol holds subsidy, price and tariff data for India only, so elsewhere none of it may be quoted.
    discom_ids = [d for d in [household.get("discom_id"), *case.get("extra_discoms", [])] if india and d and policy.get_discom(d)]
    sections = {"central_subsidy": data["central_subsidy"], "system_cost_per_kw": data["system_cost_per_kw"]} if india else {}
    sections.update({f"discoms.{d}": data["discoms"][d] for d in discom_ids})
    fixed = {}
    for d in discom_ids:
        tariff = data["discoms"][d]["tariff"]
        charge = tariff["fixed_charge"]
        fixed[d] = finance.fixed_charge(tariff, finance.DEFAULT_LOAD_KW) if isinstance(charge, dict) else charge
    return {
        "baseline": baseline_finances(survey),
        "what_if": baseline_finances(survey, what_if.get("system_kw"), what_if.get("quoted_cost")) if what_if else None,
        "currency": currency,
        "policy": sections,
        "subsidy_by_kw": {str(kw): policy.central_subsidy(kw) for kw in (1, 2, 3)} if india else {},
        "fixed_charge_per_month": fixed,
        "life_years": finance.SYSTEM_LIFE_YEARS,
        "tariff_escalation_percent": finance.TARIFF_ESCALATION * 100,
        "panel_degradation_percent": finance.PANEL_DEGRADATION * 100,
        "known_links": sorted({str(leaf) for path, leaf in _walk(data, "policy") if path.endswith((".source", ".apply_at"))}),
    }


def _clock(window: str) -> tuple[int, int] | None:
    """Start and end of "09:40 to 16:10" in minutes after midnight."""
    found = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*(?:to|-|–)\s*(\d{1,2}):(\d{2})\s*", window or "")
    if not found:
        return None
    h1, m1, h2, m2 = map(int, found.groups())
    return h1 * 60 + m1, h2 * 60 + m2


def _site_truths(survey: dict, truth: dict) -> None:
    """The figures of the site survey: the surface, the sun on it, what shades it and the panel layout."""
    surface, sun, panels = survey.get("surface") or {}, survey.get("sun") or {}, survey.get("panels") or {}

    def add(bucket: str, value, label: str) -> None:
        if value is not None and not isinstance(value, bool):
            truth[bucket].append((float(value), label))

    def length(value, label: str) -> None:
        add("metres", value, label)
        if value is not None:
            add("metres", value * FEET_PER_METRE, f"{label} (in feet)")

    add("area", surface.get("area_m2"), "survey.surface.area_m2")
    if surface.get("area_m2") is not None:
        add("area", surface["area_m2"] * SQ_FEET_PER_M2, "survey.surface.area_m2 (in square feet)")
    length(surface.get("height_m"), "survey.surface.height_m")
    add("floors", surface.get("floors"), "survey.surface.floors")
    add("degrees", surface.get("tilt_deg"), "survey.surface.tilt_deg")
    if sun.get("share_of_full_sun") is not None:
        share = sun["share_of_full_sun"] * 100
        truth["percent"] += [(share, "survey.sun.share_of_full_sun %"), (100 - share, "survey share of sun lost to shade %")]
    for season, window in (sun.get("full_sun_hours") or {}).items():
        clock = _clock(window)
        if clock:
            truth["time"] += [(clock[0], f"survey.sun.full_sun_hours.{season} start"), (clock[1], f"survey.sun.full_sun_hours.{season} end")]
            add("hours", (clock[1] - clock[0]) / 60, f"survey.sun.full_sun_hours.{season} length")
    for i, o in enumerate(survey.get("obstructions") or []):
        length(o.get("height_above_m"), f"survey.obstructions[{i}].height_above_m")
        length(o.get("distance_m"), f"survey.obstructions[{i}].distance_m")
        if o.get("share_of_shade") is not None:
            add("percent", o["share_of_shade"] * 100, f"survey.obstructions[{i}].share_of_shade %")
    shares = [o.get("share_of_shade") for o in survey.get("obstructions") or []]
    if shares and all(value is not None for value in shares):  # the fact sheet states what the listed causes leave over
        add("percent", 100 - sum(round(value * 100) for value in shares), "share of the shade from causes the survey does not list")
    add("panels", panels.get("fit"), "survey.panels.fit")
    add("panels", panels.get("recommended"), "survey.panels.recommended")
    add("degrees", panels.get("tilt_deg"), "survey.panels.tilt_deg")
    add("watts", panels.get("panel_watts"), "survey.panels.panel_watts")
    if panels.get("panel_watts"):
        add("kw", panels["panel_watts"] / 1000, "survey.panels.panel_watts in kW")
    add("kw", largest_system_kw(survey), "largest system that fits (panels.fit x panel_watts)")


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
            returned = call.get("result")  # recorded with the call; runs from before October 2026 kept the tool's JSON instead
            if returned is None:
                try:
                    returned = json.loads(call.get("output") or "")
                except ValueError:
                    continue
            if isinstance(returned, dict) and "bill_before" in returned:
                _finance_truths(returned, f"toolcall{_args(call.get('input') or {})}", truth)

    sections = snap["policy"]
    cost = sections.get("system_cost_per_kw")
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
    truth["days"].append((365, "days in a year"))
    truth["percent"] += [(snap["tariff_escalation_percent"], "finance.TARIFF_ESCALATION"), (snap["panel_degradation_percent"], "finance.PANEL_DEGRADATION")]

    _site_truths(survey, truth)
    bill, quote, units = household.get("monthly_bill"), household.get("vendor_quote"), household.get("monthly_units")
    if bill:
        truth["money"] += [(bill, "survey.household.monthly_bill"), (bill * 12, "survey.monthly_bill x12")]
        if units:
            truth["money"].append((bill / units, "survey bill / units"))
    if units:
        truth["units"] += [(units, "survey.household.monthly_units"), (units * 12, "survey usage per year"), (units / 30, "survey usage per day, average")]
    if system.get("system_kw"):
        kw = system["system_kw"]
        truth["kw"].append((kw, "survey.recommended_system.system_kw"))
        if system.get("panels") is not None:
            truth["panels"].append((system["panels"], "survey.recommended_system.panels"))
        if cost:
            truth["money"].append((kw * cost["typical"], "policy typical cost x system_kw"))
        if quote:
            truth["money"] += [(quote, "survey.household.vendor_quote"), (quote / kw, "quote per kW")]
            if cost:  # only India has a usual price range to hold a quote against
                truth["money"] += [
                    (quote - kw * cost["high"], "quote minus top of usual range"),
                    (quote - kw * cost["typical"], "quote minus typical cost"),
                ]
                truth["percent"].append(((quote / (kw * cost["high"]) - 1) * 100, "quote % above top of usual range"))
                truth["percent"].append(((quote / (kw * cost["typical"]) - 1) * 100, "quote % above typical cost"))
        gen = system.get("monthly_generation_units") or []
        if gen:
            truth["units"] += [(value, f"survey.recommended_system.monthly_generation_units[{i}]") for i, value in enumerate(gen)]
            truth["units"] += [(sum(gen), "survey generation per year"), (sum(gen) / 12, "survey generation per month, average"), (sum(gen) / 365, "survey generation per day, average")]
        if system.get("share_of_usage_covered") is not None:
            share = system["share_of_usage_covered"] * 100
            truth["percent"] += [(share, "survey share_of_usage_covered %"), (100 - share, "survey share of usage not covered %")]

    # What the household typed, in this message or an earlier one, is fair to repeat.
    for text in [*case.get("earlier", []), case["question"]]:
        _text_truths(text, "question", truth, any_unit=True)
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
    if case["lang"] not in ("en", "hi", "hinglish"):  # any other language: judged by its everyday words
        shares = stopword_shares(answer)
        mine = shares.get(case["lang"], 0.0)
        return {"pass": mine >= 0.15 and mine > 1.5 * shares["en"], "detail": {"expected": case["lang"], "share_of_everyday_words": shares}}
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
    clock = re.fullmatch(r"(\d{1,2}):(\d{2})", name)
    if clock:  # a clock time, as minutes after midnight
        return int(clock.group(1)) * 60.0 + int(clock.group(2)), name
    source = truth["baseline"]
    label = name
    if name.startswith("whatif."):
        source, name = truth["what_if"], name[len("whatif.") :]
    divide = 1
    if name.endswith("/12"):
        name, divide = name[:-3], 12
    if not source or "error" in source:
        return None, label
    if name.startswith("gross_cost_range."):
        value = source["gross_cost_range"][int(name.rsplit(".", 1)[1])] if source.get("gross_cost_range") else None
    else:
        value = source.get(name)
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
        kinds = {"money": MONEY_KINDS + ("bare",), "years": YEAR_KINDS, "other": OTHER_KINDS, "time": ("time",)}[kind]
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

    Two cases: bill and savings figures priced from a slab table whose `verified` flag is false, and any
    figure taken from the net-metering entry (the rate paid for extra units, what they are worth) when that
    entry is unverified.
    """
    discom = truth["snap"]["policy"].get(f"discoms.{(survey.get('household') or {}).get('discom_id')}")
    if not discom:
        return {"pass": None, "detail": "no supported distributor, so no tariff or net-metering entry is used"}
    marks = []
    if truth["baseline"].get("rate_basis") == "discom_slabs" and discom["tariff"].get("verified") is False:
        marks += [f".{field}" for field in SLAB_FIELDS] + [".tariff."]
    if discom["net_metering"].get("verified") is False:
        marks += [".surplus_credit", ".net_metering."]
    if not marks:
        return {"pass": None, "detail": "savings are priced from the household's own bill or from verified entries"}
    traced, _ = _trace(items, MONEY_KINDS + YEAR_KINDS + ("bare",), truth["pools"])
    # The finance notes repeat the unverified entry's own words, so they are no second, independent source.
    independent = lambda t: [s for s in t["sources"] if not s.endswith(".notes") and not s.startswith("question")]  # noqa: E731
    leaning = [t["text"] for t in traced if independent(t) and all(any(mark in s for mark in marks) for s in independent(t))]
    if not leaning:
        return {"pass": None, "detail": "the answer quotes no figure that depends on an unverified entry"}
    # The caveat has to be about the price data: "indicative range" for the system cost does not count.
    flag = next((line.strip() for line in _LINE.split(normalise(answer)) if _UNVERIFIED.search(line) and _PRICE_DATA.search(line)), None)
    return {"pass": bool(flag), "detail": {"figures_resting_on_unverified_data": leaning[:6], "caveat_found": flag[:200] if flag else None}}


_ROLES = [
    # (role, words that announce it, finance fields a figure announced that way may be)
    ("lifetime savings", r"lifetime|life time|over (?:its|the system'?s?|25)|25[- ]year|जीवन ?भर|जीवनकाल|लाइफटाइम|25 साल|zindagi bhar|25 saal",
     ("lifetime_savings", "lifetime_savings+net_cost")),
    ("surplus credit", r"surplus|extra units|export|अधिशेष|अतिरिक्त यूनिट", ("surplus_credit", "surplus_rate")),
    ("savings", r"\bsav(?:e|es|ed|ing|ings)\b|बचत|bachat",
     ("first_year_savings", "first_year_savings/12", "lifetime_savings", "lifetime_savings+net_cost")),
    ("cost after subsidy", r"after (?:the |a |any |central |government |govt\.? )*subsid(?:y|ies)|net cost|(?:सब्सिडी|subsid\w*)(?: \([^)]*\))? (?:के|ke) (?:बाद|baad)|सब्सिडी (?:घटाकर|काटकर|काटने)|subsidy (?:ghata|kaat)\w*|नेट लागत|नेट कॉस्ट|शुद्ध लागत|net kharch|"
     r"(?:सब्सिडी|subsid\w*).{0,60}?(?:चुका|देंगे|देना होगा|you(?:'d| would| will)? pay|dena hoga|denge|pay kar\w*)", ("net_cost",)),
    ("cost before subsidy", r"before (?:the |a |any |central |government |govt\.? )*subsid(?:y|ies)|gross cost|(?:सब्सिडी|subsid\w*) (?:से|se) (?:पहले|pehle)",
     ("gross_cost", "gross_cost_range.low", "gross_cost_range.high", "household.vendor_quote", "typical cost x system_kw")),
    ("subsidy", r"subsid|सब्सिडी", ("subsidy", "central_subsidy.max_total", "central_subsidy.per_kw_first_2kw", "central_subsidy.per_kw_third_kw", "kW")),
]
_ROLES = [(name, re.compile(normalise(pattern), re.I), fields) for name, pattern, fields in _ROLES]
_PAYBACK = re.compile(normalise(r"pay(?:s|ing)? (?:for itself|back)|payback|recover|get (?:my|your) money back|वसूल|वापस|wasool|vasool|wapas"), re.I)
#: "No subsidy is counted, so you pay the full $21,500": the figure is not being called a subsidy.
_NO_SUBSIDY = re.compile(normalise(r"\b(?:no|not|without|n't|nahi|nahin|bina|zero)\b|नहीं|बिना"), re.I)
_TAX_CREDIT = re.compile(r"tax[- ]credits?", re.I)
_PER_UNIT = re.compile(normalise(r"(?:per|a|each|every|/)\s*(?:unit|kwh)|प्रति यूनिट|हर यूनिट|har unit|prati unit"), re.I)


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
            wording = _TAX_CREDIT.sub(" ", line)  # a tax credit is not the credit paid for surplus units
            role = next(((name, fields) for name, pattern, fields in _ROLES if pattern.search(wording)), None)
            if role and role[0] == "subsidy" and _NO_SUBSIDY.search(line):
                role = None
            if role and role[0] in ("savings", "lifetime savings") and _PER_UNIT.search(line) and money[0].value < 100:
                role = None  # a rate per unit ("priced at ₹7.60 a unit for your savings") is not being called an amount saved
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


#: Sources that make a figure the household's own: typed by them, or calculated for them.
_OWN_FIGURES = ("question", "baseline.", "whatif.", "toolcall", "survey.household")


def check_unknowns(case: dict, answer: str, pools: dict) -> dict:
    """On a question the advisor has no data for, it must not put a number of its own on the unknown thing.

    A figure calculated for this household, or one the household typed, may share a sentence with the unknown
    ("I can't say whether your ₹2 lakh is better in a fixed deposit"), so those do not count.
    """
    spec = case.get("no_figures_about")
    if not spec:
        return {"pass": None, "detail": "not a no-data case"}
    terms = re.compile("|".join(re.escape(normalise(t)) for t in spec["terms"]), re.I)
    hits = []
    for line in _LINE.split(normalise(answer)):
        if terms.search(line):
            traced, untraced = _trace(quantities(line), tuple(spec["kinds"]), pools)
            # A figure that merely coincides with some tariff or policy number is still a figure for the unknown.
            own = lambda t: any(s.startswith(_OWN_FIGURES) and not s.endswith(".notes") for s in t["sources"])  # noqa: E731
            hits += [{"figure": u["text"], "sentence": line.strip()[:200]} for u in [*untraced, *(t for t in traced if not own(t))]]
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


_INTERNAL = re.compile(
    r"policy_finance_analyst|site_analyst|estimate_finances|lookup_policy|discom_id|'(?:msedcl|bescom|delhi|gujarat)'|"
    r"\b(?:my|our) tools?\b|\btools? (?:calls?|results?|outputs?|returned|says?|said|shows?)\b|\b(?:called|calling|used?|using) (?:a|the|my) tool\b|"
    r"\b(?:site|finance|financial|policy)(?: and finance)? analyst\b|\b(?:my|our|the) (?:specialist|analyst|sub-?agent)s?\b|fact sheet|"
    r"share_of_shade|share_of_full_sun|monthly_units|system_kw|limited_by",
    re.I,
)


def check_internals(answer: str) -> dict:
    """The household should never hear about the advisor's tools or internal identifiers."""
    found = sorted({m.group(0).lower() for m in _INTERNAL.finditer(answer)})
    return {"pass": not found, "detail": {"mentions": found}}


_MONTHLY = re.compile(normalise(r"month|mahin|मासिक|महीन|माह|प्रति माह"), re.I)
_YEARLY = re.compile(normalise(r"year|annual|saal|salana|sal mein|साल|वार्षिक|वर्ष"), re.I)
_YEARLY_SOURCES = (".bill_before", ".bill_after", ".first_year_savings", "x12")
_MONTHLY_SOURCES = ("/12", "household.monthly_bill", ".fixed_charge")


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
    said = " ".join([*case.get("earlier", []), case["question"]])  # everything the household typed in this conversation
    asked = [q.value for q in quantities(said)] + [float(n) for n in re.findall(r"\d+(?:\.\d+)?", normalise(said).replace(",", ""))]
    what_if = case.get("what_if") or {}
    household, system = survey.get("household") or {}, survey.get("recommended_system") or {}
    ok_kw = [system.get("system_kw"), largest_system_kw(survey), what_if.get("system_kw"), *asked]
    ok_cost = [household.get("vendor_quote"), what_if.get("quoted_cost"), *asked]
    odd = []
    for args in calls:
        kw, cost = args.get("system_kw"), args.get("quoted_cost")
        if kw is not None and not any(v is not None and abs(float(kw) - v) < 0.011 for v in ok_kw):
            odd.append({"system_kw": kw})
        if cost is not None and not any(v is not None and abs(float(cost) - v) < 1 for v in ok_cost):
            odd.append({"quoted_cost": cost})
    return {"pass": not odd, "detail": {"unjustified": odd, "calls": calls}}


def check_currency(items: list[Quantity], currency: str) -> dict:
    """Money is written in the survey's currency: no rupees or lakh for a home in Texas, no dollars for one in Pune."""
    marked = [q for q in items if q.kind == "money" and q.currency]
    if not marked or not currency:
        return {"pass": None, "detail": "no amount in the answer names a currency"}
    wrong = [{"figure": q.text, "written_as": q.currency, "context": q.context} for q in marked if currency not in CURRENCY_FITS.get(q.currency, {q.currency})]
    return {"pass": not wrong, "detail": {"survey_currency": currency, "in_another_currency": wrong}}


def check_forbidden(case: dict, answer: str) -> dict:
    """Things homesol has no data on and the advisor would have to recall from memory: a named scheme, a tax credit rate."""
    banned = case.get("must_not_include") or []
    if not banned:
        return {"pass": None, "detail": "nothing is ruled out by name for this case"}
    text = normalise(answer).lower()
    found = [term for term in banned if re.search(r"(?<![a-z0-9])" + re.escape(normalise(term).lower()) + r"(?![a-z0-9])", text)]
    return {"pass": not found, "detail": {"found": found}}


def run_all(case: dict, survey: dict, raw_answer: str, tool_calls: list[dict], snap: dict) -> dict:
    truth = build_truth(case, survey, tool_calls, snap)
    answer = visible_answer(raw_answer)
    if case["lang"] in DECIMAL_COMMA_LANGUAGES:
        answer = decimal_commas(answer)
    items = quantities(answer)
    pools = truth["pools"]
    return {
        "language_match": check_language(case, answer),
        "currency_matches_survey": check_currency(items, snap.get("currency") or ""),
        "money_figures_traceable": check_numbers(items, MONEY_KINDS, pools),
        "year_figures_traceable": check_numbers(items, YEAR_KINDS, pools),
        "other_figures_traceable": check_numbers(items, OTHER_KINDS, pools),
        "required_facts_present": check_required(case, answer, items, truth),
        "figures_match_their_label": check_labels(answer, pools),
        "monthly_yearly_not_confused": check_period(answer, pools),
        "no_figures_for_unknowns": check_unknowns(case, answer, pools),
        "nothing_recalled_by_name": check_forbidden(case, answer),
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
    "currency_matches_survey",
    "money_figures_traceable",
    "year_figures_traceable",
    "other_figures_traceable",
    "figures_match_their_label",
    "monthly_yearly_not_confused",
    "no_figures_for_unknowns",
    "nothing_recalled_by_name",
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
