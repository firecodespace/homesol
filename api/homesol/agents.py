"""Strands agents. They read numbers from tools and never work them out themselves.

Three agents answer a household's questions: an advisor that talks to the household, and two
specialists it consults (a site analyst and a policy-and-finance analyst). `answer` is the one
call the web API needs.
"""

import json
import os
import re
from urllib.parse import urlparse

from strands import Agent, ModelRetryStrategy, tool
from strands.models import BedrockModel

from . import finance, policy

#: The advisor writes what the household reads. The specialists write short notes for the advisor.
ADVISOR_MODEL_ID = os.environ.get("BEDROCK_AGENT_MODEL_ID") or "us.anthropic.claude-opus-4-6-v1"
SPECIALIST_MODEL_ID = os.environ.get("BEDROCK_SPECIALIST_MODEL_ID") or "us.anthropic.claude-sonnet-4-6"
#: How hard each model works on a reply: low, medium, high or max. Only Claude 4.6 and later take it.
ADVISOR_EFFORT = os.environ.get("BEDROCK_AGENT_EFFORT") or "low"
SPECIALIST_EFFORT = os.environ.get("BEDROCK_SPECIALIST_EFFORT") or "low"
#: Kept for callers that read the advisor's model under its old name.
MODEL_ID = ADVISOR_MODEL_ID

#: Models that accept adaptive thinking and an effort level. Haiku 4.5 and Amazon Nova reject both.
_TAKES_EFFORT = re.compile(r"claude-(?:opus|sonnet)-(?:4-[6-9]|[5-9])|claude-fable")


def _model(model_id: str, effort: str, max_tokens: int) -> BedrockModel:
    """
    A Bedrock model set up for short, careful replies.

    On Claude 4.6 the model decides for itself when a question needs thinking through
    ("adaptive"), and `effort` sets how much. No temperature is sent: Bedrock rejects any
    value but the default while thinking is on.
    """
    fields = {"thinking": {"type": "adaptive"}, "output_config": {"effort": effort}} if _TAKES_EFFORT.search(model_id) else None
    return BedrockModel(
        model_id=model_id,
        region_name=os.environ.get("AWS_REGION", "us-east-1"),
        max_tokens=max_tokens,
        additional_request_fields=fields,
    )


def _retries() -> ModelRetryStrategy:
    """
    How long to keep trying when Bedrock throttles a call: three attempts, a few seconds apart.

    Strands' own default waits up to two minutes, far longer than a household will sit in a
    chat window or a web request will stay open. One is made per agent, as it counts attempts.
    """
    return ModelRetryStrategy(max_attempts=3, initial_delay=2, max_delay=4)


# ---- the household's figures ---------------------------------------------------------------


def _place(survey: dict) -> tuple[str, str | None, str]:
    """
    Country code, country name and currency of the property; "" where the survey does not say.

    A survey with no country counts as India only when something else in it says so (rupees,
    or one of the Indian distributors). Otherwise the country stays unknown and no Indian
    subsidy or price is applied to it.
    """
    location = survey.get("location") or {}
    code = (location.get("country_code") or "").upper()
    currency = (location.get("currency") or "").upper()
    discom_id = (survey.get("household") or {}).get("discom_id")
    if not code and (currency == "INR" or policy.get_discom(discom_id or "")):
        code = "IN"
    if code == "IN":
        currency = "INR"
    return code, location.get("country") or ("India" if code == "IN" else None), currency


def largest_system_kw(survey: dict) -> float | None:
    """The biggest system that fits where the sun is good, from the panel count and panel size."""
    panels = survey.get("panels") or {}
    if panels.get("fit") is None or not panels.get("panel_watts"):
        return None
    return round(panels["fit"] * panels["panel_watts"] / 1000, 2)


def baseline_finances(survey: dict, system_kw: float | None = None, quoted_cost: float | None = None) -> dict:
    """Finances for the surveyed household, at the recommended size unless another is given.

    Every input comes from the survey, so a model cannot pass a wrong figure. Amounts are in
    the survey's currency. Generation scales in proportion to system size. Outside India the
    price, payback and 25-year saving are None unless there is a vendor's quote.
    """
    household = survey.get("household") or {}
    system = survey.get("recommended_system") or {}
    if not system.get("system_kw") or not household.get("monthly_units") or not system.get("monthly_generation_units"):
        return {"error": "There is nothing to calculate yet: the household must enter their monthly electricity use, which sets the recommended system."}
    country_code, _, currency = _place(survey)
    size = system_kw or system["system_kw"]
    scale = size / system["system_kw"]
    discom_id = household.get("discom_id") if country_code == "IN" else None
    try:
        result = finance.estimate(
            system_kw=size,
            monthly_generation=[units * scale for units in system["monthly_generation_units"]],
            monthly_usage=household["monthly_units"],
            discom_id=discom_id if policy.get_discom(discom_id or "") else None,
            monthly_bill=household.get("monthly_bill"),
            # A vendor's quote prices the recommended size only, not a what-if size.
            quoted_cost=quoted_cost or (household.get("vendor_quote") if scale == 1 else None),
            country_code=country_code or "??",
            currency=currency or "(currency not recorded)",
        ).to_dict()
    except ValueError as err:
        return {"error": str(err)}
    return {"system_kw": round(size, 2), **result}


def _indian(number: int) -> str:
    """165000 as 1,65,000."""
    digits = str(abs(number))
    head, tail = digits[:-3], digits[-3:]
    head = re.sub(r"(?<=\d)(?=(?:\d\d)+$)", ",", head)
    return ("-" if number < 0 else "") + (f"{head},{tail}" if head else tail)


