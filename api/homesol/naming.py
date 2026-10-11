"""
Names for what the height data found.

The site model measures every obstruction: where it is, how tall, how big.
What it cannot tell is what the thing is. A vision model looks at the photo
with each obstruction outlined and numbered, and says what it sees. It names
things; it never changes a measurement.
"""

import base64
import os

import boto3
from pydantic import BaseModel, Field

from .models import VISION_MODEL_ID, tool_choice

SYSTEM = """You help households understand a survey of their property for solar panels.

You are given an aerial photo, north up. The surface the panels would sit on (a roof, or a piece of land) is outlined in white. Height measurements have already found everything standing on that surface or rising above it nearby, and each of those is outlined in colour and numbered on the photo. You also get each one's measured facts: whether it stands on the surface, how far it rises above the surface, its footprint, and for neighbours their distance and direction.

Your job is to say what each numbered thing is, so the household recognises it. They know their own property: "the stair room", "the water tank", "the neem tree by the gate", "the neighbour's house to the south" are the kind of names that land. Use what you can see in the photo together with the measurements. A footprint of a few square metres standing one to two metres above a roof is usually a water tank; a room-sized block two and a half to four metres above it is usually a stair room or lift room; round, textured, dark green shapes are trees; a large flat-topped block beside the surface is a neighbouring building. The height data sometimes runs several things together into one outline; if you can see that an outline covers, say, two buildings and a tree, name it for what it mostly is and say so in the explanation.

For each item give:
- name: two to five plain words, as the household would say it. No measurements in the name.
- explanation: one sentence of at most 22 words saying what it is and what it means for the panels, in everyday language. Do not repeat the numbers you were given; the app shows those itself.
- confidence: "high" if the photo clearly shows it, "medium" if the photo is consistent with it, "low" if you are going mainly on the measurements.

The measurements are facts. If the photo seems to disagree with them (imagery and height data can be from different dates), trust the measurements, keep your name cautious, and mark the confidence low. Name every item you were given, and only those."""

TOOL = {
    "toolSpec": {
        "name": "report_names",
        "description": "Report what each numbered obstruction is.",
        "inputSchema": {
            "json": {
                "type": "object",
                "required": ["items"],
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["number", "name", "explanation", "confidence"],
                            "properties": {
                                "number": {"type": "integer"},
                                "name": {"type": "string"},
                                "explanation": {"type": "string"},
                                "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                            },
                        },
                    }
                },
            }
        }
    }
}


class Measured(BaseModel):
    """One obstruction as the site model measured it."""

    number: int
    on_surface: bool
    height_above_m: float
    area_m2: float
    distance_m: float
    direction: str
    #: Share of the surface's lost sunlight this obstruction causes, 0 to 1.
    share_of_shade: float | None = None


class NamingRequest(BaseModel):
    #: Base64 JPEG of the photo with the surface outlined in white and each obstruction numbered.
    image: str = Field(min_length=100)
    #: "roof" or "land", for wording.
    surface: str = "roof"
    items: list[Measured] = Field(min_length=1, max_length=16)


class Named(BaseModel):
    number: int
    name: str
    explanation: str
    confidence: str


def name_obstructions(req: NamingRequest) -> list[Named]:
    facts = "\n".join(
        f"{m.number}. "
        + (f"stands on the {req.surface}" if m.on_surface else f"{m.distance_m:.0f} m to the {m.direction} of the {req.surface}")
        + f"; rises {m.height_above_m:.1f} m above it; footprint {m.area_m2:.0f} m2"
        + (f"; causes {round(m.share_of_shade * 100)}% of the shade on it" if m.share_of_shade is not None else "")
        for m in req.items
    )
    client = boto3.client("bedrock-runtime", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    response = client.converse(
        modelId=VISION_MODEL_ID,
        system=[{"text": SYSTEM}],
        messages=[
            {
                "role": "user",
                "content": [
                    {"image": {"format": "jpeg", "source": {"bytes": base64.b64decode(req.image)}}},
                    {"text": f"The surface is a {req.surface}. Measured facts for each numbered item:\n{facts}"},
                ],
            }
        ],
        toolConfig={"tools": [TOOL], "toolChoice": tool_choice(VISION_MODEL_ID, "report_names")},
        inferenceConfig={"maxTokens": 2000},
    )
    blocks = response["output"]["message"]["content"]
    report = next((b["toolUse"]["input"] for b in blocks if "toolUse" in b), None)
    wanted = {m.number for m in req.items}
    named: list[Named] = []
    for raw in (report or {}).get("items", []):
        try:
            item = Named(**raw)
        except (TypeError, ValueError):
            continue
        if item.number in wanted and item.name.strip():
            named.append(item)
    return named
