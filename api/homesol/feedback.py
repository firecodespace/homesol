"""
Human verdicts on automatic obstruction detection.

Every detection run and every confirm / reject / missed-object verdict is kept,
so detection quality can be measured and, with enough verdicts, a model trained
on them. Only geometry and labels are stored, as map coordinates; the satellite
pixels are not, since the imagery belongs to its provider.
"""

import json
import os
import time
import uuid
from typing import Literal

import boto3
from pydantic import BaseModel, Field

TABLE = os.environ.get("FEEDBACK_TABLE", "homesol-feedback")


class Verdict(BaseModel):
    detection_id: str = Field(min_length=8, max_length=64)
    #: confirmed: the model was right (after any corrections the user made).
    #: rejected: the model reported something that is not an obstruction.
    #: missed: the user drew an obstruction the model did not report.
    verdict: Literal["confirmed", "rejected", "missed"]
    #: Index of the object in the model's report; absent for missed objects.
    model_index: int | None = None
    kind: Literal["building", "tree", "tank", "other"]
    #: Final outline as [lng, lat] pairs.
    footprint: list[tuple[float, float]] = Field(min_length=3, max_length=40)
    height_m: float | None = None
    height_from: Literal["ground", "roof"]
    #: The surveyed roof as [lng, lat] pairs, which locates the image the model saw.
    roof: list[tuple[float, float]] = Field(min_length=3, max_length=60)


def _table():
    return boto3.resource("dynamodb", region_name=os.environ.get("AWS_REGION", "us-east-1")).Table(TABLE)


def record_run(model_id: str, request_meta: dict, reported: list[dict]) -> str | None:
    """Keep what the model reported for one image. Returns the id verdicts will refer to."""
    detection_id = uuid.uuid4().hex
    try:
        _table().put_item(
            Item={
                "id": detection_id,
                "sk": "run",
                "created": int(time.time()),
                "model": model_id,
                "request": json.dumps(request_meta),
                "reported": json.dumps(reported),
            }
        )
    except Exception:
        # Losing a training record must never fail the user's detection.
        return None
    return detection_id


def record_verdict(verdict: Verdict) -> None:
    _table().put_item(
        Item={
            "id": verdict.detection_id,
            "sk": f"verdict#{time.time_ns()}",
            "created": int(time.time()),
            "verdict": verdict.verdict,
            "body": verdict.model_dump_json(exclude={"detection_id", "verdict"}),
        }
    )


def summary() -> dict:
    """Counts of runs and verdicts so far, and the precision and recall they imply."""
    counts = {"runs": 0, "confirmed": 0, "rejected": 0, "missed": 0}
    scan: dict = {"ProjectionExpression": "sk, verdict"}
    while True:
        page = _table().scan(**scan)
        for item in page["Items"]:
            counts["runs" if item["sk"] == "run" else item["verdict"]] += 1
        if "LastEvaluatedKey" not in page:
            break
        scan["ExclusiveStartKey"] = page["LastEvaluatedKey"]
    judged = counts["confirmed"] + counts["rejected"]
    real = counts["confirmed"] + counts["missed"]
    return {
        **counts,
        "precision": round(counts["confirmed"] / judged, 2) if judged else None,
        "recall": round(counts["confirmed"] / real, 2) if real else None,
    }