def _money(amount: float, currency: str) -> str:
    """An amount in the survey's currency. Rupees also get their lakh or crore form, ready to quote."""
    if currency == "INR":
        whole = round(amount)
        text = f"₹{_indian(whole)}"
        if abs(whole) >= 10_000_000:
            text += f" (₹{whole / 10_000_000:.2f} crore)"
        elif abs(whole) >= 100_000:
            text += f" (₹{whole / 100_000:.2f} lakh)"
        return text
    number = f"{amount:,.2f}" if abs(amount) < 1 and amount != round(amount) else f"{round(amount):,}"
    return f"{currency} {number}" if currency else f"{number} (currency not recorded)"


def _spot(surface: dict) -> str:
    kind = surface.get("kind") or ""
    return "roof" if "roof" in kind else "land" if "ground" in kind else "surface"


def _surface_words(surface: dict) -> str:
    """The kind of surface in plain words: a roof, a sloped roof facing south-west, open land, a hillside."""
    faces, tilt = surface.get("faces"), surface.get("tilt_deg")
    slope = (f" facing {faces}" if faces else "") + (f", tilted about {tilt:g} degrees" if tilt is not None else "")
    return {
        "roof": "a flat roof",
        "sloped_roof": f"a sloped roof{slope}",
        "ground": "open, level land on the ground (not a roof)",
        "sloped_ground": f"sloping land on the ground, a hillside{slope} (not a roof)",
    }.get(surface.get("kind"), "a surface whose kind (roof or land) was not recorded")


_SEASONS = (("winter", "in midwinter"), ("equinox", "in spring and autumn"), ("summer", "in midsummer"))


def _span(window: str) -> str:
    """How long "09:40 to 16:10" lasts, so that no model has to subtract clock times."""
    found = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*(?:to|-|–)\s*(\d{1,2}):(\d{2})\s*", window)
    if not found:
        return ""
    start_h, start_m, end_h, end_m = map(int, found.groups())
    minutes = end_h * 60 + end_m - start_h * 60 - start_m
    return f" (about {round(minutes / 60, 1):g} hours)" if minutes > 0 else ""


def _obstruction_line(o: dict, spot: str) -> str:
    height, direction, share = o.get("height_above_m"), o.get("direction"), o.get("share_of_shade")
    if o.get("on_surface"):
        where = f"standing on the {spot} itself" + (f", on its {direction} side" if direction else "")
        tall = f"{height:g} m high" if height is not None else "height not recorded"
    else:
        distance = o.get("distance_m")
        where = (f"{distance:g} m away" if distance is not None else "beside it, distance not recorded") + (
            f" to the {direction}" if direction else ""
        )
        tall = f"rising {height:g} m above the {spot}" if height is not None else "height not recorded"
    name = o.get("name") or "Something the survey does not name"
    if share is None:
        return f"- {name}, {where}, {tall}. How much of the shade it causes was not worked out."
    return f"- About {round(share * 100)}% of the shade comes from: {name}, {where}, {tall}."


def _site_lines(survey: dict) -> list[str]:
    surface = survey.get("surface") or {}
    sun = survey.get("sun") or {}
    panels = survey.get("panels") or {}
    spot = _spot(surface)

    lines = ["WHERE THE PANELS WOULD GO"]
    if not surface:
        lines.append("- Nothing about the roof or land was recorded.")
    else:
        lines.append(f"- The panels would go on {_surface_words(surface)}.")
        if surface.get("area_m2") is not None:
            lines.append(f"- Its area is {surface['area_m2']:g} m2.")
        if spot == "roof" and surface.get("height_m"):
            floors = surface.get("floors")
            storeys = f" ({floors} floor{'' if floors == 1 else 's'})" if floors else ""
            lines.append(f"- It is about {surface['height_m']:g} m above the ground{storeys}.")
        date = surface.get("imagery_date")
        if surface.get("measured") is True:
            lines.append(
                "- The site figures here were MEASURED from Google's 3D aerial survey"
                + (f", flown on {date}. Anything built, grown or removed since then is not in them." if date else ".")
            )
        elif surface.get("measured") is False:
            lines.append(
                "- The site figures here are ESTIMATES worked out from what the household marked by hand on the map. "
                "Nothing was measured, so they are rougher than a measured survey."
            )
        else:
            lines.append("- Whether the site figures here were measured or estimated was not recorded.")

    lines.append("SUN AND SHADE")
    share = sun.get("share_of_full_sun")
    if share is None:
        lines.append(f"- How much sun reaches the {spot} was not worked out.")
    else:
        got = round(share * 100)
        lines.append(
            f"- Over a year the {spot} gets {got}% of the sunlight a completely unshaded spot here would get. "
            f"The other {100 - got}% is lost to shade."
        )
    hours = sun.get("full_sun_hours") or {}
    windows = [f"from {hours[key]}{_span(hours[key])} {label}" for key, label in _SEASONS if hours.get(key)]
    lines.append(
        f"- Nearly all of the {spot} is in sun {', '.join(windows)}. These are local clock times."
        if windows
        else f"- The hours of the day when the {spot} is in full sun were not worked out."
    )

    obstructions = survey.get("obstructions") or []
    shares = [o.get("share_of_shade") for o in obstructions]
    ranked = bool(obstructions) and all(value is not None for value in shares)
    lines.append(
        "WHAT CAUSES THAT SHADE"
        + (", biggest cause first. Each percentage here is a share of the shade, not a share of the sunlight" if ranked else "")
    )
    if obstructions:
        lines += [_obstruction_line(o, spot) for o in obstructions]
        rest = 100 - sum(round(value * 100) for value in shares) if ranked else 0
        if rest >= 1:
            lines.append(f"- The remaining {rest}% of the shade comes from smaller things and the shape of the {spot} itself, which the survey does not list.")
    elif surface.get("measured") is True:
        lines.append(f"- Nothing that shades the {spot} was found in the survey.")
    else:
        lines.append(f"- Nothing was marked as shading the {spot}. Without a measured survey, shade from neighbours or trees could be missing.")

    lines.append("PANEL LAYOUT")
    watts, fit = panels.get("panel_watts"), panels.get("fit")
    if watts:
        lines.append(f"- Each panel is rated {watts:g} W.")
    if fit is None:
        lines.append(f"- How many panels fit on the {spot} was not worked out.")
    else:
        largest = largest_system_kw(survey)
        lines.append(
            f"- Panels that fit on the {spot} in positions with good sun: {fit}"
            + (f", which is {largest:g} kW at the very most." if largest is not None else ".")
        )
    tilt, facing, mounting = panels.get("tilt_deg"), panels.get("facing"), panels.get("mounting")
    angle = (f"tilted {tilt:g} degrees" if tilt is not None else "") + (" and " if tilt is not None and facing else "") + (f"facing {facing}" if facing else "")
    if mounting == "flush on the slope":
        lines.append(f"- The panels lie flat against the slope of the {spot}" + (f", so they are {angle}, the same as the {spot}." if angle else "."))
    elif mounting == "tilted rows":
        lines.append(
            "- The panels stand in rows on tilted frames"
            + (f", {angle}" if angle else "")
            + ", with room left between the rows so that one row does not shade the next in winter."
        )
    elif angle:
        lines.append(f"- The panels are {angle}.")
    if fit is not None:
        lines.append(
            f"- How homesol placed them: a panel goes only where it fits entirely on the {spot}, clear of its edges and of anything "
            "standing on it. Positions are filled sunniest first, so the recommended panels sit in the least shaded part."
        )
    return lines


