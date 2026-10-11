import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from homesol import limits
from homesol.main import app as homesol_app


class Clock:
    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock(monkeypatch):
    """A fresh in-memory limiter with small allowances and a clock 10 minutes into an hour."""
    c = Clock(1_800_000_000 + 600)
    monkeypatch.setattr(limits, "limiter", limits.Limiter(counter=limits.MemoryCounter(), clock=c))
    monkeypatch.setitem(limits.KINDS, "measure", limits.Kind("live measurements", 3, 5))
    return c


def client() -> FastAPI:
    app = FastAPI()

    @app.post("/paid", dependencies=[limits.limit("measure")])
    def paid() -> dict:
        return {"ok": True}

    return app


def call(app: FastAPI, ip: str, forwarded: str | None = None):
    """A request from `ip`, as Mangum reports the function URL's source address."""
    headers = {"x-forwarded-for": forwarded} if forwarded else {}
    return TestClient(app, client=(ip, 0)).post("/paid", headers=headers)


def test_each_visitor_gets_their_hourly_allowance_then_a_clear_429(clock):
    c = client()
    assert [call(c, "1.1.1.1").status_code for _ in range(3)] == [200, 200, 200]
    over = call(c, "1.1.1.1")
    assert over.status_code == 429
    detail = over.json()["detail"]
    assert detail["scope"] == "visitor" and detail["id"] == "measure" and detail["limit"] == 3 and detail["window"] == "hour"
    # Ten minutes into the hour: fifty minutes to wait, said in words and in seconds.
    assert detail["retry_after"] == 3000 and over.headers["retry-after"] == "3000"
    assert detail["message"] == "You've used this hour's 3 live measurements. You can carry on in 50 minutes."


def test_another_visitor_is_not_held_back_by_the_first(clock):
    c = client()
    for _ in range(4):
        call(c, "1.1.1.1")
    assert call(c, "2.2.2.2").status_code == 200


def test_the_allowance_comes_back_next_hour(clock):
    c = client()
    for _ in range(4):
        call(c, "1.1.1.1")
    clock.now += 3000
    assert call(c, "1.1.1.1").status_code == 200


def test_everyone_together_has_a_daily_cap(clock):
    c = client()
    codes = [call(c, f"9.9.9.{i}").status_code for i in range(6)]
    assert codes == [200] * 5 + [429]
    detail = call(c, "9.9.9.99").json()["detail"]
    assert detail["scope"] == "everyone" and detail["window"] == "day"
    assert "for all visitors" in detail["message"] and "midnight UTC" in detail["message"]


def test_a_failing_store_falls_back_to_counting_in_memory(monkeypatch):
    class Broken:
        def add(self, key, expires):
            raise RuntimeError("AccessDenied")

    monkeypatch.setitem(limits.KINDS, "measure", limits.Kind("live measurements", 1, 100))
    monkeypatch.setattr(limits, "limiter", limits.Limiter(counter=Broken()))
    c = client()
    assert call(c, "1.1.1.1").status_code == 200
    assert call(c, "1.1.1.1").status_code == 429


def test_visitors_are_told_apart_by_a_hash_never_the_address():
    from starlette.requests import Request

    visitor = limits.visitor_of(Request({"type": "http", "headers": [], "client": ("203.0.113.7", 0)}))
    assert "203.0.113.7" not in visitor and len(visitor) == 20
    assert limits.visitor_of(Request({"type": "http", "headers": [], "client": ("203.0.113.8", 0)})) != visitor


def test_a_made_up_forwarded_address_does_not_buy_a_fresh_allowance(clock):
    c = client()
    codes = [call(c, "1.1.1.1", forwarded=f"10.9.9.{i}").status_code for i in range(4)]
    assert codes == [200, 200, 200, 429]


PAID = {"/site": "measure", "/picture": "measure", "/site/names": "ai", "/bill": "ai", "/detect": "ai", "/advise": "ai", "/transcribe": "speech"}


def test_every_route_that_costs_money_is_limited_and_the_free_ones_are_not():
    limited = {route.path for route in homesol_app.routes if getattr(route, "dependencies", None)}
    assert limited == set(PAID)
