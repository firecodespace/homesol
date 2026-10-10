"""Model-graded criteria: one narrow yes/no question per call.

These are judgement calls a regex cannot make. They are kept apart from the
deterministic checks in every output. The grader is the same Bedrock model the
advisor runs on unless EVAL_GRADER_MODEL_ID is set, which is a known weakness:
a model tends to be lenient about its own style.
"""

from __future__ import annotations

import json
import os
import re

import boto3

from homesol import agents

GRADER_MODEL_ID = os.environ.get("EVAL_GRADER_MODEL_ID") or agents.MODEL_ID

SYSTEM = (
    "You grade one reply from a chatbot that advises Indian households about rooftop solar. "
    "You are given the household's question, the chatbot's reply, and ONE criterion. "
    "Judge only that criterion, strictly and literally, ignoring everything else about the reply. "
    "The question and reply may be in English, Hindi or Hinglish; judge them in whatever language they are in. "
    "Reply with one line of JSON and nothing else, reason first: "
    '{"reason": "<at most 30 words, in English, quoting the words of the reply you relied on>", "verdict": "yes" or "no"}'
)

CRITERIA = {
    "first_sentence_answers": (
        "Read ONLY the first sentence, quoted below. Does that sentence by itself give the household the answer "
        "to its question: a yes or no, the figure asked for, a plain statement of what the thing is or what to do, "
        "or a plain statement that the chatbot cannot answer that? Say no if the first sentence is a greeting, a "
        "restatement of the question, or a lead-in such as 'Based on your survey' or 'Let me explain' with the "
        "answer only arriving later."
    ),
    "layperson_clear": (
        "Could an adult who has never dealt with solar panels or electricity tariffs follow this reply without "
        "looking anything up? Everyday words are fine: units, subsidy, kW, bill, savings, panel, vendor, quote. "
        "Look for two things. (a) Jargon: any of these terms, or its Hindi equivalent, used in the reply with no "
        "few-word explanation of what it means: net metering, kWh, kWp, DISCOM, tariff slab, inverter, feed-in "
        "tariff, wheeling charge, surplus credit, gross cost, net cost, payback period. (b) Data dump: the reply is "
        "mostly a list of labelled fields such as 'Gross Cost: ...', 'Surplus Credit: ...' rather than sentences a "
        "person would say. For THIS criterion use this JSON instead: "
        '{"unexplained_terms": [<each such term copied exactly as it appears in the reply>], "data_dump": true or false, '
        '"verdict": "yes" if the list is empty and data_dump is false, otherwise "no"}'
    ),
    "flags_unverified": (
        "Does the reply tell the household that the electricity price data behind its savings or payback figures "
        "is unverified, indicative, not yet checked or confirmed, or still needs checking against the regulator's "
        "order? A general 'this is an estimate', or advice to get a vendor quote or site visit, does NOT count."
    ),
}


def first_sentence(answer: str) -> str:
    text = answer.strip()
    m = re.search(r"(?<=[.!?।])\s|\n", text)
    return text[: m.start()].strip() if m else text


_client = None


def _bedrock():
    global _client
    if _client is None:
        _client = boto3.client("bedrock-runtime", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    return _client


def grade(question: str, answer: str, criterion: str) -> dict:
    """Ask the grader one yes/no question. Returns {"pass": bool | None, "reason": str}."""
    user = f"QUESTION FROM THE HOUSEHOLD:\n{question}\n\nCHATBOT REPLY:\n{answer}\n\nCRITERION:\n{criterion}"
    try:
        response = _bedrock().converse(
            modelId=GRADER_MODEL_ID,
            system=[{"text": SYSTEM}],
            messages=[{"role": "user", "content": [{"text": user}]}],
            inferenceConfig={"temperature": 0, "maxTokens": 700},
        )
        raw = "".join(block.get("text", "") for block in response["output"]["message"]["content"])
    except Exception as err:  # noqa: BLE001
        return {"pass": None, "reason": f"grader call failed: {type(err).__name__}: {err}"}
    verdict, reason, parsed = None, raw.strip(), {}
    found = re.search(r"\{.*\}", raw, re.S)
    if found:
        try:
            parsed = json.loads(found.group(0))
            verdict = str(parsed.get("verdict", "")).strip().lower()
            reason = str(parsed["reason"]) if "reason" in parsed else json.dumps({k: v for k, v in parsed.items() if k != "verdict"}, ensure_ascii=False)
        except json.JSONDecodeError:
            parsed = {}
    if verdict not in ("yes", "no"):
        loose = re.search(r'"verdict"\s*:\s*"(yes|no)"', raw, re.I)
        verdict = loose.group(1).lower() if loose else None
    return {"pass": None if verdict is None else verdict == "yes", "reason": reason, "parsed": parsed}


#: Only these count as jargon, whatever else the grader lists (it likes to add "kW", "subsidy" and "₹").
JARGON = (
    "net metering", "kwh", "kwp", "discom", "slab", "inverter", "feed-in", "wheeling", "surplus credit", "gross cost",
    "net cost", "payback", "tariff", "नेट मीटरिंग", "डिस्कॉम", "स्लैब", "इन्वर्टर", "व्हीलिंग", "अधिशेष", "पेबैक", "टैरिफ",
    "वापसी अवधि", "वापसी का समय",
)


def layperson_verdict(question: str, answer: str, listed: list[str], data_dump: bool) -> dict:
    """The grader only lists candidate jargon; this decides, so a term it imagined or an everyday word cannot fail a reply."""
    said, asked = answer.lower(), question.lower()
    real = [t for t in listed if t.lower() in said and t.lower() not in asked and any(j in t.lower() for j in JARGON)]
    return {
        "pass": not real and not data_dump,
        "reason": json.dumps({"unexplained_terms": real, "data_dump": data_dump, "listed_by_grader_but_not_counted": [t for t in listed if t not in real]}, ensure_ascii=False),
    }


def _layperson(question: str, answer: str) -> dict:
    result = grade(question, answer, CRITERIA["layperson_clear"])
    parsed = result.pop("parsed", {})
    if "unexplained_terms" not in parsed:
        return result
    return layperson_verdict(question, answer, [str(t) for t in parsed.get("unexplained_terms") or []], bool(parsed.get("data_dump")))


def grade_case(case: dict, answer: str, unverified_applies: bool) -> dict:
    """All graded criteria that apply to this case. `answer` is the visible answer, leaked reasoning removed."""
    question = case["question"]
    out = {
        "first_sentence_answers": grade(
            question, answer, CRITERIA["first_sentence_answers"] + f'\n\nFIRST SENTENCE: "{first_sentence(answer)}"'
        ),
        "layperson_clear": _layperson(question, answer),
    }
    if case.get("careful"):
        out["careful_handling"] = grade(question, answer, case["careful"])
    if unverified_applies:
        out["flags_unverified"] = grade(question, answer, CRITERIA["flags_unverified"])
    for result in out.values():
        result.pop("parsed", None)
    return out


GRADED = ["first_sentence_answers", "layperson_clear", "careful_handling", "flags_unverified"]