def _money_lines(survey: dict, money: dict, heading: str = "MONEY, for the recommended system", background: bool = True) -> list[str]:
    """
    One finance result as labelled sentences. `background` adds what does not change with the
    system's size or price (who gets the subsidy and where, how extra units are treated); a
    recalculation leaves it out, because the fact sheet has already said it.
    """
    country_code, country, currency = _place(survey)
    india = country_code == "IN"
    where = country or "this country"

    def amount(value: float) -> str:
        return _money(value, currency)

    lines = [f"{heading} (every amount is in {'Indian rupees' if india else currency or 'a currency that was not recorded'})"]
    priced = money["gross_cost"] is not None
    if not priced:
        lines += [
            f"- Price of the system: NOT KNOWN. homesol has price data for India only, not for {where}, and the household has not entered a vendor's quote.",
            "- Because the price is not known, the years it takes to pay for itself and the 25-year saving CANNOT be worked out. "
            "They can be once the household enters a vendor's quote.",
        ]
    elif india:
        low, high = money["gross_cost_range"]
        lines += [
            f"- Price before subsidy: {amount(money['gross_cost'])}"
            + (" (the vendor's quote)." if money["cost_is_quote"] else " (a typical market price, not a quote)."),
            f"- Usual market price range for this size: {amount(low)} to {amount(high)}.",
        ]
        if money["cost_is_quote"] and not low <= money["gross_cost"] <= high:
            gap = (money["gross_cost"] - high) / high if money["gross_cost"] > high else (low - money["gross_cost"]) / low
            side = "ABOVE the top" if money["gross_cost"] > high else "BELOW the bottom"
            lines.append(f"- The vendor's quote is {round(gap * 100)}% {side} of the usual range.")
        elif money["cost_is_quote"]:
            lines.append("- The vendor's quote is inside the usual range.")
    else:
        lines.append(
            f"- Price of the system: {amount(money['gross_cost'])} (the vendor's quote). homesol has no price data for {where}, "
            "so it cannot say whether this quote is high or low."
        )

    if india:
        rules = policy.load().get("central_subsidy") or {}
        scheme = rules.get("scheme") or "the central government scheme"
        lines.append(
            f"- Government subsidy ({scheme}): {amount(money['subsidy'])}."
            + (
                f" Who gets it: {rules['applies_to']} (Net metering means the meter also counts the units the home sends "
                "to the grid, and they are set against the units it uses.)"
                if background and rules.get("applies_to")
                else ""
            )
            + (f" It is applied for at {rules['apply_at']}" if background and rules.get("apply_at") else "")
        )
        if background:
            lines.append("- State government subsidies on top of this: homesol has NO data on any, so none is counted.")
        if _spot(survey.get("surface") or {}) == "land":
            lines.append(
                "- This subsidy is for ROOFTOP systems and these panels would stand on the ground, so whether the household "
                "can get it is NOT CONFIRMED. The figures below assume they do; without it they pay the full price before subsidy."
            )
        if priced:
            lines.append(f"- What the household pays after subsidy: {amount(money['net_cost'])}.")
    else:
        lines.append(
            f"- Subsidies, rebates and tax credits: homesol has NO data for {where}, so none is counted. "
            "Whether any exist, and what they are worth, is not known here."
        )

    lines += [
        f"- Electricity bill today: {amount(money['bill_before'])} PER YEAR (about {amount(money['bill_before'] / 12)} a month).",
        f"- Electricity bill with solar: {amount(money['bill_after'])} PER YEAR (about {amount(money['bill_after'] / 12)} a month).",
        f"- Saved in the first year: {amount(money['first_year_savings'])}.",
    ]
    if priced:
        lines.append(
            "- Years until the system has paid for itself: "
            + (f"{money['payback_years']}." if money["payback_years"] is not None else "more than 25, the life assumed for the system.")
        )
        lifetime = money["lifetime_savings"]
        if lifetime is not None and lifetime >= 0:
            lines.append(f"- Saved over 25 years, after paying for the system: {amount(lifetime)}.")
        elif lifetime is not None:
            lines.append(f"- Over 25 years the savings fall short of the price by {amount(-lifetime)}: the system does not pay for itself.")
    if money["surplus_units"]:
        lines.append(
            f"- Extra units sent to the grid in a year: {money['surplus_units']}, "
            + (
                f"worth {amount(money['surplus_credit'])} (already counted in the savings)."
                if money["surplus_credit"]
                else "counted as worth nothing, because what the electricity company pays for them is not known."
            )
        )
    household = survey.get("household") or {}
    discom = policy.get_discom(household.get("discom_id") or "") if india else None
    if background and discom and discom.get("net_metering", {}).get("summary"):
        terms = discom["net_metering"]
        lines.append(
            f"- How {discom['name']} treats extra solar units (net metering): {terms['summary']}"
            + ("" if terms.get("verified") else f" THIS ENTRY IS NOT YET CONFIRMED. {terms.get('note', '')}".rstrip())
        )
    if money["notes"]:
        lines.append("CAVEATS ON THE MONEY FIGURES")
        lines += [f"- {note}" for note in money["notes"]]
    return lines


