import json
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from . import detect, finance, policy  # noqa: E402

app = FastAPI(title="homesol")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("ALLOWED_ORIGINS", "http://localhost:3000,https://localhost:3000").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


class FinanceRequest(BaseModel):
    system_kw: float = Field(gt=0)
    monthly_generation: list[float] = Field(min_length=12, max_length=12)
    monthly_usage: float = Field(gt=0)
    discom_id: str | None = None
    monthly_bill: float | None = Field(default=None, gt=0)
    quoted_cost: float | None = Field(default=None, gt=0)


class ChatTurn(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    text: str


class AdviseRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    #: The household's survey as shown on the dashboard.
    survey: dict
    history: list[ChatTurn] = Field(default_factory=list, max_length=20)


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.get("/policy")
def get_policy(state: str | None = None) -> dict:
    """Supported distributors, the one matching `state` if any, and the central subsidy."""
    data = policy.load()
    return {
        "as_of": data["as_of"],
        "matched": policy.discom_for_state(state),
        "central_subsidy": data["central_subsidy"],
        "discoms": {key: {"name": d["name"], "state": d["state"], "net_metering": d["net_metering"]} for key, d in data["discoms"].items()},
    }


@app.post("/finance")
def post_finance(req: FinanceRequest) -> dict:
    if req.discom_id and not policy.get_discom(req.discom_id):
        raise HTTPException(404, f"No data for distributor '{req.discom_id}'.")
    try:
        return finance.estimate(**req.model_dump()).to_dict()
    except ValueError as err:
        raise HTTPException(422, str(err)) from err


@app.post("/detect")
def post_detect(req: detect.DetectRequest) -> dict:
    from botocore.exceptions import BotoCoreError, ClientError

    try:
        return {"obstructions": [o.model_dump() for o in detect.detect(req)]}
    except detect.DetectionError as err:
        raise HTTPException(502, str(err)) from err
    except (ClientError, BotoCoreError) as err:
        raise HTTPException(502, f"The vision model is unavailable: {err}") from err


@app.post("/advise")
def post_advise(req: AdviseRequest) -> dict:
    from botocore.exceptions import BotoCoreError, ClientError

    from .agents import baseline_finances, build_advisor

    transcript = "".join(f"{'Household' if t.role == 'user' else 'You'}: {t.text}\n" for t in req.history)
    prompt = (
        f"The household's survey, as JSON:\n{json.dumps(req.survey)}\n\n"
        f"Finances already calculated for the recommended system:\n{json.dumps(baseline_finances(req.survey))}\n\n"
        + (f"The conversation so far:\n{transcript}\n" if transcript else "")
        + f"The household asks: {req.question}"
    )
    try:
        result = build_advisor(req.survey)(prompt)
    except (ClientError, BotoCoreError) as err:
        raise HTTPException(502, f"The advisor's model is unavailable: {err}") from err
    return {"answer": str(result).strip()}
