"""Mixes the narration and the music for the demo into one track, ready for the picture.

    python mix.py <timeline.json>

Every narration line gets the same gain (they come out of Kokoro within a decibel of each other).
The music sits low under the voice and lifts in the pauses, on smooth ramps, with a small cut
around 1.6 kHz so consonants stay clear. The mix is then normalised in two passes to -16 LUFS
(linear, so nothing pumps) with a true-peak limit of -1.5 dBTP. Writes audio/mix.wav beside
the timeline and records "mix" in the timeline.
"""

import json
import os
import subprocess
import sys

import numpy as np
import pyloudnorm
import soundfile
from scipy import signal

SR = 48_000
VOICE_LUFS = -20.0      # each line's loudness before the final normalisation
MUSIC_UNDER_DB = -13.0  # music gain while someone is speaking
MUSIC_GAP_DB = -7.0     # music gain in the pauses
ATTACK_S, RELEASE_S = 0.35, 0.9  # how fast the music dips before a line and recovers after it


def peaking(x: np.ndarray, f0: float, gain_db: float, q: float) -> np.ndarray:
    """An RBJ peaking equaliser, applied to each channel."""
    a = 10 ** (gain_db / 40)
    w = 2 * np.pi * f0 / SR
    alpha = np.sin(w) / (2 * q)
    b = [1 + alpha * a, -2 * np.cos(w), 1 - alpha * a]
    den = [1 + alpha / a, -2 * np.cos(w), 1 - alpha / a]
    return signal.lfilter(b, den, x, axis=0)


def main() -> None:
    tl_path = sys.argv[1]
    base = os.path.dirname(os.path.abspath(tl_path))
    tl = json.load(open(tl_path))
    n = int(tl["duration"] * SR)
    meter = pyloudnorm.Meter(SR)

    voice = np.zeros((n, 2))
    speaking = np.zeros(n, bool)
    for line in tl["voice"]:
        x, sr = soundfile.read(os.path.join(base, line["src"]))
        x = signal.resample_poly(x, SR, sr) if sr != SR else x
        loud = meter.integrated_loudness(np.stack([x, x], 1)) if len(x) > SR * 0.4 else VOICE_LUFS
        x = x * 10 ** ((VOICE_LUFS - loud) / 20)
        i = int(line["at"] * SR)
        voice[i : i + len(x)] += x[: n - i, None]
        speaking[max(0, i - int(0.15 * SR)) : i + len(x) + int(0.3 * SR)] = True

    music, sr = soundfile.read(os.path.join(base, tl["music"]))
    assert sr == SR and len(music) >= n, "music must be 48 kHz and at least as long as the film"
    music = peaking(music[:n], 1600, -3.0, 1.0)

    # Gain envelope in dB: low while speaking, up in the pauses, slewed so it never jumps.
    target = np.where(speaking, MUSIC_UNDER_DB, MUSIC_GAP_DB)
    env = np.empty(n)
    g = target[0]
    down, up = (MUSIC_GAP_DB - MUSIC_UNDER_DB) / (ATTACK_S * SR), (MUSIC_GAP_DB - MUSIC_UNDER_DB) / (RELEASE_S * SR)
    # Look ahead so the dip has finished by the time a line starts.
    ahead = np.concatenate([target[int(ATTACK_S * SR):], np.full(int(ATTACK_S * SR), target[-1])])
    goal = np.minimum(target, ahead)
    for k in range(n):
        g = max(goal[k], g - down) if goal[k] < g else min(goal[k], g + up)
        env[k] = g
    mix = voice + music * (10 ** (env / 20))[:, None]

    raw = os.path.join(base, "audio", "mix_raw.wav")
    out = os.path.join(base, "audio", "mix.wav")
    soundfile.write(raw, mix.astype(np.float32), SR, subtype="FLOAT")

    # Two-pass loudness normalisation, linear, then a true-peak limiter.
    first = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", raw, "-af", "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"],
                           capture_output=True, text=True).stderr
    m = json.loads(first[first.rindex("{") : first.rindex("}") + 1])
    norm = (f"loudnorm=I=-16:TP=-1.5:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}"
            f":measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", raw, "-af", f"{norm},alimiter=limit=0.82:attack=5:release=60:level=disabled,aresample=48000",
                    "-ar", "48000", "-c:a", "pcm_s24le", out], check=True)
    x, _ = soundfile.read(out)
    print(f"{out}: {len(x) / SR:.3f} s, {meter.integrated_loudness(x):.1f} LUFS, sample peak {20 * np.log10(np.abs(x).max()):.1f} dBFS")
    tl["mix"] = "audio/mix.wav"
    json.dump(tl, open(tl_path, "w"), indent=1)


if __name__ == "__main__":
    main()
