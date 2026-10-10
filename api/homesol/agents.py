"""Strands agents. They read numbers from tools and never work them out themselves."""

import json
import os

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
            quoted_cost=quoted_cost or household.get("vendor_quote_rupees"),
        ).to_dict()
    except ValueError as err:
        return {"error": str(err)}
    return {"system_kw": round(size, 2), **result}


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
                "msedcl" (Maharashtra), "delhi", "bescom" (Karnataka).
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

You are given the result of a shading survey of one roof: its area, how much of the year's direct sun reaches it, the usable area, the obstructions that were marked or scanned, and the recommended system. Explain what this means for where panels should go and how well this roof suits solar, and point out anything in the survey that looks incomplete (for example obstructions with no height, or no skyline scan on a roof surrounded by taller buildings).

Work only from the survey you are given. If something was not measured, say it was not measured rather than assuming."""

FINANCE_PROMPT = """You are a rooftop solar policy and finance analyst for Indian households.

Answer questions about subsidy, tariffs, net metering, cost, savings and payback. Every rule comes from lookup_policy and every rupee figure from estimate_finances: call them rather than recalling or calculating. Both tools already know this household's usage, bill, distributor and recommended system, so call estimate_finances with no arguments unless the question is a what-if about a different size or a vendor's quote. When an entry you used is marked unverified, say that it still needs checking against the regulator's order, and give its source link. If the household's distributor is not supported, say so and explain only the central subsidy."""

ADVISOR_PROMPT = """You are homesol's advisor. You help a household in India decide whether rooftop solar is right for them and what to do next.

The person you are talking to has probably never dealt with solar before. Explain in plain, everyday words: say "units" for kWh, and when you use a term such as net metering, say in a few words what it is.

Language: answer in the language of the household's latest question, and only that language. An English question gets an English answer; a Hindi question gets a Hindi answer; Hinglish gets Hinglish. The survey being about India is not a reason to answer in Hindi.

Shape of the answer: the first sentence answers the question directly, for example "Yes, solar looks worth it for your home: it should pay for itself in about 5 years." Then give the three or four facts that matter most for that question, each in one short sentence with its number. Then one next step. Keep the whole answer under 150 words unless the household asks for detail. Your specialists send you long reports; choose from them, do not paste them. Write plain text for a small chat window: no markdown, no asterisks, no headings; short lines starting with "-" are fine for the facts. Write rupee amounts the Indian way, such as ₹91,500 or ₹1.65 lakh.

You have two specialists. Ask site_analyst about the roof, shade and panel placement. Ask policy_finance_analyst about subsidy, tariffs, cost, savings and payback. Pass site_analyst the roof and obstruction parts of the survey, since it sees only what you send. policy_finance_analyst already has the household's figures, so just ask it the question. Take every figure from them or from the survey, and when a figure rests on unverified data, say so in a few words.

You are not a licensed financial advisor or an installer. For the final design and price, the household needs a site visit and quote from a registered vendor."""


def build_advisor(survey: dict) -> Agent:
    """A fresh advisor for one household, with its two specialist agents attached as tools."""
    model = BedrockModel(
        model_id=MODEL_ID,
        region_name=os.environ.get("AWS_REGION", "us-east-1"),
        max_tokens=4000,
    )
    site = Agent(model=model, system_prompt=SITE_PROMPT, callback_handler=None)
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
