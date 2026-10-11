"""An original 180-second music bed for the homesol demo, synthesised from nothing.

No samples or third-party loops are used: every sound is generated here from sine waves,
band-limited sawtooths and filtered noise, so the result carries no licence obligations.

At 96 BPM a bar is 2.5 s, so the brief's section boundaries fall on bar lines:
  0-15 s   hook     bars 0-6    pad swell, a bell motif
  15-40 s  problem  bars 6-16   pad, low pulse, quiet plucks
  40-60 s  reveal   bars 16-24  brighter progression, arpeggio lifts, riser into the demo
  60-135 s demo     bars 24-54  steady, restrained groove under the narration
  135-160 s proof   bars 54-64  percussion drops out, suspended chords build tension
  160-180 s close   bars 64-72  resolves to D major, final bell, fades to silence at 180 s

Usage: python music.py <out.wav>
"""

import sys

import numpy as np
import pyloudnorm
import soundfile
from scipy import signal

SR = 48_000
BPM = 96
BEAT = 60 / BPM
BAR = 4 * BEAT
LENGTH = 180.0
N = int(LENGTH * SR)
rng = np.random.default_rng(7)

NOTE = {n: i for i, n in enumerate(["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"])}


def hz(name: str) -> float:
    """'F#3' -> frequency in hertz."""
    pitch, octave = name[:-1], int(name[-1])
    return 440.0 * 2 ** ((NOTE[pitch] + 12 * (octave + 1) - 69) / 12)


# Chords as voicings (pad notes) with a bass root, two bars each unless stated.
CHORDS = {
    "Bm9": (["B2", "F#3", "A3", "C#4", "D4"], "B1"),
    "Gmaj7": (["G2", "D3", "F#3", "B3", "D4"], "G1"),
    "Dmaj7": (["D3", "F#3", "A3", "C#4", "E4"], "D2"),
    "A6": (["A2", "E3", "F#3", "C#4", "E4"], "A1"),
    "D": (["D3", "A3", "D4", "F#4", "A4"], "D2"),
    "Asl": (["C#3", "E3", "A3", "C#4", "E4"], "C#2"),
    "Bm": (["B2", "F#3", "B3", "D4", "F#4"], "B1"),
    "G": (["G2", "D3", "G3", "B3", "D4"], "G1"),
    "A": (["A2", "E3", "A3", "C#4", "E4"], "A1"),
    "Em7": (["E3", "B3", "D4", "G4", "B4"], "E2"),
    "Asus": (["A2", "E3", "A3", "D4", "E4"], "A1"),
    "Dmaj9": (["D3", "A3", "C#4", "E4", "F#4"], "D2"),
}

# (start bar, chord name, bars)
PROGRESSION = (
    [(0, "Bm9", 6)]
    + [(6 + 2 * i, c, 2) for i, c in enumerate(["Bm9", "Gmaj7", "Dmaj7", "A6", "Bm9"])]
    + [(16 + 2 * i, c, 2) for i, c in enumerate(["D", "Asl", "Bm", "G"])]
    + [(24 + 2 * i, c, 2) for i, c in enumerate(["D", "Bm", "G", "A"] * 3 + ["D", "Bm", "G"])]
    + [(54, "Em7", 2), (56, "G", 2), (58, "Em7", 2), (60, "Asus", 2), (62, "A", 2)]
    + [(64, "D", 2), (66, "G", 2), (68, "Dmaj9", 4)]
)

SECTIONS = [(0, "hook"), (6, "problem"), (16, "reveal"), (24, "demo"), (54, "proof"), (64, "close"), (72, "end")]


def section_at(bar: float) -> str:
    name = SECTIONS[0][1]
    for start, s in SECTIONS:
        if bar >= start:
            name = s
    return name