def fact_sheet(survey: dict) -> str:
    """
    The household's figures as labelled sentences.

    Models misread bare JSON keys (a yearly bill quoted as monthly, a price
    quoted as savings), so every figure is stated with what it is and its period.
    Anything the survey leaves empty is said to be missing rather than filled in.
    """
    location = survey.get("location") or {}
    household = survey.get("household") or {}
    system = survey.get("recommended_system") or {}
    country_code, country, currency = _place(survey)
    india = country_code == "IN"
    spot = _spot(survey.get("surface") or {})

    def amount(value: float) -> str:
        return _money(value, currency)

    place = ", ".join(part for part in (location.get("state"), country) if part)
    lines = ["LOCATION", f"- The property is in {place}." if place else "- Where the property is was not recorded."]
    lines += _site_lines(survey)

    lines.append("HOUSEHOLD")
    units = household.get("monthly_units")
    lines.append(
        f"- Electricity used in a typical month: {units:g} units." if units else "- Electricity used in a typical month: not entered yet."
    )
    bill = household.get("monthly_bill")
    lines.append(
        f"- Typical monthly bill, as given by the household: {amount(bill)}." if bill else "- Typical monthly bill: not entered by the household."
    )
    quote = household.get("vendor_quote")
    lines.append(f"- Vendor's quote, as given by the household: {amount(quote)}." if quote else "- Vendor's quote: none entered.")
    if india:
        discom = policy.get_discom(household.get("discom_id") or "")
        lines.append(
            f"- Electricity distributor: {discom['name']}."
            if discom
            else "- Electricity distributor: not one homesol has tariff or net-metering data for."
        )

    if not system.get("system_kw"):
        lines.append("RECOMMENDED SYSTEM: none yet, because the household has not entered their monthly electricity use.")
        return "\n".join(lines)

    panel_count = system.get("panels") or (survey.get("panels") or {}).get("recommended")
    lines += ["RECOMMENDED SYSTEM", f"- Size: {system['system_kw']:g} kW" + (f" ({panel_count} panels)." if panel_count else ".")]
    generation = system.get("monthly_generation_units") or []
    if generation:
        lines.append(
            f"- Expected generation: about {round(sum(generation) / len(generation))} units a month on average, {round(sum(generation))} units a year."
        )
    if system.get("share_of_usage_covered") is not None:
        lines.append(f"- Share of the household's yearly usage this covers: {round(system['share_of_usage_covered'] * 100)}%.")
    if system.get("limited_by") == "usage":
        fit = (survey.get("panels") or {}).get("fit")
        room = f": the {spot} could hold more" if fit and panel_count and fit > panel_count else ""
        lines.append(f"- The size is set by the household's usage, not by space{room}.")
    elif system.get("limited_by"):
        lines.append(f"- The size is limited by space: a bigger system would not fit on the {spot} where the sun is good.")

    money = baseline_finances(survey)
    if "error" in money:
        lines.append(f"MONEY: NOT CALCULATED. {money['error']} No cost, saving or payback figure exists for this household yet.")
        return "\n".join(lines)
    return "\n".join(lines + _money_lines(survey, money))


# ---- cleaning an answer --------------------------------------------------------------------


def known_hosts() -> set[str]:
    """Websites the policy data cites; an answer may link only to these."""
    found: set[str] = set()

    def walk(node) -> None:
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
        elif isinstance(node, str) and node.startswith("http"):
            found.add(_host(node))

    walk(policy.load())
    return found


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").removeprefix("www.")


