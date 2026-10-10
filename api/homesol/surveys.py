"""Saved surveys, so a roof outlined on one device can be opened on another."""

import json
import os
import secrets
import time

import boto3

TABLE = os.environ.get("SURVEYS_TABLE", "homesol-surveys")
KEEP_SECONDS = 90 * 24 * 3600
MAX_BYTES = 200_000
#: Unambiguous when read aloud or typed: no 0/O, 1/I/L.
ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


class SurveyTooLarge(Exception):
    pass


def _table():
    return boto3.resource("dynamodb", region_name=os.environ.get("AWS_REGION", "us-east-1")).Table(TABLE)


def save(survey: dict) -> str:
    """Store a survey and return the share code that opens it."""
    body = json.dumps(survey, separators=(",", ":"))
    if len(body.encode()) > MAX_BYTES:
        raise SurveyTooLarge
    code = "".join(secrets.choice(ALPHABET) for _ in range(8))
    now = int(time.time())
    _table().put_item(
        Item={"code": code, "survey": body, "created": now, "expires": now + KEEP_SECONDS},
        ConditionExpression="attribute_not_exists(code)",
    )
    return code


def load(code: str) -> dict | None:
    item = _table().get_item(Key={"code": code.strip().upper()}).get("Item")
    if not item or int(item["expires"]) < time.time():
        return None
    return json.loads(item["survey"])
