"""Step 3: make the finished 4K video.

16 fps frames -> smooth 30 fps (motion interpolation) -> 4x Real-ESRGAN upscale -> 3840x2160
-> H.264 with the clip's sound. Frames stream through memory one at a time, so no 4K images
are written to disk.
"""

import subprocess
import urllib.request

import numpy as np

from common import (
    FPS,
    HEIGHT,
    MODELS,
    OUTPUT,
    OUT_FPS,
    OUT_HEIGHT,
    OUT_WIDTH,
    WIDTH,
    frame_paths,
    job_dir,
    require_ffmpeg,
)

UPSCALERS = {
    # Sharp, detailed; the usual choice.
    "esrgan": ("RealESRGAN_x4plus.pth",
               "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth"),
    # Lighter and gentler on faces; try it if skin looks plastic.
    "esrgan-soft": ("realesr-general-x4v3.pth",
                    "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesr-general-x4v3.pth"),
}


class Upscaler:
    """Scales a 848x480 frame to the output size, on the GPU in tiles, or with Lanczos."""

    def __init__(self, kind, guard, out_size):
        import torch

        self.torch = torch
        self.guard = guard
        self.out_size = out_size
        self.model = None
        if kind == "lanczos":
            return
        if not torch.cuda.is_available():
            print("  No CUDA GPU: using plain Lanczos resizing instead of Real-ESRGAN.")
            return
        from spandrel import ModelLoader

        filename, url = UPSCALERS[kind]
        path = MODELS / filename
        if not path.exists():
            MODELS.mkdir(parents=True, exist_ok=True)
            print(f"  Downloading {filename} ...")
            urllib.request.urlretrieve(url, path)
        desc = ModelLoader().load_from_file(str(path))
        self.scale = desc.scale
        self.half = desc.supports_half
        self.model = desc.model.eval().cuda()
        if self.half:
            self.model = self.model.half()
        self.tile = guard.p["upscale_tile"]

    def _model_upscale(self, rgb):
        torch = self.torch
        s, t, pad = self.scale, self.tile, 16
        img = torch.from_numpy(rgb).cuda().permute(2, 0, 1)[None].float() / 255
        if self.half:
            img = img.half()
        _, _, h, w = img.shape
        out = torch.empty((1, 3, h * s, w * s), dtype=img.dtype, device="cuda")
        with torch.no_grad():
            for y in range(0, h, t):
                for x in range(0, w, t):
                    y0, x0 = max(y - pad, 0), max(x - pad, 0)
                    y1, x1 = min(y + t + pad, h), min(x + t + pad, w)
                    res = self.model(img[:, :, y0:y1, x0:x1])
                    th, tw = (min(y + t, h) - y) * s, (min(x + t, w) - x) * s
                    oy, ox = (y - y0) * s, (x - x0) * s
                    out[:, :, y * s : y * s + th, x * s : x * s + tw] = res[:, :, oy : oy + th, ox : ox + tw]
        return (out[0].clamp(0, 1) * 255).round().byte().permute(1, 2, 0).cpu().numpy()

    def __call__(self, rgb):
        import cv2

        if self.model is not None:
            self.guard.wait_if_hot()
            rgb = self._model_upscale(rgb)
        return cv2.resize(rgb, self.out_size, interpolation=cv2.INTER_LANCZOS4)


def encode(frames_dir, out_path, audio, upscaler, smooth=True, out_size=(OUT_WIDTH, OUT_HEIGHT)):
    """Stream frames through interpolation and upscaling into the encoder."""
    count = len(frame_paths(frames_dir))
    if not count:
        raise SystemExit(f"No frames in {frames_dir}. Run the generate step first.")
    motion = (f"minterpolate=fps={OUT_FPS}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1"
              if smooth else f"fps={OUT_FPS}")
    decoder = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-framerate", str(FPS), "-start_number", "0", "-i", str(frames_dir / "%06d.png"),
         "-vf", motion, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        stdout=subprocess.PIPE,
    )
    sound = ["-i", str(audio)] if audio else ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    encoder = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-y",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{out_size[0]}x{out_size[1]}", "-r", str(OUT_FPS), "-i", "-",
         *sound, "-map", "0:v", "-map", "1:a",
         "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", "-shortest",
         "-movflags", "+faststart", str(out_path)],
        stdin=subprocess.PIPE,
    )
    frame_bytes = WIDTH * HEIGHT * 3
    expected = round(count / FPS * OUT_FPS)
    done = 0
    while True:
        buf = decoder.stdout.read(frame_bytes)
        if len(buf) < frame_bytes:
            break
        frame = np.frombuffer(buf, np.uint8).reshape(HEIGHT, WIDTH, 3)
        encoder.stdin.write(np.ascontiguousarray(upscaler(frame)).tobytes())
        done += 1
        if done % 30 == 0:
            print(f"  {done}/{expected} frames", flush=True)
    encoder.stdin.close()
    decoder.wait()
    if encoder.wait() != 0 or decoder.returncode != 0:
        raise SystemExit(f"Encoding {out_path.name} failed.")
    return done


def finish(name, guard, upscaler_kind="esrgan", preview=False, smooth=True):
    require_ffmpeg()
    path = job_dir(name) / "preview" if preview else job_dir(name)
    if preview:
        size, kind, out = (1920, 1080), "lanczos", OUTPUT / f"{name}_preview.mp4"
    else:
        size, kind, out = (OUT_WIDTH, OUT_HEIGHT), upscaler_kind, OUTPUT / f"{name}_4k.mp4"
    guard.setup_torch()
    print(f"[finish] {name} -> {out}")
    audio = path / "audio.wav"
    frames = encode(path / "gen", out, audio if audio.exists() else None, Upscaler(kind, guard, size), smooth, size)
    print(f"  Wrote {out} ({frames} frames, {size[0]}x{size[1]}, {OUT_FPS} fps).")
    return out


def combine(name, parts, preview=False):
    """Join finished videos end to end without re-encoding."""
    require_ffmpeg()
    suffix = "_preview.mp4" if preview else "_4k.mp4"
    files = [OUTPUT / f"{p}{suffix}" for p in parts]
    missing = [f.name for f in files if not f.exists()]
    if missing:
        raise SystemExit(f"Can't make {name} yet; missing: {', '.join(missing)}")
    listing = OUTPUT / f".{name}_parts.txt"
    listing.write_text("".join(f"file '{f.name}'\n" for f in files))
    out = OUTPUT / f"{name}{suffix}"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
                    "-c", "copy", "-movflags", "+faststart", str(out)], check=True)
    listing.unlink()
    print(f"[combine] Wrote {out}")
    return out