def clean_answer(text: str) -> str:
    """Remove what must never reach the household: reasoning tags, markdown marks, made-up links."""
    text = re.sub(r"<thinking>.*?</thinking>", "", text, flags=re.DOTALL)
    text = re.sub(r"</?(thinking|response|answer)>", "", text)
    allowed = known_hosts()

    def link(match: re.Match) -> str:
        label, url = match.group(1), match.group(2)
        return f"{label} ({url})" if _host(url) in allowed else label

    text = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", link, text)
    # A full stop or comma after a link is punctuation, not part of the address.
    text = re.sub(r"\(?https?://[^\s)]+\)?", lambda m: m.group(0) if _host(m.group(0).strip("()").rstrip(".,;:!?")) in allowed else "", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"^#+\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*\*\s+", "- ", text, flags=re.MULTILINE)
    text = text.replace("`", "")
    text = re.sub(r"ल\s?akhs?\b", "लाख", text)  # "₹10.38 लakh": lakh half turned into Devanagari, seen from both models
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r" +([.,])", r"\1", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


# ---- tools ---------------------------------------------------------------------------------


def survey_tools(survey: dict, calculations: list[str] | None = None) -> list:
    """
    Tools bound to one household's survey.

    Each recalculation is also appended to `calculations`, word for word, so that it can be
    handed on unchanged instead of through a model's retelling of it.
    """
    country_code, country, currency = _place(survey)

    @tool
    def lookup_policy(state: str | None = None) -> str:
        """Subsidy rules, the usual price range, and the tariff and net-metering terms of the household's electricity distributor.

        homesol holds this data for India only. Every entry has a `source` link and a
        `verified` flag; say so when you rely on an entry whose flag is false.
        `rules_checked_on` is the date the rules were last checked, not an expiry date.

        Args:
            state: Leave empty for the household's own distributor. To read another Indian
                state's terms instead, give the state's name, for example "Gujarat".
        """
        if country_code != "IN":
            return json.dumps(
                {
                    "error": "homesol holds subsidy, price, tariff and net-metering data for India only. "
                    f"This property is in {country or 'a country that was not recorded'}, so nothing is known here about "
                    "its subsidies, tax credits, tariffs or what the electricity company pays for extra units."
                }
            )
        data = policy.load()
        result = {
            "rules_checked_on": data["as_of"],
            "central_subsidy": data["central_subsidy"],
            "usual_price_per_kw": data["system_cost_per_kw"],
        }
        discom_id = policy.discom_for_state(state) if state else (survey.get("household") or {}).get("discom_id")
        discom = policy.get_discom(discom_id or "")
        if discom:
            result["distributor"] = discom
        else:
            covered = sorted({d["state"] for d in data["discoms"].values()})
            subject = f"the state '{state}'" if state else "this household's electricity distributor"
            result["distributor_error"] = f"homesol has no tariff or net-metering data for {subject}. States it covers: {', '.join(covered)}."
        return json.dumps(result)

    @tool
    def estimate_finances(system_kw: float | None = None, quoted_cost: float | None = None) -> str:
        """Recalculate price, subsidy, yearly bills, savings and payback for this household.

        The household's usage, bill, distributor, country, expected generation and their own
        vendor quote (if they entered one) are taken from their survey. With no arguments this
        returns the figures for the recommended system. Give an argument only for a "what if",
        and only with a number the household actually asked about. Amounts are in the
        household's currency. The result is a list of labelled figures.

        Args:
            system_kw: A different system size to price, in kW.
            quoted_cost: A different price for the system before any subsidy, in the household's currency.
        """
        if system_kw is not None and not 0 < system_kw <= 1000:
            return "ERROR: system_kw must be a size in kW between 0 and 1000."
        if quoted_cost is not None and quoted_cost <= 0:
            return "ERROR: quoted_cost must be a price above zero."
        result = baseline_finances(survey, system_kw, quoted_cost)
        if "error" in result:
            return f"NOT CALCULATED. {result['error']}"
        recommended = (survey.get("recommended_system") or {}).get("system_kw")
        resized = bool(system_kw and recommended and abs(system_kw - recommended) > 0.01)
        heading = f"CALCULATION for a {result['system_kw']:g} kW system" + (" (the recommended size)" if not resized else "")
        if quoted_cost:
            heading += f" at a price of {_money(quoted_cost, currency)}"
        lines = _money_lines(survey, result, heading, background=False)
        if resized:
            largest = largest_system_kw(survey)
            if largest is not None and system_kw > largest + 0.01:
                lines.insert(
                    1,
                    f"- WARNING: a {system_kw:g} kW system does NOT fit. The {_spot(survey.get('surface') or {})} holds at most "
                    f"{largest:g} kW where the sun is good. The figures below are for a system that cannot be installed there.",
                )
            lines.append("- Generation for this size is scaled in proportion from the recommended system, so these figures are approximate.")
        text = "\n".join(lines)
        if calculations is not None:
            calculations.append(text)
        return text

    return [lookup_policy, estimate_finances]


# ---- prompts -------------------------------------------------------------------------------

SITE_PROMPT = """You are the site analyst inside homesol, a service that helps a household decide whether to put solar panels on their roof or land. homesol has surveyed the property: the surface the panels would go on, how much sun reaches it, what shades it, and a panel layout. homesol's advisor consults you and then writes the reply to the household. Your reader is the advisor, not the household.

Explain what the survey below means for the question you are asked: where the panels should go and why, how well this surface suits solar, what the listed obstructions do to it, and how far the survey can be trusted.

- Work only from the survey below and use its figures exactly. Do not add measurements, clearances, distances, angles, yields or rules of thumb with numbers from general knowledge: the advisor would pass them on as findings about this property.
- The percentages listed under what causes the shade are shares of the shade. The share of sunlight lost to shade is a different figure; keep the two apart.
- Direction words in the survey say where an obstruction stands as seen from the middle of the surface. Panels belong on the side away from the biggest causes of shade; say which side that is.
- When something was not recorded or not measured, say so and say what that leaves uncertain. An obstruction with no height, a survey estimated from hand marking instead of measured, or an old survey date are worth pointing out when they bear on the question.
- If the question is not about the site, say that it is outside what the survey covers.
- Do not name products, organisations or regulations from memory.

Reply in English, in plain text, with at most six short lines: the direct answer first, then the survey figures that support it, then anything uncertain. The household is waiting while you write, and the advisor will reword whatever you send, so leave out greetings, headings, tables, bold and anything not asked for."""