def saw(freq: float, t: np.ndarray, top: float = 7000.0) -> np.ndarray:
    """A band-limited sawtooth: harmonics up to `top` Hz, so nothing aliases."""
    out = np.zeros_like(t)
    for k in range(1, int(top // freq) + 1):
        out += np.sin(2 * np.pi * k * freq * t) / k
    return out


def envelope(n: int, attack: float, release: float) -> np.ndarray:
    env = np.ones(n)
    a, r = int(attack * SR), int(release * SR)
    if a:
        env[:a] = np.linspace(0, 1, a) ** 1.5
    if r:
        env[-r:] *= np.linspace(1, 0, r) ** 1.5
    return env


def lowpass(x: np.ndarray, cutoff: float, order: int = 2) -> np.ndarray:
    sos = signal.butter(order, cutoff, "low", fs=SR, output="sos")
    return signal.sosfilt(sos, x)


def place(buf: np.ndarray, start: float, sound: np.ndarray, gain: float, pan: float = 0.0) -> None:
    """Add a mono sound into the stereo buffer at `start` seconds, panned -1 (left) to 1 (right)."""
    i = int(start * SR)
    if i >= N:
        return
    sound = sound[: N - i] * gain
    left, right = np.cos((pan + 1) * np.pi / 4), np.sin((pan + 1) * np.pi / 4)
    buf[i : i + len(sound), 0] += sound * left
    buf[i : i + len(sound), 1] += sound * right


def pad_layer() -> np.ndarray:
    buf = np.zeros((N, 2))
    brightness = {"hook": 900, "problem": 1100, "reveal": 1700, "demo": 1500, "proof": 1300, "close": 1800}
    for bar, chord, bars in PROGRESSION:
        start, dur = bar * BAR, bars * BAR + 1.6  # overlap for a smooth crossfade
        t = np.arange(int(dur * SR)) / SR
        notes, _ = CHORDS[chord]
        for j, note in enumerate(notes):
            f = hz(note)
            voice = sum(saw(f * d, t + rng.random()) for d in (0.997, 1.0, 1.004)) / 3
            # A slow breathing movement in the filter keeps the pad alive.
            voice = lowpass(voice, brightness[section_at(bar)] * (1 + 0.1 * np.sin(2 * np.pi * 0.11 * start)))
            voice *= envelope(len(t), 1.4 if bar else 4.5, 1.6)
            place(buf, start, voice, 0.055, pan=(j / (len(notes) - 1) - 0.5) * 0.8)
    return buf


def pluck(freq: float, length: float = 0.9) -> np.ndarray:
    t = np.arange(int(length * SR)) / SR
    tone = np.sin(2 * np.pi * freq * t) + 0.35 * np.sin(4 * np.pi * freq * t) + 0.12 * np.sin(6 * np.pi * freq * t)
    return tone * np.exp(-t * 7.5) * envelope(len(t), 0.004, 0.05)


def bell(freq: float, length: float = 4.0) -> np.ndarray:
    """FM bell: a carrier modulated at 3.5x its frequency, the modulation fading faster than the tone."""
    t = np.arange(int(length * SR)) / SR
    index = 2.2 * np.exp(-t * 2.5)
    return np.sin(2 * np.pi * freq * t + index * np.sin(2 * np.pi * 3.5 * freq * t)) * np.exp(-t * 1.4) * envelope(len(t), 0.002, 0.3)


def melodic_layer() -> np.ndarray:
    buf = np.zeros((N, 2))
    for bar, chord, bars in PROGRESSION:
        notes, root = CHORDS[chord]
        sec = section_at(bar)
        upper = [hz(n) * 2 for n in notes[1:]]
        for b in range(bars):
            bar_start = (bar + b) * BAR
            if sec in ("problem", "reveal", "demo", "close"):
                # Eighth-note arpeggio; the reveal climbs, the rest rock gently.
                pattern = [0, 2, 1, 3, 2, 1, 3, 2] if sec != "reveal" else [0, 1, 2, 3, 2, 3, 1, 3]
                level = {"problem": 0.045, "reveal": 0.07, "demo": 0.06, "close": 0.06}[sec]
                for k, idx in enumerate(pattern):
                    accent = 1.0 if k % 2 == 0 else 0.72
                    place(buf, bar_start + k * BEAT / 2, pluck(upper[idx % len(upper)]), level * accent, pan=0.35 if k % 2 else -0.35)
            if sec != "hook":
                # Bass: the root on the first beat, the fifth before the next bar in the busier sections.
                t = np.arange(int(BAR * SR)) / SR
                f = hz(root)
                tone = (np.sin(2 * np.pi * f * t) + 0.25 * np.sin(4 * np.pi * f * t)) * envelope(len(t), 0.02, 0.4)
                place(buf, bar_start, tone * np.exp(-t * 0.6), 0.16 if sec != "proof" else 0.13)
    # Bells mark the opening statement, the reveal and the ending.
    for at, note in [(2.5, "F#5"), (5.0, "A5"), (10.0, "D6"), (40.0, "A5"), (41.25, "D6"), (165.0, "F#5"), (170.0, "A5"), (172.5, "D6")]:
        place(buf, at, bell(hz(note)), 0.05, pan=0.2)
    return buf


def rhythm_layer() -> np.ndarray:
    buf = np.zeros((N, 2))
    kick_t = np.arange(int(0.35 * SR)) / SR
    kick = np.sin(2 * np.pi * (45 * kick_t + (90 - 45) / 18 * (1 - np.exp(-18 * kick_t)))) * np.exp(-kick_t * 11)
    shaker = signal.sosfilt(signal.butter(4, 6500, "high", fs=SR, output="sos"), rng.standard_normal(int(0.05 * SR)))
    shaker *= np.exp(-np.arange(len(shaker)) / SR * 70)
    for bar in range(72):
        sec = section_at(bar)
        if sec == "problem":
            place(buf, bar * BAR, kick, 0.10)
        if sec in ("demo", "close") and bar < 70:
            for beat in (0, 2):
                place(buf, bar * BAR + beat * BEAT, kick, 0.13)
            for k in range(4):
                place(buf, bar * BAR + (k + 0.5) * BEAT, shaker, 0.02, pan=0.3)
    # A soft filtered-noise rise into the demo, and another into the close.
    for end in (60.0, 160.0):
        n = int(2.5 * SR)
        noise = rng.standard_normal(n)
        cut = np.linspace(400, 5000, n)
        rise = np.zeros(n)
        # Swept low-pass, block by block.
        for i in range(0, n, 2400):
            rise[i : i + 2400] = lowpass(noise[i : i + 2400], cut[i])
        place(buf, end - 2.5, rise * np.linspace(0, 1, n) ** 2, 0.05)
    return buf


def reverb(x: np.ndarray, seconds: float = 2.8, wet: float = 0.28) -> np.ndarray:
    n = int(seconds * SR)
    t = np.arange(n) / SR
    ir = np.stack([lowpass(rng.standard_normal(n), 5200) * np.exp(-t * 6.9 / seconds) for _ in range(2)], axis=1)
    ir /= np.sqrt((ir**2).sum(axis=0))
    tail = np.stack([signal.fftconvolve(x[:, c], ir[:, c])[:N] for c in range(2)], axis=1)
    return x * (1 - wet) + tail * wet


def main(out: str) -> None:
    mix = reverb(pad_layer() + melodic_layer(), 3.2, 0.35) + reverb(rhythm_layer(), 1.2, 0.15)
    # The last bars fade to true silence exactly at 180 s.
    fade = int(4.0 * SR)
    mix[-fade:] *= np.linspace(1, 0, fade)[:, None] ** 2
    mix[:int(0.05 * SR)] *= np.linspace(0, 1, int(0.05 * SR))[:, None]
    meter = pyloudnorm.Meter(SR)
    mix = pyloudnorm.normalize.loudness(mix, meter.integrated_loudness(mix), -20.0)
    peak = np.abs(mix).max()
    if peak > 0.89:
        mix *= 0.89 / peak
    soundfile.write(out, mix.astype(np.float32), SR, subtype="PCM_24")
    print(f"{out}: {len(mix) / SR:.3f} s, {meter.integrated_loudness(mix):.1f} LUFS, peak {20 * np.log10(np.abs(mix).max()):.1f} dBFS")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "music.wav")
