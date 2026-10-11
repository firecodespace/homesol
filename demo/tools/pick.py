"""Turns pixel positions on a /picture photo into map points and taps each through the API.

    python pick.py <corners json> <image width> <image height> x1,y1 x2,y2 ...
"""
import json, sys, urllib.request

corners = json.loads(sys.argv[1])
w, h = float(sys.argv[2]), float(sys.argv[3])
(tl, tr, br, bl) = corners

def to_lnglat(x, y):
    u, v = x / w, y / h
    top = [tl[0] + (tr[0] - tl[0]) * u, tl[1] + (tr[1] - tl[1]) * u]
    bot = [bl[0] + (br[0] - bl[0]) * u, bl[1] + (br[1] - bl[1]) * u]
    return [top[0] + (bot[0] - top[0]) * v, top[1] + (bot[1] - top[1]) * v]

for arg in sys.argv[4:]:
    x, y = map(float, arg.split(","))
    lng, lat = to_lnglat(x, y)
    req = urllib.request.Request("http://localhost:8000/site", data=json.dumps({"point": [lng, lat]}).encode(), headers={"Content-Type": "application/json"})
    r = json.load(urllib.request.urlopen(req, timeout=120))
    if not r.get("found"):
        print(f"{arg:>9} -> {lng:.6f},{lat:.6f}  {r.get('kind') or r.get('reason')}")
        continue
    s = r["surface"]
    obs = r["obstructions"]
    print(f"{arg:>9} -> {lng:.6f},{lat:.6f}  {s['kind']} {s['area_m2']:.0f} m2, {s['floors']} floors, {r.get('imagery_quality')} {r.get('imagery_date')}, {len(obs)} obstructions ({sum(o['on_surface'] for o in obs)} on it): "
          + "; ".join(f"{o['name']} {o['height_above_m']}m{' ON' if o['on_surface'] else ''}" for o in obs[:6]))
