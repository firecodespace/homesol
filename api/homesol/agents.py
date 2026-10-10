"""Strands agents. They read numbers from tools and never work them out themselves."""

import json
import os

from strands import Agent, tool
from strands.models import BedrockModel

from . import finance, policy

MODEL_ID = os.environ.get("BEDROCK_AGENT_MODEL_ID", "us.anthropic.claude-opus-5-5")


@tool
def lookup_policy(discom_id: str) -> str:
    """Subsidy, tariff and net-metering rules for one electricity distributor.

    Returns the central PM Surya Ghar subsidy rules plus that distributor's
    tariff slabs and net-metering terms. Every entry carries a `source` link
    and a `verified` flag; say so when you rely on an unverified entry.

    Args:
        discom_id: One of "msedcl" (Maharashtra), "delhi", "bescom" (Karnataka).
    """
    data = policy.load()
    discom = policy.get_discom(discom_id)
    if not discom:
        return json.dumps({"error": f"No data for '{discom_id}'.", "supported": list(data["discoms"])})
    return json.dumps({"as_of": data["as_of"], "central_subsidy": data["central_subsidy"], "discom": discom})


@tool
def estimate_finances(
    system_kw: float,
    monthly_generation: list[float],
    monthly_usage: float,
    discom_id: str | None = None,
    monthly_bill: float | None = None,
    quoted_cost: float | None = None,
) -> str:
    """Cost, subsidy, yearly bill savings and payback for a rooftop system.

    Use this for every rupee figure, including what-if questions such as a
    different system size or a vendor's quote. Scale `monthly_generation` in
    proportion when changing `system_kw`.

    Args:
        system_kw: System size in kW.
        monthly_generation: Expected units generated in each month, January to December.
        monthly_usage: Units the household uses in a typical month.
        discom_id: Electricity distributor id, when known.
        monthly_bill: The household's typical monthly bill in rupees, when known.
        quoted_cost: A vendor's quoted price in rupees before subsidy, when the user has one.
    """
    try:
        return json.dumps(
            finance.estimate(
                system_kw=system_kw,
                monthly_generation=monthly_generation,
                monthly_usage=monthly_usage,
                discom_id=discom_id,
                monthly_bill=monthly_bill,
                quoted_cost=quoted_cost,
            ).to_dict()
        )
    except ValueError as err:
        return json.dumps({"error": str(err)})


SITE_PROMPT = """You are a rooftop solar site surveyor for Indian homes.

You are given the result of a shading survey of one roof: its area, how much of the year's direct sun reaches it, the usable area, the obstructions that were marked or scanned, and the recommended system. Explain what this means for where panels should go and how well this roof suits solar, and point out anything in the survey that looks incomplete (for example obstructions with no height, or no skyline scan on a roof surrounded by taller buildings).

Work only from the survey you are given. If something was not measured, say it was not measured rather than assuming."""

FINANCE_PROMPT = """You are a rooftop solar policy and finance analyst for Indian households.

Answer questions about subsidy, tariffs, net metering, cost, savings and payback. Every rule comes from lookup_policy and every rupee figure from estimate_finances: call them rather than recalling or calculating. When an entry you used is marked unverified, say that it still needs checking against the regulator's order, and give its source link. If the household's distributor is not supported, say so and explain only the central subsidy."""

ADVISOR_PROMPT = """You are homesol's advisor. You help a household in India decide whether rooftop solar is right for them and what to do next.

The person you are talking to has probably never dealt with solar before. Explain in plain, everyday words: say "units" for kWh, and when you use a term such as net metering, say in a few words what it is. Lead with the answer to what they asked, then the reason. Reply in the language the user writes in, including Hindi or Hinglish.

You have two specialists. Ask site_analyst about the roof, shade and panel placement. Ask policy_finance_analyst about subsidy, tariffs, cost, savings and payback. Pass them the relevant part of the household's survey, since they see only what you send. Report their caveats along with their numbers, and do not state a figure that neither they nor the survey gave you.

You are not a licensed financial advisor or an installer. For the final design and price, the household needs a site visit and quote from a registered vendor."""


def build_advisor() -> Agent:
    """A fresh advisor with its two specialist agents attached as tools."""
    model = BedrockModel(
        model_id=MODEL_ID,
        region_name=os.environ.get("AWS_REGION", "us-east-1"),
        max_tokens=4000,
    )
    site = Agent(model=model, system_prompt=SITE_PROMPT, callback_handler=None)
    money = Agent(
        model=model,
        system_prompt=FINANCE_PROMPT,
        tools=[lookup_policy, estimate_finances],
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
