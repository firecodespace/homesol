"""Find objects that could shade a roof in a satellite image, using a vision model on Bedrock."""

import base64
import os
from typing import Literal

import boto3
from pydantic import BaseModel, Field, ValidationError

from .models import VISION_MODEL_ID as MODEL_ID
from .models import tool_choice

#: The model reports positions on a 0–1000 grid whatever the image size.
GRID = 1000

SYSTEM = """You survey rooftops in India for solar panel installation from satellite images.

You are given a square, north-up satellite image. One roof is outlined in yellow: that is the roof where panels will go. Your job is to find everything that could cast a shadow onto that roof, so a shading calculation can account for it.

Report two kinds of objects:
- Things standing on the outlined roof: stair rooms (mumty), water tanks, lift rooms, sheds, existing equipment.
- Things next to it that rise above it: taller neighbouring buildings and trees. Skip neighbours that are clearly lower than the outlined roof, and skip anything more than about 30 m away unless it is a tall tower.

For each object give its footprint as it sits on the surface, not including its shadow. Trace it tightly: a water tank is a few metres across, not the whole roof.

Shadows are the best evidence of height. When an object's shadow is clearly visible from base to tip, report the foot of the corner casting it and the tip of that corner's shadow, both on the surface the shadow falls on. If the shadow is hidden, merges with another, or falls across surfaces at different levels, leave the shadow out: a wrong shadow is worse than none.

Do not report the outlined roof itself, flat markings, stains, vehicles, or shadows as objects. If nothing would shade the roof, report an empty list.

Give every position as [x, y] on a 0 to 1000 grid, where [0, 0] is the top-left corner of the image, x runs right and y runs down."""

POINT = {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2}
TOOL = {
    "toolSpec": {
        "name": "report_obstructions",
        "description": "Report every object that could shade the outlined roof.",
        "inputSchema": {
            "json": {
                "type": "object",
                "required": ["obstructions"],
                "properties": {
                    "obstructions": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["kind", "label", "on_roof", "outline", "typical_height_m"],
                            "properties": {
                                "kind": {"type": "string", "enum": ["building", "tree", "tank", "other"]},
                                "label": {"type": "string", "description": "Two to five plain words, e.g. 'stair room'."},
                                "on_roof": {"type": "boolean", "description": "True if it stands on the outlined roof itself."},
                                "outline": {"type": "array", "items": POINT, "description": "Footprint corners in order, 3 to 8 points."},
                                "shadow_base": {**POINT, "description": "Foot of the corner casting a clearly visible shadow."},
                                "shadow_tip": {**POINT, "description": "Where that same corner's shadow ends."},
                                "typical_height_m": {"type": "number", "description": "Best guess of its height above the surface it stands on."},
                            },
                        },
                    }
                },
            }
        }
    }
}


class Point(BaseModel):
    x: float
    y: float


class Shadow(BaseModel):
    base: Point
    tip: Point


class Obstruction(BaseModel):
    kind: Literal["building", "tree", "tank", "other"]
    label: str
    on_roof: bool
    outline: list[Point]
    shadow: Shadow | None
    typical_height_m: float


class DetectRequest(BaseModel):
    #: Base64 JPEG, square, with the roof outlined in yellow.
    image: str = Field(min_length=100)
    size: int = Field(gt=0)
    metres_per_pixel: float = Field(gt=0)
    #: Compass bearing shadows point in at the likely capture time, if the image date is known.
    shadow_bearing: float | None = None


class DetectionError(Exception):
    pass


def _point(raw, size: int) -> Point:
    x, y = raw
    scale = size / GRID
    return Point(x=min(max(float(x), 0), GRID) * scale, y=min(max(float(y), 0), GRID) * scale)


def detect(req: DetectRequest) -> list[Obstruction]:
    """Obstructions in image pixels, top-left origin."""
    width_m = req.size * req.metres_per_pixel
    context = f"The image covers about {width_m:.0f} m by {width_m:.0f} m."
    if req.shadow_bearing is not None:
        context += (
            f" From the image date, shadows should point towards compass bearing {req.shadow_bearing:.0f} degrees"
            " (0 is up, 90 is right)."
        )

    client = boto3.client("bedrock-runtime", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    response = client.converse(
        modelId=MODEL_ID,
        system=[{"text": SYSTEM}],
        messages=[
            {
                "role": "user",
                "content": [
                    {"image": {"format": "jpeg", "source": {"bytes": base64.b64decode(req.image)}}},
                    {"text": context + " Report what you find with the report_obstructions tool."},
                ],
            }
        ],
        toolConfig={"tools": [TOOL], "toolChoice": tool_choice(MODEL_ID, "report_obstructions")},
        inferenceConfig={"maxTokens": 4000},
    )

    blocks = response["output"]["message"]["content"]
    report = next((b["toolUse"]["input"] for b in blocks if "toolUse" in b), None)
    if report is None:
        raise DetectionError("The model did not report any result. Try again.")

    found: list[Obstruction] = []
    for raw in report.get("obstructions", []):
        try:
            outline = [_point(p, req.size) for p in raw["outline"]]
            shadow = None
            if raw.get("shadow_base") and raw.get("shadow_tip"):
                shadow = Shadow(base=_point(raw["shadow_base"], req.size), tip=_point(raw["shadow_tip"], req.size))
            found.append(
                Obstruction(
                    kind=raw["kind"],
                    label=raw["label"],
                    on_roof=raw["on_roof"],
                    outline=outline,
                    shadow=shadow,
                    typical_height_m=raw["typical_height_m"],
                )
            )
        except (KeyError, TypeError, ValueError, ValidationError):
            # One malformed object should not discard the rest.
            continue
    return [o for o in found if len(o.outline) >= 3]
