"""Strands agents. They read numbers from tools and never work them out themselves."""

import json
import os
import re

from strands import Agent, tool
from strands.models import BedrockModel

from . import finance, policy

MODEL_ID = os.environ.get("BEDROCK_AGENT_MODEL_ID", "us.amazon.nova-pro-v1:0")


def baseline_finances(survey: dict, system_kw: float | None = None, quoted_cost: float | None = None) -> dict:
    """Finances for the surveyed household, at the recommended size unless another is given.

    Every input comes from the survey, so a model cannot pass a wrong figure.
    Generation scales in proportion to system size.
    """
    household = survey.get("household") or {}
    system = survey.get("recommended_system") or {}
    if not system.get("system_kw") or not household.get("monthly_units"):
        return {"error": "The survey has no recommended system yet. The household must enter monthly units first."}
    size = system_kw or system["system_kw"]
    scale = size / system["system_kw"]
    discom_id = household.get("discom_id")
    try:
        result = finance.estimate(
            system_kw=size,
            monthly_generation=[units * scale for units in system["monthly_generation_units"]],
            monthly_usage=household["monthly_units"],
            discom_id=discom_id if policy.get_discom(discom_id or "") else None,
            monthly_bill=household.get("monthly_bill_rupees"),
            # A vendor's quote prices the recommended size only, not a what-if size.
            quoted_cost=quoted_cost or (household.get("vendor_quote_rupees") if scale == 1 else None),
        ).to_dict()
    except ValueError as err:
        return {"error": str(err)}
    return {"system_kw": round(size, 2), **result}


def _rupees(amount: float) -> str:
    return f"Rs {round(amount):,}"


def fact_sheet(survey: dict) -> str:
    """
    The household's figures as labelled sentences.

    Models misread bare JSON keys (a yearly bill quoted as monthly, a price
    quoted as savings), so every figure is stated with what it is and its period.
    """
    roof = survey.get("roof") or {}
    household = survey.get("household") or {}
    system = survey.get("recommended_system") or {}
    lines = ["ROOF"]
    if roof:
        lines += [
            f"- Roof area: {roof.get('area_m2')} m2, of which {roof.get('usable_area_m2')} m2 gets enough sun for panels.",
            f"- Share of the year's direct sun reaching the roof: {round((roof.get('yearly_sun_reaching_roof') or 0) * 100)}%.",
            f"- Largest system the sunny area can hold: {roof.get('max_system_kw')} kW.",
            f"- Roof height: about {roof.get('height_m')} m.",
            "- A rooftop skyline scan with the phone "
            + ("has been done." if roof.get("skyline_scanned") else "has NOT been done yet."),
        ]
    obstructions = survey.get("obstructions") or []
    lines.append(f"OBSTRUCTIONS MARKED: {len(obstructions)}" + ("" if obstructions else " (none)"))
    for o in obstructions:
        height = f"{o['height_m']} m above the {o.get('height_from')}" if o.get("height_m") else "height not recorded"
        lines.append(f"- {o.get('kind')}: {height} (height source: {o.get('height_source')}).")

    lines.append("HOUSEHOLD")
    lines.append(f"- Electricity used in a typical month: {household.get('monthly_units')} units.")
    if household.get("monthly_bill_rupees"):
        lines.append(f"- Typical monthly bill, as given by the household: {_rupees(household['monthly_bill_rupees'])}.")
    discom = policy.get_discom(household.get("discom_id") or "")
    lines.append(
        f"- Electricity distributor: {discom['name']}." if discom else "- Electricity distributor: not one homesol has tariff data for."
    )

    if not system.get("system_kw"):
        lines.append("RECOMMENDED SYSTEM: none yet, because the household has not entered monthly units.")
        return "\n".join(lines)

    generation = system["monthly_generation_units"]
    lines += [
        "RECOMMENDED SYSTEM",
        f"- Size: {system['system_kw']} kW ({system.get('panels')} panels).",
        f"- Expected generation: about {round(sum(generation) / 12)} units a month on average, {round(sum(generation))} units a year.",
        f"- Share of the household's yearly usage this covers: {round((system.get('share_of_usage_covered') or 0) * 100)}%.",
        "- The size is limited by "
        + ("the roof: a bigger system would not fit in the sunny area." if system.get("limited_by") == "roof" else "the household's usage, not the roof."),
    ]

    money = baseline_finances(survey)
    if "error" in money:
        lines.append(f"MONEY: not calculated. {money['error']}")
        return "\n".join(lines)
    low, high = money["gross_cost_range"]
    lines += [
        "MONEY, for the recommended system",
        f"- Price before subsidy: {_rupees(money['gross_cost'])}"
        + (" (the vendor's quote)." if money["cost_is_quote"] else " (a typical market price, not a quote)."),
        f"- Usual market price range for this size: {_rupees(low)} to {_rupees(high)}.",
    ]
    if money["cost_is_quote"] and not low <= money["gross_cost"] <= high:
        gap = (money["gross_cost"] - high) / high if money["gross_cost"] > high else (low - money["gross_cost"]) / low
        side = "ABOVE the top" if money["gross_cost"] > high else "BELOW the bottom"
        lines.append(f"- The vendor's quote is {round(gap * 100)}% {side} of the usual range.")
    lines += [
        f"- Government subsidy (PM Surya Ghar): {_rupees(money['subsidy'])}.",
        f"- What the household pays after subsidy: {_rupees(money['net_cost'])}.",
        f"- Electricity bill today: {_rupees(money['bill_before'])} PER YEAR (about {_rupees(money['bill_before'] / 12)} a month).",
        f"- Electricity bill with solar: {_rupees(money['bill_after'])} PER YEAR (about {_rupees(money['bill_after'] / 12)} a month).",
        f"- Saved in the first year: {_rupees(money['first_year_savings'])}.",
        "- Years until the system has paid for itself: "
        + (f"{money['payback_years']}." if money["payback_years"] is not None else "more than 25."),
        f"- Saved over 25 years, after paying for the system: {_rupees(money['lifetime_savings'])}.",
    ]
    if money["surplus_units"]:
        lines.append(
            f"- Extra units sold back in a year: {money['surplus_units']}, worth {_rupees(money['surplus_credit'])} (already counted in the savings)."
        )
    lines.append("CAVEATS ON THE MONEY FIGURES")
    lines += [f"- {note}" for note in money["notes"]]
    return "\n".join(lines)


