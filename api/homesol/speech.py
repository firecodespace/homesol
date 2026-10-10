"""Speech to text for English and Hindi, using Amazon Transcribe streaming."""

import asyncio
import os

from amazon_transcribe.client import TranscribeStreamingClient

SAMPLE_RATE = 16_000
LANGUAGES = ["en-IN", "hi-IN"]
#: Bytes per chunk sent to Transcribe: 100 ms of 16-bit mono audio.
CHUNK = SAMPLE_RATE * 2 // 10
MAX_SECONDS = 60


class SpeechError(Exception):
    pass


async def transcribe(pcm: bytes, language: str | None = None) -> dict:
    """
    Transcribe a short clip of 16 kHz, 16-bit, mono PCM audio.

    With no `language`, Transcribe picks between Indian English and Hindi.
    Returns the text and the language it was heard as.
    """
    if len(pcm) > MAX_SECONDS * SAMPLE_RATE * 2:
        raise SpeechError(f"Recordings can be at most {MAX_SECONDS} seconds.")
    if language is not None and language not in LANGUAGES:
        raise SpeechError(f"Unsupported language '{language}'.")

    client = TranscribeStreamingClient(region=os.environ.get("AWS_REGION", "us-east-1"))
    options = (
        {"language_code": language}
        if language
        else {"language_code": None, "identify_language": True, "language_options": LANGUAGES}
    )
    stream = await client.start_stream_transcription(
        media_sample_rate_hz=SAMPLE_RATE, media_encoding="pcm", **options
    )

    async def send() -> None:
        for start in range(0, len(pcm), CHUNK):
            await stream.input_stream.send_audio_event(audio_chunk=pcm[start : start + CHUNK])
        await stream.input_stream.end_stream()

    parts: list[str] = []
    heard = language

    async def receive() -> None:
        nonlocal heard
        async for event in stream.output_stream:
            for result in event.transcript.results:
                if result.is_partial or not result.alternatives:
                    continue
                parts.append(result.alternatives[0].transcript)
                heard = getattr(result, "language_code", None) or heard

    await asyncio.gather(send(), receive())
    return {"text": " ".join(parts).strip(), "language": heard}
