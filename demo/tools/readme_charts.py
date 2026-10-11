"""The README's model-pairing chart, drawn from the advisor test runs' own summaries.

    python3 demo/tools/readme_charts.py

Writes docs/images/model-pairings-light.svg and -dark.svg. One measure, median time to answer,
as bars; the share of automatic checks passed sits beside each bar as text, because on a 0-100%
scale the five pass rates (98-99%) would be five identical bars. Colours were checked with the
dataviz palette validator: light #855300/#cf9446 on #ffffff, dark #c7821a/#865710 on #0d1117.
"""

import json
import os
from xml.sax.saxutils import escape

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
RUNS = os.path.join(ROOT, "api", "evals", "runs")
OUT = os.path.join(ROOT, "docs", "images")

PAIRINGS = [  # (run, advisor, specialists, chosen)
    ("20261011-compare-nova-nova", "Nova Pro", "Nova Pro", False),
    ("20261011-compare-sonnet-sonnet", "Sonnet 4.6", "Sonnet 4.6", False),
    ("20261011-compare-opus-haiku", "Opus 4.6", "Haiku 4.5", False),
    ("20261011-compare-opus-sonnet", "Opus 4.6", "Sonnet 4.6", True),
    ("20261011-compare-opus-opus", "Opus 4.6", "Opus 4.6", False),
]

THEMES = {
    "light": {"ink": "#1f2328", "muted": "#59636e", "grid": "#d1d9e0", "chosen": "#855300", "other": "#cf9446"},
    "dark": {"ink": "#e6edf3", "muted": "#9198a1", "grid": "#30363d", "chosen": "#c7821a", "other": "#865710"},
}


def rows() -> list[dict]:
    out = []
    for run, advisor, specialists, chosen in PAIRINGS:
        s = json.load(open(os.path.join(RUNS, run, "summary.json")))
        d = s["deterministic_overall"]
        out.append({"label": f"{advisor} + {specialists}", "chosen": chosen, "median": s["latency_s"]["median"],
                    "passed": d["passed"], "scored": d["scored"], "cases": s["cases"]})
    return out


def bar(x: float, y: float, w: float, h: float, r: float = 4) -> str:
    """A bar square at the baseline with a 4 px rounded data end."""
    r = min(r, w, h / 2)
    return (f"M{x:.1f},{y:.1f} H{x + w - r:.1f} Q{x + w:.1f},{y:.1f} {x + w:.1f},{y + r:.1f} "
            f"V{y + h - r:.1f} Q{x + w:.1f},{y + h:.1f} {x + w - r:.1f},{y + h:.1f} H{x:.1f} Z")


def svg(theme: dict, data: list[dict]) -> str:
    W, left, plot_w, top, row_h, bar_h = 860, 230, 420, 92, 44, 20
    right = left + plot_w + 70
    xmax = 13.0
    sx = plot_w / xmax
    H = top + row_h * len(data) + 64
    font = "font-family=\"-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif\""
    p = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" {font}>',
         '<title>Median answer time and automatic checks passed for five advisor model pairings</title>',
         f'<text x="0" y="24" font-size="17" font-weight="600" fill="{theme["ink"]}">Five model pairings, the same {data[0]["cases"]} advisor questions</text>',
         f'<text x="0" y="46" font-size="13" fill="{theme["muted"]}">Median time to answer. Checks passed were within a percentage point of each other; the choice rested on the kind of failures.</text>',
         f'<text x="0" y="{top - 14}" font-size="12" font-weight="600" fill="{theme["muted"]}">Advisor + specialists</text>',
         f'<text x="{right}" y="{top - 14}" font-size="12" font-weight="600" fill="{theme["muted"]}">Checks passed</text>']
    # Hairline gridlines and their ticks, behind the bars.
    for t in range(0, 13, 4):
        x = left + t * sx
        p.append(f'<line x1="{x:.1f}" y1="{top - 4}" x2="{x:.1f}" y2="{top + row_h * len(data) - 8}" stroke="{theme["grid"]}" stroke-width="1"/>')
        p.append(f'<text x="{x:.1f}" y="{top + row_h * len(data) + 10}" font-size="12" text-anchor="middle" fill="{theme["muted"]}">{t} s</text>')
    for i, r in enumerate(data):
        y = top + i * row_h
        cy = y + bar_h / 2 + 4.5
        weight = "600" if r["chosen"] else "400"
        label = r["label"] + ("  (chosen)" if r["chosen"] else "")
        p.append(f'<text x="0" y="{cy:.1f}" font-size="13" font-weight="{weight}" fill="{theme["ink"]}">{escape(label)}</text>')
        w = r["median"] * sx
        p.append(f'<path d="{bar(left, y, w, bar_h)}" fill="{theme["chosen"] if r["chosen"] else theme["other"]}"><title>{escape(r["label"])}: median {r["median"]:.1f} s</title></path>')
        p.append(f'<text x="{left + w + 8:.1f}" y="{cy:.1f}" font-size="13" fill="{theme["ink"]}">{r["median"]:.1f} s</text>')
        rate = 100 * r["passed"] / r["scored"]
        p.append(f'<text x="{right}" y="{cy:.1f}" font-size="13" fill="{theme["ink"]}" style="font-variant-numeric:tabular-nums">{rate:.1f}%  <tspan fill="{theme["muted"]}">({r["passed"]}/{r["scored"]})</tspan></text>')
    p.append(f'<text x="0" y="{H - 8}" font-size="11" fill="{theme["muted"]}">Source: api/evals/runs/20261011-compare-*/summary.json. One run per question, on questions the prompts were tuned on.</text>')
    p.append("</svg>")
    return "\n".join(p)


def main() -> None:
    data = rows()
    os.makedirs(OUT, exist_ok=True)
    for name, theme in THEMES.items():
        path = os.path.join(OUT, f"model-pairings-{name}.svg")
        open(path, "w").write(svg(theme, data))
        print(path)


if __name__ == "__main__":
    main()
