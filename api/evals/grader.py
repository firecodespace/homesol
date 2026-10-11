"""Model-graded criteria: one narrow yes/no question per call.

These are judgement calls a regex cannot make. They are kept apart from the
deterministic checks in every output. The grader is never the model that wrote
the answer, because a model tends to be lenient about its own style: it is
Claude Opus 4.6, or Claude Sonnet 4.6 when the advisor itself is an Opus.
Set EVAL_GRADER_MODEL_ID to choose another.
"""

from __future__ import annotations

import json
import os
import re

import boto3

from homesol import agents

OPUS, SONNET = "us.anthropic.claude-opus-4-6-v1", "us.anthropic.claude-sonnet-4-6"
GRADER_MODEL_ID = os.environ.get("EVAL_GRADER_MODEL_ID") or (SONNET if "opus" in agents.ADVISOR_MODEL_ID else OPUS)

SYSTEM = (
    "You grade one reply from a chatbot that advises a household, anywhere in the world, about putting solar panels "
    "on their roof or land. You are given the household's question (with any earlier turns of the conversation), "
    "the chatbot's reply, and ONE criterion. "
    "Judge only that criterion, strictly and literally, ignoring everything else about the reply. "
    "The question and reply may be in English, Hindi, Hinglish (Hindi in Latin letters) or another language; "
    "judge them in whatever language they are in. "
    "Reply with one line of JSON and nothing else, reason first: "
    '{"reason": "<at most 30 words, in English, quoting the words of the reply you relied on>", "verdict": "yes" or "no"}'
)

CRITERIA = {
    "first_sentence_answers": (
        "Read ONLY the first sentence, quoted below. Does that sentence by itself give the household the answer "
        "to its question: a yes or no, the figure asked for, a plain statement of what the thing is or what to do, "
        "or a plain statement that the chatbot does not have, or cannot work out, what was asked? When the "
        "question asks two things, answering the first of them is enough. Say no if the first sentence is a greeting, a "
        "restatement of the question, or a lead-in such as 'Based on your survey' or 'Let me explain' with the "
        "answer only arriving later."
    ),
    "layperson_clear": (
        "Could an adult who has never dealt with solar panels or electricity tariffs follow this reply without "
        "looking anything up? Everyday words are fine: units, subsidy, kW, bill, savings, panel, vendor, quote. "
        "A term the household used in its own question is fine too. "
        "Look for two things. (a) Jargon. Go through these terms and their Hindi equivalents: net metering, kWh, "
        "kWp, DISCOM, tariff slab, inverter, feed-in tariff, wheeling charge, surplus credit, gross cost, net cost, "
        "payback period. For each one that appears in the reply, copy the words of the reply that tell the reader "
        "what it means (in brackets, after a dash or 'yaani', or in a nearby sentence). If the reply never says what "
        "it means, leave that empty. (b) Data dump: the reply is mostly a list of labelled fields such as "
        "'Gross Cost: ...', 'Surplus Credit: ...' rather than sentences a person would say. For THIS criterion use "
        "this JSON instead: "
        '{"terms": [{"term": "<copied exactly as it appears in the reply>", "explained_by": "<words copied from the reply, or empty>"}], '
        '"data_dump": true or false, "verdict": "yes" if every term has an explanation and data_dump is false, otherwise "no"}'
    ),
    "flags_unverified": (
        "The reply quotes a figure that rests on data homesol has not been able to confirm: the rate the electricity "
        "company pays for extra (surplus) units, or the tariff behind the savings. Does the reply tell the household "
        "that this rate or data is unverified, not yet confirmed, reported but not checked, or still needs "
        "confirming? A general 'this is an estimate', or advice to get a vendor quote or site visit, does NOT count."
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


def grade(question: str, answer: str, criterion: str, earlier: str = "") -> dict:
    """Ask the grader one yes/no question. Returns {"pass": bool | None, "reason": str}."""
    user = (
        (f"EARLIER IN THE CONVERSATION:\n{earlier}\n\n" if earlier else "")
        + f"QUESTION FROM THE HOUSEHOLD:\n{question}\n\nCHATBOT REPLY:\n{answer}\n\nCRITERION:\n{criterion}"
    )
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


def _layperson(question: str, answer: str, earlier: str = "") -> dict:
    result = grade(question, answer, CRITERIA["layperson_clear"], earlier)
    parsed = result.pop("parsed", {})
    if "terms" not in parsed:
        return result
    terms = [t for t in parsed.get("terms") or [] if isinstance(t, dict)]
    unexplained = [str(t.get("term", "")) for t in terms if not str(t.get("explained_by") or "").strip()]
    verdict = layperson_verdict(question, answer, unexplained, bool(parsed.get("data_dump")))
    explained = {str(t.get("term", "")): str(t["explained_by"]) for t in terms if str(t.get("explained_by") or "").strip()}
    return {**verdict, "reason": json.dumps({**json.loads(verdict["reason"]), "explained": explained}, ensure_ascii=False)}


def grade_case(case: dict, answer: str, unverified_applies: bool, history: list[dict] | None = None) -> dict:
    """All graded criteria that apply to this case. `answer` is the visible answer, leaked reasoning removed."""
    question = case["question"]
    earlier = "\n".join(f"{'Household' if turn['role'] == 'user' else 'Chatbot'}: {turn['text']}" for turn in history or [])
    out = {
        "first_sentence_answers": grade(
            question, answer, CRITERIA["first_sentence_answers"] + f'\n\nFIRST SENTENCE: "{first_sentence(answer)}"', earlier
        ),
        "layperson_clear": _layperson(question, answer, earlier),
    }
    if case.get("careful"):
        out["careful_handling"] = grade(question, answer, case["careful"], earlier)
    if unverified_applies:
        out["flags_unverified"] = grade(question, answer, CRITERIA["flags_unverified"], earlier)
    for result in out.values():
        result.pop("parsed", None)
    return out


GRADED = ["first_sentence_answers", "layperson_clear", "careful_handling", "flags_unverified"]
