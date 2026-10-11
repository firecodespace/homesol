"""Narration for the demo, generated locally with Kokoro-82M (Apache-2.0) through kokoro-onnx.

    python narrate.py lines.json out_dir [--voice af_heart] [--speed 1.0]

lines.json is a list of {"id": "vo_01", "say": "text to speak"}. `say` is written for the ear:
"home sol" for homesol, amounts in words ("one lakh twenty thousand rupees"), no symbols.
Writes out_dir/<id>.wav (24 kHz mono) and out_dir/durations.json, which the edit uses to place
each line.

Uses kokoro-v1.0.onnx and voices-v1.0.bin in demo/.models/ when present (kokoro-onnx's GitHub
release files); otherwise downloads the model and voice from Hugging Face
(onnx-community/Kokoro-82M-v1.0-ONNX).
"""

import json
import os
import sys

import numpy as np
import soundfile

MODELS = os.path.join(os.path.dirname(__file__), "..", ".models")
REPO = "onnx-community/Kokoro-82M-v1.0-ONNX"

# Phoneme corrections for Indian words English rules misread (respelling cannot reach these).
FIXES = {
    "sˈɜːɹɪə": "sˈuːɹjə",  # Surya: "SOOR-yuh", not "SUR-ee-uh"
}


def fetch(voice: str) -> tuple[str, str]:
    """The ONNX model and a voices file holding `voice`, downloaded on first use."""
    # kokoro-onnx's own release files, if already fetched (github.com/thewh1teagle/kokoro-onnx).
    model, voices = os.path.join(MODELS, "kokoro-v1.0.onnx"), os.path.join(MODELS, "voices-v1.0.bin")
    if os.path.exists(model) and os.path.exists(voices):
        return model, voices
    from huggingface_hub import hf_hub_download

    os.makedirs(MODELS, exist_ok=True)
    model = hf_hub_download(REPO, "onnx/model.onnx", local_dir=MODELS)
    raw = hf_hub_download(REPO, f"voices/{voice}.bin", local_dir=MODELS)
    # kokoro-onnx reads voices as a NumPy archive of (positions, 1, 256) style vectors.
    voices = os.path.join(MODELS, f"voices-{voice}.npz")
    if not os.path.exists(voices):
        np.savez(voices, **{voice: np.fromfile(raw, dtype=np.float32).reshape(-1, 1, 256)})
    return model, voices


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    opt = lambda name, default: sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default
    voice, speed = opt("--voice", "af_heart"), float(opt("--speed", "1.0"))
    lines = json.load(open(args[0]))
    out = args[1]
    os.makedirs(out, exist_ok=True)

    from kokoro_onnx import Kokoro

    model, voices = fetch(voice)
    tts = Kokoro(model, voices)
    durations = {}
    for line in lines:
        # Speak from phonemes, so words the English rules get wrong can be corrected (see FIXES).
        phonemes = tts.tokenizer.phonemize(line["say"], "en-us")
        for wrong, right in FIXES.items():
            phonemes = phonemes.replace(wrong, right)
        audio, sr = tts.create(phonemes, voice=voice, speed=line.get("speed", speed), lang="en-us", is_phonemes=True)
        # Trim the model's leading and trailing near-silence, keeping a short natural edge.
        loud = np.flatnonzero(np.abs(audio) > 0.01)
        if len(loud):
            audio = audio[max(0, loud[0] - int(0.04 * sr)) : loud[-1] + int(0.12 * sr)]
        path = os.path.join(out, f"{line['id']}.wav")
        soundfile.write(path, audio.astype(np.float32), sr)
        durations[line["id"]] = round(len(audio) / sr, 3)
        print(f"{line['id']}: {durations[line['id']]:.2f} s  {line['say'][:70]}")
    json.dump(durations, open(os.path.join(out, "durations.json"), "w"), indent=2)


if __name__ == "__main__":
    main()