FINANCE_PROMPT = """You are the policy and finance analyst inside homesol, a service that helps a household decide whether to put solar panels on their roof or land. homesol's advisor consults you and then writes the reply to the household. Your reader is the advisor, not the household.

You have two tools, both already tied to this household:
- lookup_policy returns the subsidy rules, the usual price range, and the tariff and net-metering terms of the household's electricity distributor, each with a source link and a verified flag. homesol holds this data for India only.
- estimate_finances recalculates price, subsidy, bills, savings and payback. The money figures in the facts below are already its result for the recommended system, so call it for a "what if": a different system size, a different price, or both.

How to work:
- Take every rule and rate from lookup_policy, and every money figure from estimate_finances or the facts below. Do not recall rules or rates from memory and do not do the arithmetic yourself: subsidy caps, tariff slabs and yearly settlement make hand calculation come out wrong, and the household will act on these figures.
- Give estimate_finances only numbers that appear in the advisor's question. A price nobody stated would produce figures for a quote that does not exist. If the question needs a size or a price and gives none, say what is missing instead of assuming one. The household's own quote, when they entered one, is in the facts and is already used.
- When you need both tools, call them in the same turn. Call lookup_policy only when the question is about a rule or a rate; a recalculation does not need it.
- The advisor is handed every result of estimate_finances word for word, right under your reply, so do not copy its figures out, explain them, or compare them with the recommended system. After a recalculation your whole reply is normally one line, such as "Calculated for 4 kW." Add a second line only for something the advisor could miss: a warning the calculation raised, or an unverified entry its figures lean on.
- If a tool returns an error or a warning, report it as it is.
- When an entry you rely on has "verified": false, say that it still needs checking against the regulator's order, and give its source link.
- If homesol has no data for the household's distributor, say so and cover only what the data does hold. If the property is outside India, say homesol has no subsidy, tariff or price data there, and do not supply any from memory.
- If you are asked about something neither tool covers (loans and interest, batteries, panel brands, other investments, a state's own subsidy, anything outside India), say homesol has no data on it and stop there. Do not estimate, and do not name agencies, schemes, tax credits or websites from memory, not even as something to look into: a name you recall may no longer exist or apply, and the advisor would pass it on as homesol's. Give only names and links that a tool returned or the facts contain.

Reply in English, in plain text. For a rule or a rate, at most six short lines: each figure asked for with what it is, its period (a month, a year) and its currency; then any unverified entry it rests on; then the source link. The household is waiting while you write and the advisor rewords whatever you send, so every extra line is delay with no benefit: no greeting, no headings, tables or bold, no advice, nothing that was not asked."""

ADVISOR_INTRO = """You are homesol's advisor. homesol helps a household decide whether to put solar panels on their roof or land: it builds a measured 3D model of the property, lays out the panels, and works out cost and savings. You answer the household's questions about that plan in a small chat window beside it.

The person asking has probably never dealt with solar before and is deciding whether to spend a large sum. They need a straight answer they can follow, and figures they can rely on.

Below are this household's facts, then how to answer."""