def known_links() -> set[str]:
    """Every source link in the policy data; the only links an answer may contain."""
    found: set[str] = set()

    def walk(node) -> None:
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
        elif isinstance(node, str) and node.startswith("http"):
            found.add(node.rstrip("/"))

    walk(policy.load())
    return found


def clean_answer(text: str) -> str:
    """Remove what must never reach the household: reasoning tags, markdown marks, made-up links."""
    text = re.sub(r"<thinking>.*?</thinking>", "", text, flags=re.DOTALL)
    text = re.sub(r"</?(thinking|response|answer)>", "", text)
    allowed = known_links()

    def link(match: re.Match) -> str:
        label, url = match.group(1), match.group(2)
        return f"{label} ({url})" if url.rstrip("/") in allowed else label

    text = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", link, text)
    text = re.sub(r"https?://[^\s)]+", lambda m: m.group(0) if m.group(0).rstrip("/.,") in allowed else "", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"^#+\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*\*\s+", "- ", text, flags=re.MULTILINE)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def survey_tools(survey: dict) -> list:
    """Tools bound to one household's survey."""

    @tool
    def lookup_policy(discom_id: str | None = None) -> str:
        """Subsidy, tariff and net-metering rules for the household's electricity distributor.

        Returns the central PM Surya Ghar subsidy rules plus the distributor's
        tariff slabs and net-metering terms. Every entry has a `source` link and
        a `verified` flag; say so when you rely on an unverified entry.
        `rules_checked_on` is the date the rules were last checked, not an expiry date.

        Args:
            discom_id: Leave empty for the household's own distributor. Otherwise one of
                "msedcl" (Maharashtra), "delhi", "bescom" (Karnataka), "gujarat".
        """
        data = policy.load()
        chosen = discom_id or (survey.get("household") or {}).get("discom_id") or ""
        discom = policy.get_discom(chosen)
        result = {"rules_checked_on": data["as_of"], "central_subsidy": data["central_subsidy"]}
        if discom:
            result["discom"] = discom
        else:
            result["discom_error"] = f"No tariff data for '{chosen}'. Supported: {list(data['discoms'])}."
        return json.dumps(result)

    @tool
    def estimate_finances(system_kw: float | None = None, quoted_cost: float | None = None) -> str:
        """Cost, subsidy, yearly bill savings and payback for this household.

        Call with no arguments for the recommended system. The household's usage,
        bill, distributor and expected generation are taken from their survey.
        Use the arguments only for what-if questions.

        Args:
            system_kw: A different system size to price, in kW.
            quoted_cost: A vendor's quoted price in rupees before subsidy.
        """
        return json.dumps(baseline_finances(survey, system_kw, quoted_cost))

    return [lookup_policy, estimate_finances]


