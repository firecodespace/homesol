import base64
import binascii
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from . import bill, detect, feedback, finance, google_solar, naming, policy, site, speech, surveys  # noqa: E402

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
    sanctioned_load_kw: float | None = Field(default=None, gt=0, le=100)
    country_code: str = Field(default="IN", min_length=2, max_length=2)
    currency: str = Field(default="INR", min_length=3, max_length=3)


class ChatTurn(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    text: str


class AdviseRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    #: The household's survey as shown on the dashboard.
    survey: dict
    history: list[ChatTurn] = Field(default_factory=list, max_length=20)


class TranscribeRequest(BaseModel):
    #: Base64 of 16 kHz, 16-bit, mono PCM audio.
    audio: str = Field(min_length=100)
    language: str | None = None


class SiteRequest(BaseModel):
    #: A tapped point as [lng, lat], to find the roof under it...
    point: tuple[float, float] | None = None
    #: ...or a hand-drawn outline as [lng, lat] pairs, to model what is inside it.
    outline: list[tuple[float, float]] | None = Field(default=None, min_length=3, max_length=80)


class RoofAtRequest(BaseModel):
    lng: float = Field(ge=-180, le=180)
    lat: float = Field(ge=-90, le=90)


class SaveSurveyRequest(BaseModel):
    survey: dict


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


@app.post("/transcribe")
async def post_transcribe(req: TranscribeRequest) -> dict:
    try:
        pcm = base64.b64decode(req.audio, validate=True)
    except binascii.Error as err:
        raise HTTPException(422, "Audio is not valid base64.") from err
    try:
        return await speech.transcribe(pcm, req.language)
    except speech.SpeechError as err:
        raise HTTPException(422, str(err)) from err
    except Exception as err:  # the Transcribe SDK raises its own unrelated error types
        raise HTTPException(502, f"Speech recognition is unavailable: {err}") from err


@app.post("/surveys")
def post_survey(req: SaveSurveyRequest) -> dict:
    try:
        return {"code": surveys.save(req.survey)}
    except surveys.SurveyTooLarge as err:
        raise HTTPException(413, "This survey is too large to save.") from err


@app.get("/surveys/{code}")
def get_survey(code: str) -> dict:
    survey = surveys.load(code)
    if survey is None:
        raise HTTPException(404, "No saved survey with that code. It may have expired.")
    return {"survey": survey}


@app.post("/site")
def post_site(req: SiteRequest) -> dict:
    """
    A measured model of one property: its surface, obstructions, and height and sunlight rasters.

    `available: false` means Google has no survey there; `found: false` means the tapped point is
    not a roof, with `kind` saying what it is instead.
    """
    try:
        if req.outline:
            return {"available": True, **site.from_outline(req.outline)}
        if req.point:
            return {"available": True, **site.from_tap(*req.point)}
    except google_solar.SolarDataUnavailable as err:
        return {"available": False, "reason": str(err)}
    except Exception as err:  # network and decoding failures must not break the survey
        return {"available": False, "reason": f"Google's data could not be read: {err}"}
    raise HTTPException(422, "Give a point or an outline.")


@app.post("/site/names")
def post_site_names(req: naming.NamingRequest) -> dict:
    """What each measured obstruction is, as seen in the photo. Empty when the model cannot be reached."""
    from botocore.exceptions import BotoCoreError, ClientError

    try:
        return {"items": [n.model_dump() for n in naming.name_obstructions(req)]}
    except (ClientError, BotoCoreError) as err:
        return {"items": [], "reason": str(err)}


@app.post("/picture")
def post_picture(req: RoofAtRequest) -> dict:
    """Google's photo of the area around a point, so taps land on the imagery the measurements use."""
    try:
        return {"available": True, "picture": google_solar.area_picture(req.lng, req.lat)}
    except google_solar.SolarDataUnavailable as err:
        return {"available": False, "reason": str(err)}
    except Exception as err:
        return {"available": False, "reason": f"Google's data could not be read: {err}"}


@app.post("/bill")
def post_bill(req: bill.BillRequest) -> dict:
    from botocore.exceptions import BotoCoreError, ClientError

    try:
        return bill.read_bill(req).model_dump()
    except bill.BillError as err:
        raise HTTPException(422, str(err)) from err
    except (ClientError, BotoCoreError) as err:
        raise HTTPException(502, f"The bill reader is unavailable: {err}") from err


@app.post("/detect")
def post_detect(req: detect.DetectRequest) -> dict:
    from botocore.exceptions import BotoCoreError, ClientError

    try:
        found = [o.model_dump() for o in detect.detect(req)]
    except detect.DetectionError as err:
        raise HTTPException(502, str(err)) from err
    except (ClientError, BotoCoreError) as err:
        raise HTTPException(502, f"The vision model is unavailable: {err}") from err
    detection_id = feedback.record_run(detect.MODEL_ID, req.model_dump(exclude={"image"}), found)
    return {"detection_id": detection_id, "obstructions": found}


@app.post("/feedback")
def post_feedback(verdict: feedback.Verdict) -> dict:
    feedback.record_verdict(verdict)
    return {"ok": True}


@app.get("/feedback/summary")
def get_feedback_summary() -> dict:
    return feedback.summary()


@app.post("/advise")
def post_advise(req: AdviseRequest) -> dict:
    from botocore.exceptions import BotoCoreError, ClientError

    from .agents import build_advisor, clean_answer, fact_sheet

    transcript = "".join(f"{'Household' if t.role == 'user' else 'You'}: {t.text}\n" for t in req.history)
    prompt = (
        f"This household's facts:\n{fact_sheet(req.survey)}\n\n"
        + (f"The conversation so far:\n{transcript}\n" if transcript else "")
        + f"The household asks: {req.question}"
    )
    try:
        result = build_advisor(req.survey)(prompt)
    except (ClientError, BotoCoreError) as err:
        raise HTTPException(502, f"The advisor's model is unavailable: {err}") from err
    return {"answer": clean_answer(str(result))}
