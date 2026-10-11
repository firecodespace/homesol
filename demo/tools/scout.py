"""Finds a good demo property: taps candidate points through the local API and ranks what it finds.

    python scout.py <lng> <lat> [--grid 3 --step 60] [--api http://localhost:8000]

Taps a grid of points (metres apart) around a centre, the way a user taps a roof, and prints
each surface found: kind, area, floors, survey quality and what stands around it. Each tap is one
or two billed Google Solar requests, so keep grids small (3x3 is 9 taps).

A good demo roof: a flat residential roof, found by tap, HIGH or MEDIUM survey quality, 60-250 m²,
with two to five obstructions that cast real shade (a stair room or tank on it, a taller
neighbour or trees beside it), and still room for six or more panels.
"""

import json
import math
import sys
import urllib.request


def tap(api: str, lng: float, lat: float) -> dict:
    req = urllib.request.Request(f"{api}/site", data=json.dumps({"point": [lng, lat]}).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as res:
        return json.load(res)


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    opt = lambda name, default: type(default)(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default
    lng0, lat0 = float(args[0]), float(args[1])
    grid, step, api = opt("--grid", 3), opt("--step", 60.0), opt("--api", "http://localhost:8000")
    m_per_deg_lat = 111_320.0
    m_per_deg_lng = m_per_deg_lat * math.cos(math.radians(lat0))
    half = (grid - 1) / 2
    for i in range(grid):
        for j in range(grid):
            lng = lng0 + (j - half) * step / m_per_deg_lng
            lat = lat0 + (half - i) * step / m_per_deg_lat
            try:
                r = tap(api, lng, lat)
            except Exception as e:  # noqa: BLE001 - report and keep scouting
                print(f"{lng:.6f},{lat:.6f}  error {e}")
                continue
            if not r.get("available"):
                print(f"{lng:.6f},{lat:.6f}  no survey: {r.get('reason')}")
                continue
            if not r.get("found"):
                print(f"{lng:.6f},{lat:.6f}  nothing: {r.get('kind')}")
                continue
            s = r["surface"]
            obs = r.get("obstructions", [])
            on = sum(o["on_surface"] for o in obs)
            print(
                f"{lng:.6f},{lat:.6f}  {s['kind']:12s} {s.get('area_m2', 0):6.0f} m²  {s.get('floors')} floors  "
                f"quality {r.get('imagery_quality', '?'):6s} date {r.get('imagery_date', '?')}  "
                f"obstructions {len(obs)} ({on} on it): " + ", ".join(o["name"] for o in obs[:5])
            )


if __name__ == "__main__":
    main()