SITE_PROMPT = """You are a rooftop solar site surveyor for Indian homes.

The result of a shading survey of one roof is given below: its area, how much of the year's direct sun reaches it, the usable area, the obstructions that were marked or scanned, and the recommended system. Explain what this means for where panels should go and how well this roof suits solar, and point out anything in the survey that looks incomplete (for example obstructions with no height, or no skyline scan on a roof surrounded by taller buildings).

Work only from the survey below, and use its figures exactly. If something was not measured, say it was not measured rather than assuming. If the skyline scan has already been done, do not ask for it again."""

FINANCE_PROMPT = """You are a rooftop solar policy and finance analyst for Indian households.

Answer questions about subsidy, tariffs, net metering, cost, savings and payback. Every rule comes from lookup_policy and every rupee figure from estimate_finances: call them rather than recalling or calculating. Both tools already know this household's usage, bill, distributor and recommended system, so call estimate_finances with no arguments unless the question is a what-if about a different size or a vendor's quote. When an entry you used is marked unverified, say that it still needs checking against the regulator's order, and give its source link. If the household's distributor is not supported, say so and explain only the central subsidy."""

ADVISOR_PROMPT = """You are homesol's advisor. You help a household in India decide whether rooftop solar is right for them and what to do next.

The person you are talking to has probably never dealt with solar before. Explain in plain, everyday words: say "units" for kWh, and when you use a term such as net metering, say in a few words what it is.

Language: answer in the language of the household's latest question, and only that language. An English question gets an English answer. A question in Devanagari gets an answer in Devanagari Hindi. A question in Hindi typed in Roman letters (Hinglish, such as "kitna kharcha aayega?") gets an answer in the same Roman-letter Hindi from first word to last, not English. The survey being about India is not a reason to answer in Hindi.

Shape of the answer: the first sentence answers the question directly, for example "Yes, solar looks worth it for your home: it should pay for itself in about 5 years." Then give the three or four facts that matter most for that question, each in one short sentence with its number. Then one next step. Keep the whole answer under 150 words unless the household asks for detail. Your specialists send you long reports; choose from them, do not paste them. Write plain text for a small chat window: no markdown, no asterisks, no headings; short lines starting with "-" are fine for the facts. Write rupee amounts the Indian way, such as ₹91,500 or ₹1.65 lakh.

You have two specialists. Ask site_analyst about the roof, shade and panel placement. Ask policy_finance_analyst about subsidy, tariffs, cost, savings and payback. Both already have this household's survey and figures, so just ask them the question. The household's facts are also given to you directly, each labelled with what it is and whether it is per month or per year: copy figures with their labels, and never move a figure to a different meaning (a price is not a saving; a yearly bill is not a monthly bill). When the facts list a caveat that bears on your answer, pass it on in a few words.

What you do not have: if the answer needs a figure that is not in the facts or a specialist's reply (battery prices, panel brands, loan rates, returns on other investments), say plainly that homesol does not have that information, and do not estimate it. Do not compare solar with fixed deposits, mutual funds or any other investment, and do not tell the household what to do with their money; give the solar figures and leave the choice to them. If the question has nothing to do with their home's electricity or solar, say that is outside what you can help with. Include a web link only if it appears in the facts or a specialist's reply. Never mention your specialists, tools or internal ids.

When a vendor's quote is outside the usual range, say so directly, with the percentage from the facts.

You are not a licensed financial advisor or an installer. For the final design and price, the household needs a site visit and quote from a registered vendor."""


def build_advisor(survey: dict) -> Agent:
    """A fresh advisor for one household, with its two specialist agents attached as tools."""
    model = BedrockModel(
        model_id=MODEL_ID,
        region_name=os.environ.get("AWS_REGION", "us-east-1"),
        max_tokens=4000,
    )
    facts = fact_sheet(survey)
    site = Agent(
        model=model,
        system_prompt=f"{SITE_PROMPT}\n\nThis household's survey:\n{facts}",
        callback_handler=None,
    )
    money = Agent(
        model=model,
        system_prompt=FINANCE_PROMPT,
        tools=survey_tools(survey),
        callback_handler=None,
    )
    return Agent(
        model=model,
        system_prompt=ADVISOR_PROMPT,
        callback_handler=None,
        tools=[
            site.as_tool(name="site_analyst", description="Explains the roof survey: shade, usable area, panel placement."),
            money.as_tool(
                name="policy_finance_analyst",
                description="Answers subsidy, tariff, net-metering, cost, savings and payback questions with sourced figures.",
            ),
        ],
    )
