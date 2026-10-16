"""Settings and small helpers shared by every step."""

import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent
WORK = ROOT / "work"
OUTPUT = ROOT / "output"
MODELS = ROOT / "models"

# The video model works at 480p, 16 frames a second, in chunks of 81 frames (about 5 s).
MODEL_ID = "Wan-AI/Wan2.1-VACE-1.3B-diffusers"
WIDTH, HEIGHT = 848, 480  # 16:9, both divisible by 16
FPS = 16
CHUNK_FRAMES = 81  # must be 4k+1
OVERLAP_FRAMES = 9  # frames each chunk re-uses from the previous one, for a seamless join

# The finished video.
OUT_WIDTH, OUT_HEIGHT = 3840, 2160  # 4K UHD
OUT_FPS = 30


def job_dir(name):
    return WORK / name


def get_job(name):
    from jobs import JOBS

    if name not in JOBS:
        raise SystemExit(f"Unknown job '{name}'. Jobs: {', '.join(JOBS)}")
    return JOBS[name]


def resolve(path):
    p = Path(path)
    return p if p.is_absolute() else ROOT / p


def require_ffmpeg():
    if not shutil.which("ffmpeg"):
        raise SystemExit(
            "ffmpeg is not installed or not on PATH.\n"
            "  Windows: winget install Gyan.FFmpeg   (then open a new terminal)\n"
            "  Linux:   sudo apt install ffmpeg"
        )


def run(cmd):
    """Run a command and stop with its output if it fails."""
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        sys.stderr.write(result.stderr[-3000:])
        raise SystemExit(f"Command failed: {' '.join(str(c) for c in cmd[:6])} ...")
    return result


def frame_paths(folder):
    return sorted(Path(folder).glob("*.png"))


def load_rgb(path):
    return np.asarray(Image.open(path).convert("RGB"))


def load_mask(path):
    return np.asarray(Image.open(path).convert("L")) > 127


def save_png(array_or_image, path):
    img = array_or_image if isinstance(array_or_image, Image.Image) else Image.fromarray(array_or_image)
    img.save(path, compress_level=1)


def fresh_dir(path):
    path = Path(path)
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)
    return path


def torch_device():
    import torch

    return "cuda" if torch.cuda.is_available() else "cpu"
