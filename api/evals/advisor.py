"""Ask the real advisor one question and record what happened inside.

The prompt is not rebuilt here. `homesol.main.post_advise` is called directly,
so the survey JSON, the baseline finances and the question are assembled by the
same code the web app hits. To see inside, two names in `homesol.agents` are
replaced at runtime (nothing on disk changes):

- `Agent` gets a hook that logs every tool call made by the advisor and by its
  two specialists, with arguments and output;
- `build_advisor` is wrapped so the exact prompt and the AgentResult (token
  usage, stop reason) can be kept.
"""

from __future__ import annotations

import threading
import time

from homesol import main as app  # loads api/.env exactly as the server does
from homesol import agents
from strands.hooks import AfterToolCallEvent, HookProvider, HookRegistry

_local = threading.local()
_RealAgent = agents.Agent
_real_build_advisor = agents.build_advisor


class _Recorder(HookProvider):
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.prompt: str | None = None
        self.result = None
        self._lock = threading.Lock()

    def register_hooks(self, registry: HookRegistry, **kwargs) -> None:
        registry.add_callback(AfterToolCallEvent, self._after_tool)

    def _after_tool(self, event: AfterToolCallEvent) -> None:
        use, result = event.tool_use, event.result
        if isinstance(result, dict):
            output = "".join(block.get("text", "") for block in result.get("content", []) if isinstance(block, dict))
            status = result.get("status")
        else:
            output, status = repr(result), "error"
        with self._lock:
            self.calls.append({"tool": use.get("name"), "input": use.get("input"), "status": status, "output": output})


def _recording_agent(*args, **kwargs):
    recorder = getattr(_local, "recorder", None)
    if recorder is not None:
        kwargs["hooks"] = [*(kwargs.get("hooks") or []), recorder]
    return _RealAgent(*args, **kwargs)


def _recording_build_advisor(survey: dict):
    advisor = _real_build_advisor(survey)
    recorder = getattr(_local, "recorder", None)
    if recorder is None:
        return advisor

    def call(prompt: str):
        recorder.prompt = prompt
        recorder.result = advisor(prompt)
        return recorder.result

    return call


agents.Agent = _recording_agent
agents.build_advisor = _recording_build_advisor


def ask(survey: dict, question: str) -> dict:
    """One advisor turn with no history, as the first message in the chat window."""
    recorder = _Recorder()
    _local.recorder = recorder
    started = time.monotonic()
    out: dict = {"answer": None, "error": None}
    try:
        out["answer"] = app.post_advise(app.AdviseRequest(question=question, survey=survey))["answer"]
    except Exception as err:  # noqa: BLE001 - a failed case is a result, not a crash
        out["error"] = f"{type(err).__name__}: {getattr(err, 'detail', None) or err}"
    finally:
        _local.recorder = None
    out["latency_s"] = round(time.monotonic() - started, 2)
    out["prompt"] = recorder.prompt
    out["tool_calls"] = recorder.calls
    out["tools_called"] = [c["tool"] for c in recorder.calls]
    usage = getattr(getattr(recorder.result, "metrics", None), "accumulated_usage", None)
    out["advisor_usage"] = dict(usage) if usage else None
    out["model_id"] = agents.MODEL_ID
    return out
