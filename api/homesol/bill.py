"""Read the figures a solar estimate needs from a photo of an electricity bill."""

import base64
import os

import boto3
from pydantic import BaseModel, Field

from . import policy

MODEL_ID = os.environ.get("BEDROCK_VISION_MODEL_ID", "us.amazon.nova-pro-v1:0")

SYSTEM = """You read Indian household electricity bills for a rooftop solar calculator.

You are given a photo or scan of one bill. Bills are often bilingual (English with Hindi, Marathi, Kannada or Gujarati) and photographed at an angle. Report only what is printed on the bill.

- units_consumed: the units (kWh) billed for this billing period. This is the consumption figure, usually the difference between the current and previous meter readings, and not either reading itself.
- bill_amount: the charges for this billing period in rupees, before arrears, late fees or previous dues are added. If the bill shows only one total, use it.
- billing_days: the number of days the bill covers, if dates or a day count are printed.
- distributor: the name of the electricity company that issued the bill, as printed.
- state: the Indian state, if it can be read from the bill.
- sanctioned_load_kw: the sanctioned or connected load in kW, if printed.
- monthly_history: units for earlier months if the bill prints a consumption history, most recent first.

Leave out any field you cannot read with confidence: a missing value is handled, a wrong one misleads the household. Do not report the customer's name, address, consumer number, phone number or any other personal detail."""

TOOL = {
    "toolSpec": {
        "name": "report_bill",
        "description": "Report the figures read from the electricity bill.",
        "inputSchema": {
            "json": {
                "type": "object",
                "properties": {
                    "is_electricity_bill": {"type": "boolean"},
                    "units_consumed": {"type": "number"},
                    "bill_amount": {"type": "number"},
                    "billing_days": {"type": "integer"},
                    "distributor": {"type": "string"},
                    "state": {"type": "string"},
                    "sanctioned_load_kw": {"type": "number"},
                    "monthly_history": {"type": "array", "items": {"type": "number"}},
                },
                "required": ["is_electricity_bill"],
            }
        }
    }
}

#: Words on a bill that identify each supported distributor.
DISTRIBUTOR_NAMES = {
    "msedcl": ("msedcl", "mahavitaran", "maharashtra state electricity distribution"),
    "delhi": ("bses", "tata power delhi", "tata power-ddl", "tpddl", "ndpl"),
    "bescom": ("bescom", "bangalore electricity supply"),
    "gujarat": ("dgvcl", "mgvcl", "pgvcl", "ugvcl", "gujarat vij"),
}


class BillRequest(BaseModel):
    #: Base64 JPEG or PNG of the bill.
    image: str = Field(min_length=100)
    format: str = Field(default="jpeg", pattern="^(jpeg|png)$")


class BillReading(BaseModel):
    units_per_month: float | None = None
    bill_per_month: float | None = None
    discom_id: str | None = None
    distributor: str | None = None
    sanctioned_load_kw: float | None = None
    #: What the monthly figures were worked out from, for showing to the user.
    basis: str | None = None


class BillError(Exception):
    pass


def match_distributor(name: str | None, state: str | None) -> str | None:
    lowered = (name or "").lower()
    for discom_id, words in DISTRIBUTOR_NAMES.items():
        if any(word in lowered for word in words):
            return discom_id
    return policy.discom_for_state(state) if not name else None


def to_monthly(raw: dict) -> BillReading:
    """Turn what was printed on the bill into typical monthly figures."""
    units, amount, days = raw.get("units_consumed"), raw.get("bill_amount"), raw.get("billing_days")
    history = [u for u in raw.get("monthly_history") or [] if isinstance(u, (int, float)) and u > 0]

    # Some distributors bill every two months; scale to a 30-day month when the period is known.
    scale = 30 / days if days and 20 <= days <= 100 else 1.0
    this_month = units * scale if units and units > 0 else None
    basis = None
    units_per_month = this_month
    if len(history) >= 3:
        months = history + ([this_month] if this_month else [])
        units_per_month = sum(months) / len(months)
        basis = f"the average of {len(months)} months printed on the bill"
    elif this_month:
        basis = f"this bill's {round(units)} units over {days} days" if scale != 1.0 else "this bill"

    # Keep the bill amount in step with the units, so the implied price per unit stays the bill's own.
    bill_per_month = None
    if amount and amount > 0:
        bill_per_month = amount * (units_per_month / units) if units and units_per_month else amount * scale

    return BillReading(
        units_per_month=round(units_per_month) if units_per_month else None,
        bill_per_month=round(bill_per_month) if bill_per_month else None,
        discom_id=match_distributor(raw.get("distributor"), raw.get("state")),
        distributor=raw.get("distributor"),
        sanctioned_load_kw=raw.get("sanctioned_load_kw"),
        basis=basis,
    )


def read_bill(req: BillRequest) -> BillReading:
    client = boto3.client("bedrock-runtime", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    forced = "anthropic" not in MODEL_ID
    response = client.converse(
        modelId=MODEL_ID,
        system=[{"text": SYSTEM}],
        messages=[
            {
                "role": "user",
                "content": [
                    {"image": {"format": req.format, "source": {"bytes": base64.b64decode(req.image)}}},
                    {"text": "Read this bill and report it with the report_bill tool."},
                ],
            }
        ],
        toolConfig={"tools": [TOOL], "toolChoice": {"tool": {"name": "report_bill"}} if forced else {"auto": {}}},
        inferenceConfig={"maxTokens": 1000},
    )
    blocks = response["output"]["message"]["content"]
    raw = next((b["toolUse"]["input"] for b in blocks if "toolUse" in b), None)
    if raw is None:
        raise BillError("The bill could not be read. Try a clearer photo.")
    if not raw.get("is_electricity_bill"):
        raise BillError("That doesn't look like an electricity bill. Upload a photo of the bill itself.")
    reading = to_monthly(raw)
    if reading.units_per_month is None and reading.bill_per_month is None:
        raise BillError("The units and amount could not be read. Try a clearer, closer photo.")
    return reading
