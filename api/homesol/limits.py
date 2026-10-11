"""Rate limits on the endpoints that cost money: Google's survey, Claude on Bedrock, Amazon Transcribe.

The API is public, so each visitor gets an allowance per hour for each kind of work, and all
visitors together get an allowance per day. One heavy user cannot run up the bill, and the demo
stays open for everyone else.

Visitors are told apart by a salted hash of their IP address; the address itself is never stored.
Counters live in DynamoDB when `RATE_LIMIT_TABLE` is set: one atomic counter per visitor and hour,
and one per day for everyone, shared by every Lambda instance and deleted by DynamoDB's own expiry.
Without the table, or if it cannot be reached, each instance counts in memory instead, so the
limits still hold, per instance.

A request over its allowance gets HTTP 429 with a `detail` object the website shows as it is: what
was limited, for whom, and when it can be tried again.
"""

import hashlib
import json
import logging
import math
import os
import threading
import time
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request

log = logging.getLogger(__name__)

HOUR = 3600
DAY = 86400


@dataclass(frozen=True)
class Kind:
    #: How the limit is named to the visitor: "You've used this hour's 60 live measurements."
    label: str
    per_visitor_hour: int
    everyone_day: int


#: Allowances, chosen so a person exploring several properties never meets them: finding and
#: measuring one property takes a handful of measurements, and an advisor conversation a few answers.
KINDS = {
    "measure": Kind("live measurements", 60, 1500),
    "ai": Kind("AI answers and readings", 30, 600),
    "speech": Kind("voice questions", 30, 500),
}


def _overrides() -> None:
    """RATE_LIMITS='{"measure": [60, 1500], ...}' changes allowances without a code change."""
    raw = os.environ.get("RATE_LIMITS")
    if not raw:
        return
    for name, (hourly, daily) in json.loads(raw).items():
        KINDS[name] = Kind(KINDS[name].label, int(hourly), int(daily))


_overrides()


class MemoryCounter:
    """Counts in this process: the fallback, and what local runs and tests use."""

    def __init__(self) -> None:
        self._hits: dict[str, tuple[int, float]] = {}
        self._lock = threading.Lock()

    def add(self, key: str, expires: float) -> int:
        with self._lock:
            now = time.time()
            if len(self._hits) > 10_000:
                self._hits = {k: v for k, v in self._hits.items() if v[1] > now}
            count, until = self._hits.get(key, (0, expires))
            if until <= now:
                count, until = 0, expires
            self._hits[key] = (count + 1, until)
            return count + 1


class DynamoCounter:
    """Atomic counters in DynamoDB, shared by every instance. Items expire on their own."""

    def __init__(self, table: str) -> None:
        import boto3

        self._table = boto3.resource("dynamodb", region_name=os.environ.get("AWS_REGION", "us-east-1")).Table(table)

    def add(self, key: str, expires: float) -> int:
        result = self._table.update_item(
            Key={"id": key},
            UpdateExpression="ADD #h :one SET #e = if_not_exists(#e, :expires)",
            ExpressionAttributeNames={"#h": "hits", "#e": "expires"},
            ExpressionAttributeValues={":one": 1, ":expires": int(expires)},
            ReturnValues="UPDATED_NEW",
        )
        return int(result["Attributes"]["hits"])


class Limiter:
    def __init__(self, counter=None, clock=time.time) -> None:
        table = os.environ.get("RATE_LIMIT_TABLE")
        self.counter = counter or (DynamoCounter(table) if table else MemoryCounter())
        self.fallback = MemoryCounter()
        self.clock = clock

    def _add(self, key: str, expires: float) -> int:
        try:
            return self.counter.add(key, expires)
        except Exception as err:  # DynamoDB unreachable or not permitted: count here instead
            log.warning("rate limit store unavailable, counting in memory: %s", err)
            self.counter = self.fallback
            return self.counter.add(key, expires)

    def check(self, kind_name: str, visitor: str) -> None:
        """Count one request; raise HTTP 429 when it is over either allowance."""
        kind = KINDS[kind_name]
        now = self.clock()
        hour, day = int(now // HOUR), int(now // DAY)
        hour_ends, day_ends = (hour + 1) * HOUR, (day + 1) * DAY
        # Kept a little past the window so a counter never vanishes while still in use.
        if self._add(f"{kind_name}#v#{visitor}#{hour}", hour_ends + 300) > kind.per_visitor_hour:
            raise _limited(kind_name, "visitor", kind.per_visitor_hour, "hour", hour_ends - now)
        if self._add(f"{kind_name}#all#{day}", day_ends + 300) > kind.everyone_day:
            raise _limited(kind_name, "everyone", kind.everyone_day, "day", day_ends - now)


def _wait(seconds: float) -> str:
    minutes = max(1, math.ceil(seconds / 60))
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} hour{'s' if hours != 1 else ''}" + (f" {minutes} minute{'s' if minutes != 1 else ''}" if minutes else "")


def _limited(kind_name: str, scope: str, limit: int, window: str, retry_after: float) -> HTTPException:
    kind = KINDS[kind_name]
    retry_after = max(1, math.ceil(retry_after))
    if scope == "visitor":
        message = f"You've used this hour's {limit:,} {kind.label}. You can carry on in {_wait(retry_after)}."
    else:
        message = f"homesol has used today's {limit:,} {kind.label} for all visitors. They reset at midnight UTC, in {_wait(retry_after)}."
    return HTTPException(
        status_code=429,
        detail={"message": message, "id": kind_name, "scope": scope, "kind": kind.label, "limit": limit, "window": window, "retry_after": retry_after},
        headers={"Retry-After": str(retry_after)},
    )


def visitor_of(request: Request) -> str:
    """A salted hash of the caller's address.

    On Lambda, Mangum sets the client to the function URL's own `sourceIp`, which the caller cannot
    forge. X-Forwarded-For is deliberately not read: a caller can send any value there, and a new
    value per request would be a fresh allowance each time.
    """
    address = request.client.host if request.client else "unknown"
    salt = os.environ.get("RATE_LIMIT_SALT", "homesol")
    return hashlib.sha256(f"{salt}:{address}".encode()).hexdigest()[:20]


limiter = Limiter()


def limit(kind_name: str):
    """A route dependency that counts the request against `kind_name`'s allowances."""
    KINDS[kind_name]  # fail at import time on a typo, not on the first request

    def check(request: Request) -> None:
        limiter.check(kind_name, visitor_of(request))

    return Depends(check)
