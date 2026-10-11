"""The edit: which footage plays when, where each narration line lands, and every graphic.

    python build_timeline.py [--render] [--only scene,scene]

Writes demo_assets/timeline.json for assemble.py and demo_assets/edl.md (the edit, readable).
With --render, renders each graphic it needs (skipping ones already rendered with the same
parameters). Positions in footage come from the takes' marks; final times are computed here, and
the total is checked to be exactly 180 s.
"""

import hashlib
import json
import os
import subprocess
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..")
ASSETS = os.path.join(ROOT, "demo_assets")
GFX = os.path.join(ASSETS, "graphics")
DURATION = 180.0

WF = "raw/workflow/workflow_2.mkv"
HOOK = "raw/hook/hook_3.mkv"
CLOSE = "raw/close/close_1.mkv"
# The home's coordinates in the location card are blurred (output pixels).
PRIVATE = [[1122, 140, 296, 58]]

# (name, source, in, duration, dissolve into the next, extra)
SEGMENTS = [
    ("hook", HOOK, 1.15, 15.6, 0.6, {"push": [[0, 0, 1920, 1080], [72, 40, 1776, 999]]}),
    ("problem", "graphics/problem.mkv", 0, 25.6, 0.6, {}),
    ("reveal", "graphics/reveal.mkv", 0, 6.6, 0.6, {}),
    ("tap-and-measure", WF, 0.6, 33.3, 0.4, {"blur": PRIVATE}),
    ("shadows", WF, 34.8, 13.6, 0.4, {"blur": PRIVATE}),
    ("what-shades-it", WF, 48.6, 12.0, 0.4, {"blur": PRIVATE}),
    ("panels", WF, 62.9, 7.6, 0.4, {"blur": PRIVATE}),
    ("plan", WF, 71.8, 15.8, 0.4, {"blur": PRIVATE}),
    ("money", WF, 90.2, 12.6, 0.4, {"blur": PRIVATE}),
    ("ask", WF, 104.9, 8.6, 0.6, {"blur": PRIVATE}),
    ("answer", WF, 122.2, 9.6, 0.5, {"blur": PRIVATE}),
    ("evidence", "graphics/evidence.mkv", 0, 11.2, 0.4, {}),
    ("close-hero", CLOSE, 0.5, 7.0, 0.6, {"push": [[0, 0, 1920, 1080], [96, 54, 1728, 972]]}),
    ("end", "graphics/close.mkv", 0, 7.2, 0, {}),
]

# Narration: line id -> start time in the final film.
VOICE = {
    "v01": 0.9, "v02": 3.5, "v03": 7.6,
    "v04": 15.8, "v05": 19.2, "v06": 21.6, "v07": 23.6, "v08": 25.5, "v09": 29.4,
    "v10": 40.7,
    "v11": 46.3, "v12": 53.8, "v13": 67.3, "v14": 79.7, "v15": 95.2, "v16": 104.2,
    "v17": 111.4, "v18": 118.9, "v19": 133.0, "v20": 139.6, "v21": 148.6,
    "v22": 156.0, "v23": 166.8, "v24": 174.6,
}

PROBLEM_START = 15.0  # where the problem scene's own clock starts in the film
STATEMENT = "A measured roof, a year of shadows, a panel plan and <em>an honest price.</em> From one tap."
BUILT = "Built with <b>Strands Agents</b> · <b>Claude on Amazon Bedrock</b> · <b>AWS Lambda</b> · Google Solar API · NASA POWER"


def scenes() -> dict:
    """Every graphic: scene, seconds, alpha, parameters, and where overlays land in the film."""
    evidence = json.loads(subprocess.run([sys.executable, os.path.join(ROOT, "tools", "evidence_params.py"),
                                          os.path.join(ROOT, "..", "api", "evals", "runs", "20261011-final-opus-sonnet", "summary.txt")],
                                         capture_output=True, text=True, check=True).stdout)
    evidence["duration"] = 11.2
    v = VOICE
    rel = lambda t: round(t - PROBLEM_START - 0.2, 2)
    return {
        "hook_overlay": dict(scene="hook", seconds=15.6, alpha=True, at=0.0, p={"duration": 15.6, "lines": [0.7, 3.3, 7.4]}),
        "problem": dict(scene="problem", seconds=25.6, alpha=False, p={"duration": 25.6, "cards": [rel(v["v05"]), rel(v["v06"]), rel(v["v07"]), rel(v["v08"])], "today": rel(v["v09"])}),
        "reveal": dict(scene="reveal", seconds=6.6, alpha=False, p={"duration": 6.6}),
        "evidence": dict(scene="evidence", seconds=11.2, alpha=False, p=evidence),
        "close": dict(scene="close", seconds=7.2, alpha=False, p={"duration": 7.2, "statement": STATEMENT, "built": BUILT}),
        # Captions over the app sit at the top of the map, clear of the tooltips and the results.
        "lt_measured": dict(scene="lower", seconds=6.0, alpha=True, at=59.6,
                            p={"duration": 6.0, "kicker": "Measured, not guessed", "text": "The roof and everything that can shade it, <em>from Google's 3D height data.</em>", "at": [470, 160], "width": 880}),
        "lt_claude": dict(scene="lower", seconds=7.2, alpha=True, at=67.6,
                          p={"duration": 7.2, "kicker": "Claude on Amazon Bedrock", "text": "Names what the code measured. <em>It can't change a measurement.</em>", "at": [470, 160], "width": 880}),
        "lt_agent": dict(scene="lower", seconds=6.4, alpha=True, at=140.4,
                         p={"duration": 6.4, "kicker": "Strands Agents on Claude", "text": "An advisor whose tools are <em>bound to this plan.</em>", "at": [470, 160], "width": 880}),
        "co_causes": dict(scene="callout", seconds=4.4, alpha=True, at=95.6,
                          p={"duration": 4.4, "rect": [1438, 88, 452, 72], "label": "56% of the lost sun: one tree cluster", "dim": 0.32, "side": "left", "labelTop": 168}),
        "co_plan": dict(scene="callout", seconds=3.4, alpha=True, at=119.3,
                        p={"duration": 3.4, "rect": [1436, 92, 456, 282], "label": "Sized to this household's use", "dim": 0.3}),
        "co_sources": dict(scene="callout", seconds=3.0, alpha=True, at=135.7,
                           p={"duration": 3.0, "rect": [1468, 806, 424, 244], "label": "Where each figure came from", "dim": 0.3}),
    }


