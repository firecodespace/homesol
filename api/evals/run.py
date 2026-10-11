"""Run the advisor eval.

    api/.venv/bin/python api/evals/run.py                 # full run: advisor + checks + grader
    api/.venv/bin/python api/evals/run.py --only mh-worth-en,dl-surplus-en
    api/.venv/bin/python api/evals/run.py --rescore api/evals/runs/<run>   # re-check saved answers, no model calls
    api/.venv/bin/python api/evals/run.py --rescore <run> --regrade        # also re-ask the grader

The models under test are read from the environment exactly as the server reads
them, so one configuration is compared with another by setting them for a run:

    BEDROCK_AGENT_MODEL_ID=us.anthropic.claude-sonnet-4-6 BEDROCK_AGENT_EFFORT=medium \
        api/.venv/bin/python api/evals/run.py --out api/evals/runs/sonnet-medium

A full run makes 86 advisor conversations (81 cases, five of them two-turn) and
about 210 short grader calls on Bedrock: roughly 5 minutes and 3 to 4 US dollars
with a Claude Opus 4.6 advisor. Results go to api/evals/runs/<timestamp>/:
results.jsonl (everything per case), summary.json, summary.txt and models.json
(which models answered and which one graded). Runs saved before 11 October 2026
used the old survey shape and cannot be re-scored with these checks.
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


def ask(survey: dict, question: str, history: list[dict]) -> dict:
    result = advisor.ask(survey, question, history)
    if result["error"] and any(word in result["error"].lower() for word in ("throttl", "too many", "timeout", "timed out")):
        time.sleep(20)
        result = advisor.ask(survey, question, history)
    return result


def run_case(case: dict, survey: dict, do_grade: bool) -> dict:
    record = {k: case[k] for k in ("id", "household", "lang", "type", "question")}
    record["truth"] = json.loads(json.dumps(checks.snapshot(case, survey)))  # the figures as they stand when the advisor is asked
    # A case with `earlier` questions is a real conversation: each is asked in turn and its actual answer becomes
    # the history of the next. Only the answer to the last question is scored.
    history: list[dict] = []
    earlier_calls: list[dict] = []
    record["earlier_turns"] = []
    for question in case.get("earlier", []):
        turn = ask(survey, question, history)
        record["earlier_turns"].append({k: turn[k] for k in ("answer", "error", "latency_s", "tools_called")} | {"question": question})
        if turn["error"]:
            record.update({"answer": None, "error": f"earlier turn failed: {turn['error']}", "latency_s": turn["latency_s"], "tools_called": []})
            score(record, case, survey, do_grade)
            return record
        earlier_calls += turn["tool_calls"]
        history += [{"role": "user", "text": question}, {"role": "assistant", "text": turn["answer"]}]
    record["history"] = history
    record.update(ask(survey, case["question"], history))
    record["earlier_tool_calls"] = earlier_calls
    score(record, case, survey, do_grade)
    print(f"  {case['id']:<28} {record['latency_s']:>6.1f}s  {'ERROR ' + record['error'] if record['error'] else ''}", flush=True)
    return record


def score(record: dict, case: dict, survey: dict, do_grade: bool) -> None:
    if record.get("error") or not record.get("answer"):
        record["checks"], record["graded"] = {}, {}
        return
    # Figures a recalculation returned in an earlier turn of the same conversation are still fair to quote.
    calls = [*(record.get("earlier_tool_calls") or []), *(record.get("tool_calls") or [])]
    record["checks"] = checks.run_all(case, survey, record["answer"], calls, record["truth"])
    if do_grade:
        applies = record["checks"]["unverified_data_flagged"]["pass"] is not None
        visible = checks.visible_answer(record["answer"])
        record["graded"] = grader.grade_case(case, visible, applies, record.get("history"))
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

    def overall(group: str, names: list[str]) -> dict:
        results = [r[group][name]["pass"] for r in ok for name in names if name in r.get(group, {})]
        scored = [x for x in results if x is not None]
        return {"passed": sum(scored), "scored": len(scored), "rate": round(sum(scored) / len(scored), 4) if scored else None}

    ok = [r for r in records if not r.get("error")]
    latencies = sorted(r["latency_s"] for r in ok)
    direct = sorted(r["latency_s"] for r in ok if not r["tools_called"])
    consulted = sorted(r["latency_s"] for r in ok if r["tools_called"])
    middle = lambda values: values[len(values) // 2] if values else None  # noqa: E731
    tokens: dict = {}
    for r in ok:
        for agent, usage in (r.get("usage") or {}).items():
            for key in ("inputTokens", "outputTokens"):
                tokens.setdefault(agent, {}).setdefault(key, 0)
                tokens[agent][key] += usage.get(key, 0)
    return {
        "cases": len(records),
        "answered": len(ok),
        "errored": [{"id": r["id"], "error": r["error"]} for r in records if r.get("error")],
        "latency_s": {
            "median": middle(latencies),
            "p90": latencies[int(len(latencies) * 0.9)],
            "max": latencies[-1],
            "mean": round(sum(latencies) / len(latencies), 2),
            "median_answered_from_the_facts": middle(direct),
            "median_with_a_specialist": middle(consulted),
        }
        if latencies
        else None,
        "tools": {
            name: sum(1 for r in ok if name in r["tools_called"])
            for name in ("site_analyst", "policy_finance_analyst", "lookup_policy", "estimate_finances")
        },
        "no_tool_called": [r["id"] for r in ok if not r["tools_called"]],
        "cases_with_a_model_error_retried": [r["id"] for r in ok if r.get("model_errors")],
        "tokens_by_agent": tokens,
        "deterministic_overall": overall("checks", checks.DETERMINISTIC),
        "graded_overall": overall("graded", grader.GRADED),
        "deterministic": rate("checks", checks.DETERMINISTIC, ok),
        "graded": rate("graded", grader.GRADED, ok),
        "deterministic_by_language": {lang: {n: v["rate"] for n, v in rate("checks", checks.DETERMINISTIC, [r for r in ok if r["lang"] == lang]).items()} for lang in LANGUAGES},
        "graded_by_language": {lang: {n: v["rate"] for n, v in rate("graded", grader.GRADED, [r for r in ok if r["lang"] == lang]).items()} for lang in LANGUAGES},
        "all_deterministic_checks_passed": sum(1 for r in ok if all(c["pass"] is not False for c in r["checks"].values())),
    }


def render(summary: dict, records: list[dict]) -> str:
    lines = []
    models = summary.get("models")
    if models:
        lines.append(
            f"advisor {models['advisor_model_id']} (effort {models['advisor_effort']})  "
            f"specialists {models['specialist_model_id']} (effort {models['specialist_effort']})  grader {models.get('grader_model_id')}"
        )
    lines.append(f"cases {summary['cases']}  answered {summary['answered']}  errored {len(summary['errored'])}")
    for e in summary["errored"]:
        lines.append(f"  ERROR {e['id']}: {e['error']}")
    if summary["latency_s"]:
        lat = summary["latency_s"]
        lines.append(
            f"latency  median {lat['median']}s  p90 {lat['p90']}s  max {lat['max']}s  mean {lat['mean']}s  "
            f"(median answered from the facts {lat['median_answered_from_the_facts']}s, with a specialist {lat['median_with_a_specialist']}s)"
        )
    lines.append("cases calling each tool: " + ", ".join(f"{k} {v}" for k, v in summary["tools"].items()) + f"; none at all {len(summary['no_tool_called'])}")
    if summary["cases_with_a_model_error_retried"]:
        lines.append(f"cases where a model call failed and was retried (their latency includes the wait): {', '.join(summary['cases_with_a_model_error_retried'])}")
    lines.append(f"cases passing every deterministic check: {summary['all_deterministic_checks_passed']}/{summary['answered']}")
    for title, key in (("DETERMINISTIC CHECKS", "deterministic"), ("MODEL-GRADED CRITERIA", "graded")):
        total = summary[f"{key}_overall"]
        lines += ["", f"{title:<28}{'pass':>10}{'rate':>7}{'n/a':>5}  " + "".join(f"{lang[:5]:>6}" for lang in LANGUAGES)]
        for name, row in summary[key].items():
            by = summary[f"{key}_by_language"]
            cells = "".join(f"{'-' if by[lang][name] is None else format(by[lang][name], '.0%'):>6}" for lang in LANGUAGES)
            rate = "-" if row["rate"] is None else format(row["rate"], ".0%")
            lines.append(f"{name:<28}{str(row['passed']) + '/' + str(row['scored']):>10}{rate:>7}{row['not_applicable']:>5}  {cells}")
        if total["scored"]:
            lines.append(f"{'ALL OF THE ABOVE':<28}{str(total['passed']) + '/' + str(total['scored']):>10}{format(total['rate'], '.1%'):>7}")
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


#: Languages a case may be in. Anything but the first three is judged by its everyday words (see checks.check_language).
LANGUAGES = ("en", "hi", "hinglish", "de")


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
    models_file = out / "models.json"
    if not args.rescore:
        models_file.write_text(json.dumps({**advisor.settings(), "grader_model_id": None if args.no_grade else grader.GRADER_MODEL_ID}, indent=1))
    models = json.loads(models_file.read_text()) if models_file.exists() else None
    if models and args.regrade:
        models["grader_model_id"] = grader.GRADER_MODEL_ID
        models_file.write_text(json.dumps(models, indent=1))
    summary = {"models": models, "code_under_test": json.loads(code_file.read_text()) if code_file.exists() else None, **summary}
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1))
    text = render(summary, records)
    (out / "summary.txt").write_text(text + "\n")
    print("\n" + text)
    print(f"\nfull answers and per-check detail: {out / 'results.jsonl'}")


if __name__ == "__main__":
    main()
