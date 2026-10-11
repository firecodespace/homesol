"""Ask the real advisor one question and record what happened inside.

Nothing is rebuilt here. `homesol.agents.answer` is called directly: the same
call the web API makes, with the same survey JSON, question and history. To see
inside, two names in `homesol.agents` are replaced at runtime (nothing on disk
changes):

- `Agent` gets a hook that logs every tool call and every model call made by
  the advisor and by its two specialists;
- `build_advisor` is wrapped so the advisor's AgentResult (token usage, stop
  reason) can be kept.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")  # the same file the server loads; values already set in the shell win

from homesol import agents  # noqa: E402  (after the environment is loaded: it reads its model ids on import)
from strands.hooks import AfterInvocationEvent, AfterModelCallEvent, AfterToolCallEvent, BeforeToolCallEvent, HookProvider, HookRegistry  # noqa: E402

_local = threading.local()
_RealAgent = agents.Agent
_real_build_advisor = agents.build_advisor


class _Recorder(HookProvider):
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.model_calls: dict[str, int] = {}
        self.model_errors: list[str] = []
        self.usage: dict[str, dict] = {}
        self.result = None
        self._started: dict[str, float] = {}
        self._lock = threading.Lock()

    def register_hooks(self, registry: HookRegistry, **kwargs) -> None:
        registry.add_callback(BeforeToolCallEvent, self._before_tool)
        registry.add_callback(AfterToolCallEvent, self._after_tool)
        registry.add_callback(AfterModelCallEvent, self._after_model)
        registry.add_callback(AfterInvocationEvent, self._after_invocation)

    def _before_tool(self, event: BeforeToolCallEvent) -> None:
        with self._lock:
            self._started[event.tool_use.get("toolUseId", "")] = time.monotonic()

    def _after_tool(self, event: AfterToolCallEvent) -> None:
        use, result = event.tool_use, event.result
        if isinstance(result, dict):
            output = "".join(block.get("text", "") for block in result.get("content", []) if isinstance(block, dict))
            status = result.get("status")
        else:
            output, status = repr(result), "error"
        with self._lock:
            started = self._started.pop(use.get("toolUseId", ""), None)
            self.calls.append(
                {
                    "tool": use.get("name"),
                    "input": use.get("input"),
                    "status": status,
                    "output": output,
                    "seconds": round(time.monotonic() - started, 2) if started else None,
                }
            )

    def _after_model(self, event: AfterModelCallEvent) -> None:
        name = getattr(event.agent, "name", None) or "agent"
        with self._lock:
            self.model_calls[name] = self.model_calls.get(name, 0) + 1
            if event.exception is not None:  # throttling shows up here; Strands then waits and retries
                self.model_errors.append(f"{name}: {type(event.exception).__name__}")

    def _after_invocation(self, event: AfterInvocationEvent) -> None:
        metrics = getattr(event.result, "metrics", None)
        invocations = getattr(metrics, "agent_invocations", None) or []
        # A specialist consulted twice keeps one running total, so take this invocation's own count when there is one.
        usage = invocations[-1].usage if invocations else getattr(metrics, "accumulated_usage", None)
        if usage:
            name = getattr(event.agent, "name", None) or "agent"
            with self._lock:
                total = self.usage.setdefault(name, {})
                for key, value in dict(usage).items():
                    if isinstance(value, (int, float)):
                        total[key] = total.get(key, 0) + value


def _recording_agent(*args, **kwargs):
    recorder = getattr(_local, "recorder", None)
    if recorder is not None:
        kwargs["hooks"] = [*(kwargs.get("hooks") or []), recorder]
    return _RealAgent(*args, **kwargs)


def _recording_build_advisor(survey: dict, history: list[dict] | None = None):
    advisor = _real_build_advisor(survey, history)
    recorder = getattr(_local, "recorder", None)
    if recorder is None:
        return advisor

    def call(prompt: str):
        recorder.result = advisor(prompt)
        return recorder.result

    return call


agents.Agent = _recording_agent
agents.build_advisor = _recording_build_advisor


def settings() -> dict:
    """The models under test, as the advisor module read them from the environment."""
    return {
        "advisor_model_id": agents.ADVISOR_MODEL_ID,
        "advisor_effort": agents.ADVISOR_EFFORT,
        "specialist_model_id": agents.SPECIALIST_MODEL_ID,
        "specialist_effort": agents.SPECIALIST_EFFORT,
    }


def ask(survey: dict, question: str, history: list[dict] | None = None) -> dict:
    """One advisor turn. `history` is the conversation before it, as the web app sends it."""
    recorder = _Recorder()
    _local.recorder = recorder
    started = time.monotonic()
    out: dict = {"answer": None, "error": None}
    try:
        out["answer"] = agents.answer(question, survey, history or [])
    except Exception as err:  # noqa: BLE001 - a failed case is a result, not a crash
        out["error"] = f"{type(err).__name__}: {getattr(err, 'detail', None) or err}"
    finally:
        _local.recorder = None
    out["latency_s"] = round(time.monotonic() - started, 2)
    out["tool_calls"] = recorder.calls
    out["tools_called"] = [c["tool"] for c in recorder.calls]
    out["model_calls"] = recorder.model_calls
    out["model_errors"] = recorder.model_errors
    out["usage"] = recorder.usage
    out["model_id"] = agents.ADVISOR_MODEL_ID
    return out