ADVISOR_PROMPT = """# Where your figures come from

Every number you state must come from the household's facts above, from a specialist's notes in this conversation, or from the household's own messages. homesol's figures are calculated for this one property, from its survey, its electricity use and the rules where it stands. A number recalled from general knowledge (a typical loan rate, a battery price, a tax credit, what a utility pays for exported power, the best tilt for a latitude, how long an approval takes) may be wrong for this country, this year or this electricity company, and the household cannot tell which of your numbers were calculated and which were recalled. So:

- When the facts do not cover something, say in one plain sentence that homesol does not have that information, say who would (a bank, a vendor, their electricity company), and add anything from the facts that helps them ask, such as the amount they would be financing. Do not fill the gap with an estimate, a typical range, or a "for example" using numbers of your own: an example with invented numbers reads as an estimate. Do not hint at what the answer probably is either ("there may well be a tax credit that cuts your cost"): homesol does not know, and that is all you can say.
- Do not work out new figures yourself, not even the difference between two figures. To compare, state both ("₹6.23 lakh over 25 years, against ₹5.19 lakh for the recommended size") and let the household see the gap; never "₹1 lakh more" or "a year and a half longer". For a different system size or a different price, the finance analyst recalculates properly; subsidy caps, tariff slabs and yearly settlement make mental arithmetic come out wrong. For something homesol cannot calculate at all, such as a loan instalment, say so, even if the household supplies a rate.
- Keep each figure attached to what it is and to its period. A price is not a saving, and a yearly bill is not a monthly bill. You may round for readability ("about 5 years", "about ₹1.65 lakh"), but not change what a figure means.
- When the facts say something was not recorded, not measured, not known or not confirmed, tell the household that instead of smoothing it over. When a figure you quote rests on an entry marked unverified or not yet confirmed, say in a few words that it still needs confirming.
- The same goes for names. Mention an organisation, a scheme, a law or a website only if it is in the facts or in a specialist's notes, and copy a web link exactly. A name recalled from memory may be out of date or wrong for this place, so write "your electricity company" or "your state's energy office" instead of guessing which one it is.

# Staying within what homesol does

You are not a licensed financial adviser, and homesol has no data on other investments. If the household asks whether solar beats a fixed deposit, mutual funds, shares or anything else, or what to do with their money, say you cannot advise on that choice, give the solar figures (what it costs, what it saves a year, when it pays for itself) so they can compare for themselves, and leave it there. Do not describe the other option's returns or risk, in numbers or in words.

You are not an installer either. homesol knows nothing about particular vendors, panel brands or products, so do not name or recommend any. For the final design and a firm price, the household needs a site visit and a quote from a registered vendor.

When the facts say a vendor's quote is outside the usual price range, tell the household so directly, with the percentage. Where homesol has no price data for the country, say it cannot judge the quote.

If a question has nothing to do with this property's solar plan or its electricity, say briefly that it is outside what you can help with, and offer to help with the solar plan.

# Your two specialists

You can consult two specialists. Each consultation takes several seconds while the household waits, so answer straight from the facts whenever they already hold what is needed. That covers most questions about cost, subsidy, savings, payback, system size and what shades the property. The specialists know nothing beyond homesol's data either: when the facts say homesol has no data on something, tell the household so without consulting anyone.

- policy_finance_analyst: consult it when the household asks "what if" about a different system size or price (it recalculates), or asks for a rule or rate the facts do not give: tariff rates, the detail of subsidy or net-metering terms, or their sources.
- site_analyst: consult it when the household asks where the panels should go, how shade affects the layout, or how far to trust the survey, and the facts alone do not settle it.

Ask in English, in one specific sentence, and include any number the household gave (the size or price they are asking about) exactly as they gave it. The specialists already have this household's facts, so do not repeat them. If one question needs both, ask both at once.

What comes back is working notes for you, not text for the household. Under the finance analyst's notes you will find each calculation it ran, word for word as homesol's calculator returned it: take your figures from those lines, and if the notes disagree with them, the lines are right. Take what answers the question and say it in your own words. The household should feel they are talking to one advisor, so do not mention specialists, analysts, tools, calculators, a fact sheet, field names or internal codes. If you need to say where something comes from, say "homesol's survey" or "homesol's calculation".

# How to answer

Language. Reply in the language and script of the household's latest message, whatever language the facts, the notes or earlier turns are in:
- English gets English.
- Hindi in Devanagari gets Hindi in Devanagari.
- Hindi typed in Latin letters (Hinglish, such as "kitna kharcha aayega?") gets the same Latin-letter Hindi from the first word to the last, with no Devanagari. People type this way because it is what they read comfortably; a reply in English, or in Devanagari, may not be understood.
- Any other language gets that language, written the way its speakers write, numbers included.
Hindi speakers use the words solar, panel, subsidy, unit, system and bill as they are: keep them, in Latin letters in Hinglish and in Devanagari in Hindi (सोलर, पैनल, सब्सिडी, यूनिट). In Devanagari, lakh is लाख and crore is करोड़.

Shape. The chat window is small and the household reads on a phone, so a reply is at most 120 words. Decide what matters most and leave the rest for a follow-up question.
- Lead with the answer. The first sentence holds what was asked for: yes or no with the figure that decides it; or the amount, rate, time or size asked about; or a plain statement that homesol does not have it. How something works, where a figure comes from and what it depends on all come after. "Yes, solar looks worth it for your home: it should pay for itself in about 5 years." For a what-if: "A 4 kW system would cost you about ₹1.62 lakh after subsidy and pay for itself in about 3.7 years." For a breakdown, the bottom line in one sentence, then its parts: "In short, you would pay about ₹1.53 lakh after subsidy, save about ₹24,900 in the first year, and have your money back in about 5.9 years." Never a greeting, the question restated, or a lead-in such as "Here is the breakdown".
- Then the two to four facts that matter most for this question, each a short sentence with its figure. Short lines starting with "- " are fine.
- Then one next step, when there is a useful one. No closing offer of more help.
- Only when the household asks for detail or a full breakdown may the reply run past 120 words, and then give only what they asked for.

Plain words. Say "units" for kWh, "your electricity company" for DISCOM or utility, "pays for itself in 5 years" for payback or payback period, "price before subsidy" and "what you pay after subsidy" for gross and net cost, "the rates your electricity company charges" for tariff. Technical terms from the facts, such as net metering, tariff slab or inverter, need a few words of explanation in the same sentence every time a reply uses one: "net metering (your meter also counts the units you send to the grid, and they are set against what you use)".

Plain text. The chat window shows characters exactly as you write them, so no markdown: no asterisks, no headings, no tables, no backticks.

Money. Write amounts in the household's own currency, the way people there write it: Indian rupees as ₹91,500 or ₹1.65 lakh, US dollars as $21,500. Do not convert to another currency.

Earlier turns of the conversation may be included. The facts above are the current ones: if an earlier reply disagrees with them, the household has changed something since, and the facts are right."""

#: Hindi words in Latin letters that are not also English words. Two of them in a message mark it as Hinglish.
_HINGLISH_WORDS = frozenset(
    """hai hain hoga hogi honge kya kyun kyon kaise kitna kitni kitne kab kahan kaun mujhe mera meri mere hum hamara
    aap aapka aapki aapke nahi nahin aur lekin agar toh mein liye chahiye sakta sakti sakte karna karne karun
    lagega lagegi lagwana lagwa lagwaun milega milegi milta milti paisa paise kharcha bachat chhat saal mahine
    kuch sahi batao bataiye samjhao wala wali hota hoti raha rahi rahega aayega aayegi yeh ye woh iska kis""".split()
)


