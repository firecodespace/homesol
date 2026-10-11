"""Which Bedrock model does which job, and how each may be called."""

import os

#: Reads pictures: names what the height data found, reads electricity bills.
VISION_MODEL_ID = os.environ.get("BEDROCK_VISION_MODEL_ID", "us.anthropic.claude-opus-4-6-v1")

#: Models that reject a request forcing one particular tool; they are asked to call it instead.
_NO_FORCED_TOOL = ("claude-opus-5-5", "claude-sonnet-5-5", "claude-fable-5-1")


def tool_choice(model_id: str, tool_name: str) -> dict:
    """The Converse `toolChoice` that makes this model answer through one tool."""
    if any(name in model_id for name in _NO_FORCED_TOOL):
        return {"auto": {}}
    return {"tool": {"name": tool_name}}