def render(name: str, s: dict) -> str:
    ext = "mov" if s["alpha"] else "mkv"
    params = json.dumps(s["p"], sort_keys=True)
    key = hashlib.sha1(f"{s['scene']}{s['seconds']}{params}{open(os.path.join(ROOT, 'graphics', s['scene'] + '.html')).read()}".encode()).hexdigest()[:10]
    out = os.path.join(GFX, f"{name}.{ext}")
    stamp = out + ".key"
    if os.path.exists(out) and os.path.exists(stamp) and open(stamp).read() == key:
        return out
    cmd = ["node", os.path.join(ROOT, "tools", "render.cjs"), s["scene"], str(s["seconds"]), out, "--p", params] + (["--alpha"] if s["alpha"] else [])
    subprocess.run(cmd, check=True, env={**os.environ, "NODE_PATH": subprocess.run(["npm", "root", "-g"], capture_output=True, text=True).stdout.strip()})
    open(stamp, "w").write(key)
    return out


def main() -> None:
    sc = scenes()
    if "--render" in sys.argv:
        only = sys.argv[sys.argv.index("--only") + 1].split(",") if "--only" in sys.argv else None
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(4) as pool:
            list(pool.map(lambda kv: render(*kv), [(k, v) for k, v in sc.items() if not only or k in only]))

    video, t, starts = [], 0.0, {}
    for name, src, cut_in, dur, fade, extra in SEGMENTS:
        starts[name] = round(t, 3)
        clip = {"src": src, "in": cut_in, "dur": dur, **({"xfade": fade} if fade else {}), **extra}
        video.append(clip)
        t += dur - fade
    if abs(t - DURATION) > 1e-6:
        raise SystemExit(f"segments add up to {t:.3f} s, not {DURATION}")

    durations = json.load(open(os.path.join(ASSETS, "audio", "vo", "durations.json")))
    lines = sorted(VOICE.items(), key=lambda kv: kv[1])
    for (a, ta), (b, tb) in zip(lines, lines[1:]):
        if ta + durations[a] > tb - 0.15:
            raise SystemExit(f"{a} ({ta} + {durations[a]} s) runs into {b} at {tb}")
    last = lines[-1]
    if last[1] + durations[last[0]] > DURATION - 1.0:
        raise SystemExit("the last line runs into the fade-out")

    overlays = [{"src": f"graphics/{k}.mov", "at": v["at"]} for k, v in sc.items() if v["alpha"]]
    timeline = {
        "duration": DURATION, "fps": 30, "video": video, "overlays": sorted(overlays, key=lambda o: o["at"]),
        "voice": [{"src": f"audio/vo/{k}.wav", "at": t} for k, t in lines],
        "music": "audio/music.wav",
    }
    json.dump(timeline, open(os.path.join(ASSETS, "timeline.json"), "w"), indent=1)

    said = {l["id"]: l["say"] for l in json.load(open(os.path.join(ASSETS, "audio", "lines.json")))}
    with open(os.path.join(ASSETS, "edl.md"), "w") as f:
        f.write("| Starts | Segment | Source | From | Length |\n|---|---|---|---|---|\n")
        for name, src, cut_in, dur, fade, extra in SEGMENTS:
            f.write(f"| {starts[name]:.1f} s | {name} | `{src}` | {cut_in} s | {dur} s |\n")
        f.write("\n| Line | At | Ends | Words |\n|---|---|---|---|\n")
        for k, tt in lines:
            f.write(f"| {k} | {tt:.1f} | {tt + durations[k]:.1f} | {said[k]} |\n")
        f.write("\n| Overlay | At | Length |\n|---|---|---|\n")
        for k, s in sc.items():
            if s["alpha"]:
                f.write(f"| {k} | {s['at']} | {s['seconds']} |\n")
    print(json.dumps(starts, indent=1))
    print(f"total {t:.3f} s; {len(lines)} lines; {len(overlays)} overlays")


if __name__ == "__main__":
    main()
