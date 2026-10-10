"""Run the advisor eval.

    api/.venv/bin/python api/evals/run.py                 # full run: advisor + checks + grader
    api/.venv/bin/python api/evals/run.py --only mh-worth-en,dl-surplus-en
    api/.venv/bin/python api/evals/run.py --rescore api/evals/runs/<run>   # re-check saved answers, no model calls
    api/.venv/bin/python api/evals/run.py --rescore <run> --regrade        # also re-ask the grader

A full run makes roughly 44 advisor conversations and 120 short grader calls on
Bedrock. Results go to api/evals/runs/<timestamp>/: results.jsonl (everything
per case), summary.json and summary.txt.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from evals import advisor  # noqa: E402  (first: it loads api/.env)
from evals import checks, grader  # noqa: E402


def run_case(case: dict, survey: dict, do_grade: bool) -> dict:
    record = {k: case[k] for k in ("id", "household", "lang", "type", "question")}
    record["truth"] = json.loads(json.dumps(checks.snapshot(case, survey)))  # the figures as they stand when the advisor is asked
    result = advisor.ask(survey, case["question"])
    if result["error"] and any(word in result["error"].lower() for word in ("throttl", "too many", "timeout", "timed out")):
        time.sleep(20)
        result = advisor.ask(survey, case["question"])
    record.update(result)
    score(record, case, survey, do_grade)
    print(f"  {case['id']:<26} {record['latency_s']:>6.1f}s  {'ERROR ' + record['error'] if record['error'] else ''}", flush=True)
    return record


def score(record: dict, case: dict, survey: dict, do_grade: bool) -> None:
    if record.get("error") or not record.get("answer"):
        record["checks"], record["graded"] = {}, {}
        return
    record["checks"] = checks.run_all(case, survey, record["answer"], record.get("tool_calls") or [], record["truth"])
    if do_grade:
        applies = record["checks"]["unverified_data_flagged"]["pass"] is not None
        visible = checks.visible_answer(record["answer"])
        record["graded"] = grader.grade_case(case, visible, applies)
        record["grader_model_id"] = grader.GRADER_MODEL_ID
    else:
        record.setdefault("graded", {})


def code_version() -> dict:
    """Which advisor was tested: commit, uncommitted files under api/, and hashes of the files that decide its answers."""
    import hashlib
    import subprocess

    api = HERE.parent

    def git(*cmd: str) -> str:
        try:
            return subprocess.run(["git", *cmd], cwd=api, capture_output=True, text=True, timeout=10).stdout.strip()
        except OSError:
            return ""

    files = ["homesol/agents.py", "homesol/finance.py", "homesol/policy.py", "homesol/main.py", "data/policies.json"]
    return {
        "git_commit": git("rev-parse", "--short", "HEAD"),
        "uncommitted_under_api": [line for line in git("status", "--short", "--", ".").splitlines() if "evals/" not in line],
        "sha256": {f: hashlib.sha256((api / f).read_bytes()).hexdigest()[:16] for f in files if (api / f).exists()},
        "note": "Read when the run starts. If these files are edited while a run is in progress, the run still uses what was loaded at the start.",
    }


def regraded_offline(graded: dict, record: dict, case: dict) -> dict:
    """Keep saved grader verdicts, re-applying only the parts that are decided by code."""
    graded = dict(graded)
    graded.pop("figures_mean_what_they_say", None)  # dropped: it passed answers with plainly wrong figures
    if record.get("checks", {}).get("unverified_data_flagged", {}).get("pass") is None:
        graded.pop("flags_unverified", None)
    lay = graded.get("layperson_clear")
    if lay:
        try:
            said = json.loads(lay["reason"])
            listed = [*said.get("unexplained_terms", []), *said.get("dropped_not_in_reply_or_used_by_household", []), *said.get("listed_by_grader_but_not_counted", [])]
            graded["layperson_clear"] = grader.layperson_verdict(case["question"], checks.visible_answer(record["answer"]), listed, bool(said.get("data_dump")))
        except (ValueError, AttributeError):
            pass
    return graded


def summarise(records: list[dict]) -> dict:
    def rate(group: str, names: list[str], subset: list[dict]) -> dict:
        table = {}
        for name in names:
            results = [r[group][name]["pass"] for r in subset if name in r.get(group, {})]
            scored = [x for x in results if x is not None]
            table[name] = {
                "passed": sum(scored),
                "scored": len(scored),
                "not_applicable": len(results) - len(scored),
                "rate": round(sum(scored) / len(scored), 3) if scored else None,
                "failed_ids": [r["id"] for r in subset if name in r.get(group, {}) and r[group][name]["pass"] is False],
            }
        return table

    ok = [r for r in records if not r.get("error")]
    latencies = sorted(r["latency_s"] for r in ok)
    return {
        "cases": len(records),
        "answered": len(ok),
        "errored": [{"id": r["id"], "error": r["error"]} for r in records if r.get("error")],
        "latency_s": {"median": latencies[len(latencies) // 2], "p90": latencies[int(len(latencies) * 0.9)], "max": latencies[-1]} if latencies else None,
        "tools": {
            name: sum(1 for r in ok if name in r["tools_called"])
            for name in ("site_analyst", "policy_finance_analyst", "lookup_policy", "estimate_finances")
        },
        "no_tool_called": [r["id"] for r in ok if not r["tools_called"]],
        "deterministic": rate("checks", checks.DETERMINISTIC, ok),
        "graded": rate("graded", grader.GRADED, ok),
        "deterministic_by_language": {lang: {n: v["rate"] for n, v in rate("checks", checks.DETERMINISTIC, [r for r in ok if r["lang"] == lang]).items()} for lang in ("en", "hi", "hinglish")},
        "graded_by_language": {lang: {n: v["rate"] for n, v in rate("graded", grader.GRADED, [r for r in ok if r["lang"] == lang]).items()} for lang in ("en", "hi", "hinglish")},
        "all_deterministic_checks_passed": sum(1 for r in ok if all(c["pass"] is not False for c in r["checks"].values())),
    }


def render(summary: dict, records: list[dict]) -> str:
    lines = [f"cases {summary['cases']}  answered {summary['answered']}  errored {len(summary['errored'])}"]
    for e in summary["errored"]:
        lines.append(f"  ERROR {e['id']}: {e['error']}")
    if summary["latency_s"]:
        lat = summary["latency_s"]
        lines.append(f"latency  median {lat['median']}s  p90 {lat['p90']}s  max {lat['max']}s")
    lines.append("cases calling each tool: " + ", ".join(f"{k} {v}" for k, v in summary["tools"].items()) + f"; none at all {len(summary['no_tool_called'])}")
    lines.append(f"cases passing every deterministic check: {summary['all_deterministic_checks_passed']}/{summary['answered']}")
    for title, key in (("DETERMINISTIC CHECKS", "deterministic"), ("MODEL-GRADED CRITERIA", "graded")):
        lines += ["", f"{title:<28}{'pass':>10}{'rate':>7}{'n/a':>5}   {'en':>5}{'hi':>6}{'hingl':>6}"]
        for name, row in summary[key].items():
            by = summary[f"{key}_by_language"]
            cells = "".join(f"{'-' if by[lang][name] is None else format(by[lang][name], '.0%'):>6}" for lang in ("en", "hi", "hinglish"))
            rate = "-" if row["rate"] is None else format(row["rate"], ".0%")
            lines.append(f"{name:<28}{str(row['passed']) + '/' + str(row['scored']):>10}{rate:>7}{row['not_applicable']:>5}  {cells}")
    lines += ["", "FAILURES"]
    for r in records:
        if r.get("error"):
            continue
        for group in ("checks", "graded"):
            for name, res in r.get(group, {}).items():
                if res["pass"] is False:
                    detail = res.get("detail", res.get("reason"))
                    if isinstance(detail, dict):
                        detail = {k: v for k, v in detail.items() if k not in ("traced", "present", "calls") and v not in ([], None)}
                    lines.append(f"- {r['id']} [{'graded' if group == 'graded' else 'det'}] {name}: {json.dumps(detail, ensure_ascii=False)[:600]}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cases", default=str(HERE / "cases.json"))
    parser.add_argument("--only", help="comma-separated case ids")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--no-grade", action="store_true", help="skip the model-graded criteria")
    parser.add_argument("--rescore", help="a run directory: recompute the deterministic checks on its saved answers")
    parser.add_argument("--regrade", action="store_true", help="with --rescore, also call the grader again")
    parser.add_argument("--out", help="output directory (default: evals/runs/<timestamp>)")
    args = parser.parse_args()

    data = json.loads(Path(args.cases).read_text())
    cases = data["cases"]
    if args.only:
        wanted = set(args.only.split(","))
        cases = [c for c in cases if c["id"] in wanted]
    surveys = {name: h["survey"] for name, h in data["households"].items()}

    if args.rescore:
        out = Path(args.rescore)
        saved = {r["id"]: r for r in map(json.loads, (out / "results.jsonl").read_text().splitlines())}
        for case in cases:
            if case["id"] in saved:
                record = saved[case["id"]]
                kept = record.get("graded", {})
                score(record, case, surveys[case["household"]], args.regrade)
                if not args.regrade:
                    record["graded"] = regraded_offline(kept, record, case)
        records = list(saved.values())  # cases left out by --only keep their old scores
    else:
        out = Path(args.out) if args.out else HERE / "runs" / datetime.now().strftime("%Y%m%d-%H%M%S")
        out.mkdir(parents=True, exist_ok=True)
        print(f"running {len(cases)} cases with {args.workers} workers -> {out}", flush=True)
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            records = list(pool.map(lambda c: run_case(c, surveys[c["household"]], not args.no_grade), cases))

    (out / "results.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in records))
    summary = summarise(records)
    code_file = out / "code_version.json"
    if not args.rescore:
        code_file.write_text(json.dumps(code_version(), indent=1))
    summary = {"code_under_test": json.loads(code_file.read_text()) if code_file.exists() else None, **summary}
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1))
    text = render(summary, records)
    (out / "summary.txt").write_text(text + "\n")
    print("\n" + text)
    print(f"\nfull answers and per-check detail: {out / 'results.jsonl'}")


if __name__ == "__main__":
    main()
