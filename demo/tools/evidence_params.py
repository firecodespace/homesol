"""Builds the evidence card's parameters from the advisor test run's own summary file, verbatim."""
import json, sys
PATH = "api/evals/runs/20261011-final-opus-sonnet/summary.txt"
WANT = ["cases 81", "language_match", "money_figures_traceable", "figures_match_their_label",
        "what_if_recalculated", "no_leaked_reasoning", "ALL OF THE ABOVE"]
lines = open(sys.argv[1] if len(sys.argv) > 1 else PATH).read().splitlines()
# Each line is shown as an exact prefix of the file's line, cut where the per-language columns
# begin (found from the table's own header), so nothing is retyped.
header = next(l for l in lines if l.startswith("DETERMINISTIC CHECKS"))
cut = header.index(" n/a")
picked, seen = [], set()
for w in WANT:
    for l in lines:
        if l.startswith(w) and w not in seen:
            seen.add(w)
            picked.append(l if w == "cases 81" else l[:cut].rstrip())
            break
for shown in picked:
    assert any(l.startswith(shown) for l in lines), shown
print(json.dumps({
    "path": PATH,
    "lines": picked,
    "highlight": ["money_figures_traceable", "ALL OF THE ABOVE"],
    "stats": [["789 / 790", "automatic checks passed, on language, currency and every figure"],
              ["57 / 57", "answers with money in them: every amount traced back to the plan's own figures"],
              ["81 / 81", "answered in the language they were asked in: English, Hindi, Hinglish or German"]],
    "note": "One run per question, on the same questions the prompts were tuned on: a check of behaviour, not a held-out benchmark.",
}))