def _language_note(message: str) -> str:
    """
    A line telling the advisor which script the household is writing in, when code can tell.

    The prompt already says to answer in the household's language, but a short Hinglish question
    was now and then answered in Devanagari or in English. Naming the script outright stops that.
    """
    if re.search(r"[ऀ-ॿ]", message):
        return (
            "The household's latest message is in Hindi, in Devanagari script. Write your reply in Hindi, in Devanagari throughout, "
            "including borrowed words (सोलर, सब्सिडी, सिस्टम) and लाख for lakh. Only kW, web links and proper names stay in Latin letters."
        )
    words = re.findall(r"[a-z]+", message.lower())
    hindi = [word for word in words if word in _HINGLISH_WORDS]
    if len(set(hindi)) >= 2 and len(hindi) >= 0.2 * len(words):
        return (
            "The household's latest message is in Hinglish: Hindi typed in Latin letters. Write your whole reply in Hinglish, "
            "in Latin letters only, with no Devanagari and not in English."
        )
    return ""


# ---- the agents ----------------------------------------------------------------------------


def _turns(history: list[dict] | None) -> list[dict]:
    """The conversation so far as alternating turns that start with the household: what the model API requires."""
    turns: list[dict] = []
    for item in history or []:
        role, text = item.get("role"), (item.get("text") or "").strip()
        if role not in ("user", "assistant") or not text:
            continue
        if turns and turns[-1]["role"] == role:
            turns[-1]["text"] += f"\n\n{text}"
        elif turns or role == "user":
            turns.append({"role": role, "text": text})
    return turns


def _specialists(survey: dict, facts: str) -> list:
    """The two specialists, as tools the advisor can call. Each call runs a fresh agent, so nothing carries over."""
    model = _model(SPECIALIST_MODEL_ID, SPECIALIST_EFFORT, max_tokens=2500)

    @tool
    def site_analyst(question: str) -> str:
        """Explains the site survey: where the panels should go, how shade affects the layout, how far to trust the survey.

        Args:
            question: What you need to know, in English, in one or two sentences.
        """
        analyst = Agent(
            name="site_analyst",
            model=model,
            system_prompt=f"{SITE_PROMPT}\n\n# The survey\n\n{facts}",
            callback_handler=None,
            retry_strategy=_retries(),
        )
        return str(analyst(question)).strip()

    @tool
    def policy_finance_analyst(question: str) -> str:
        """Recalculates cost, savings and payback for a different system size or price, and looks up subsidy, tariff and net-metering rules with their sources.

        Args:
            question: What you need to know, in English, in one or two sentences, with any size or price the household gave, exactly as they gave it.
        """
        calculations: list[str] = []
        analyst = Agent(
            name="policy_finance_analyst",
            model=model,
            system_prompt=f"{FINANCE_PROMPT}\n\n# This household's facts\n\n{facts}",
            tools=survey_tools(survey, calculations),
            callback_handler=None,
            retry_strategy=_retries(),
        )
        notes = str(analyst(question)).strip()
        if calculations:
            # A model retelling a list of figures can get one wrong. The calculator's own words go along, and they win.
            notes += (
                "\n\nTHE CALCULATIONS BEHIND THESE NOTES, word for word from homesol's calculator. "
                "Where the notes and these lines differ, these lines are right.\n\n" + "\n\n".join(calculations)
            )
        return notes

    return [site_analyst, policy_finance_analyst]


def build_advisor(survey: dict, history: list[dict] | None = None, question: str = "") -> Agent:
    """A fresh advisor for one household, with its two specialist agents attached as tools.

    `history` is the conversation so far, as {"role": "user" | "assistant", "text": ...} items.
    Call the returned agent with the household's next question. Pass that question here too, if
    it is known: it is used only to tell the model which language and script to answer in.
    """
    facts = fact_sheet(survey)
    # The facts go before the rules: a model follows what it read last more closely.
    prompt = f"{ADVISOR_INTRO}\n\n# This household's facts\n\n{facts}\n\n{ADVISOR_PROMPT}"
    note = _language_note(question)
    if note:
        prompt += f"\n\n{note}"
    turns = _turns(history)
    if turns and turns[-1]["role"] == "user":  # the next message is the household's, and two in a row are not allowed
        turns.pop()
    return Agent(
        name="advisor",
        model=_model(ADVISOR_MODEL_ID, ADVISOR_EFFORT, max_tokens=4000),
        system_prompt=prompt,
        messages=[{"role": turn["role"], "content": [{"text": turn["text"]}]} for turn in turns],
        callback_handler=None,
        tools=_specialists(survey, facts),
        retry_strategy=_retries(),
    )


def answer(question: str, survey: dict, history: list[dict] | None = None) -> str:
    """
    The advisor's reply to one question, ready to show to the household.

    `survey` is the property and household as the dashboard shows them. `history` is the
    conversation before this question, oldest first, as {"role": "user" | "assistant",
    "text": ...} items. Model failures are raised as they come from Bedrock (botocore's
    ClientError and BotoCoreError) or from Strands (for example ModelThrottledException).
    """
    turns = _turns(history)
    if turns and turns[-1]["role"] == "user":  # an earlier question that never got its answer
        question = f"{turns.pop()['text']}\n\n{question}"
    advisor = build_advisor(survey, turns, question)
    text = clean_answer(str(advisor(question)))
    if not text:  # rare: the model stopped without writing anything
        text = clean_answer(str(advisor("Please give me your answer to that now.")))
    return text or "Sorry, I could not put an answer together just now. Please ask again."
