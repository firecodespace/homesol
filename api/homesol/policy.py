"""Curated subsidy, tariff and net-metering rules, keyed by DISCOM."""

import json
from functools import lru_cache
from pathlib import Path

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "policies.json"

STATE_TO_DISCOM = {
    "maharashtra": "msedcl",
    "delhi": "delhi",
    "nct of delhi": "delhi",
    "karnataka": "bescom",
    "gujarat": "gujarat",
}


@lru_cache
def load() -> dict:
    return json.loads(DATA_FILE.read_text())


def discom_for_state(state: str | None) -> str | None:
    return STATE_TO_DISCOM.get((state or "").strip().lower())


def get_discom(discom_id: str) -> dict | None:
    return load()["discoms"].get(discom_id)


def central_subsidy(system_kw: float) -> int:
    """PM Surya Ghar subsidy in rupees for a residential system of this size."""
    rules = load()["central_subsidy"]
    first = min(system_kw, 2) * rules["per_kw_first_2kw"]
    third = min(max(system_kw - 2, 0), 1) * rules["per_kw_third_kw"]
    return round(min(first + third, rules["max_total"]))


def surplus_rate(discom: dict, system_kw: float) -> float | None:
    """Rupees per unit the distributor pays for extra solar units, for a system of this size."""
    rate = discom["net_metering"]["surplus_rate"]
    if isinstance(rate, list):
        return next(band["rate"] for band in rate if band["up_to_kw"] is None or system_kw <= band["up_to_kw"])
    return rate
