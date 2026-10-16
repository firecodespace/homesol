"""Step 2: render the new person into the clip with Wan 2.1 VACE (1.3B), chunk by chunk.

The clip is rendered in 5-second chunks. Each chunk after the first starts from the last
OVERLAP_FRAMES frames of the one before, so the joins don't jump. Every finished frame is saved
straight away, so if the laptop sleeps or you stop it, running the same command again carries on
from where it stopped.

Writes, under work/<job>/:
  raw/   frames exactly as the model drew them (used to continue the next chunk)
  gen/   the same frames with the untouched background pasted back from the clip, so the
         racetrack, sky and car stay exactly as they were
"""

import hashlib
import math
import time

import numpy as np
from PIL import Image

from common import (
    CHUNK_FRAMES,
    FPS,
    HEIGHT,
    MODEL_ID,
    OVERLAP_FRAMES,
    WIDTH,
    WORK,
    frame_paths,
    job_dir,
    load_mask,
    load_rgb,
    save_png,
)

FLOW_SHIFT = 3.0  # recommended for 480p
GUIDANCE = 5.0
STEPS = 30
PREVIEW_STEPS = 20
SEED = 1234


# --- planning -------------------------------------------------------------------------------


def round_up_4k1(n):
    """The model generates 4k+1 frames."""
    return 4 * math.ceil((n - 1) / 4) + 1


def plan_chunks(total, done=0, chunk=CHUNK_FRAMES, overlap=OVERLAP_FRAMES):
    """Return (keep, start, new) for each chunk still to render.

    keep  frames carried over from the previous chunk (0 for the first)
    start index of the first new frame
    new   new frames this chunk adds
    """
    plan = []
    while done < total:
        keep = min(overlap, done)
        new = min(chunk - keep, total - done)
        plan.append((keep, done, new))
        done += new
    return plan


# --- text embeddings ------------------------------------------------------------------------


def encode_prompts(texts, guard):
    """Turn prompts into the model's text embeddings, cached on disk.

    The text encoder alone is about 11 GB, so it runs once, its results are saved, and it is
    removed from memory before the video model is loaded.
    """
    import torch

    cache = WORK / "text_cache"
    cache.mkdir(parents=True, exist_ok=True)
    paths = {t: cache / (hashlib.sha1(t.encode()).hexdigest()[:16] + ".pt") for t in texts}
    missing = [t for t, p in paths.items() if not p.exists()]
    if missing:
        from diffusers.pipelines.wan.pipeline_wan_vace import prompt_clean
        from transformers import AutoTokenizer, UMT5EncoderModel

        on_gpu = guard.vram_gb() >= 16
        device = "cuda" if on_gpu else "cpu"
        print(f"  Encoding {len(missing)} prompt(s) on the {'GPU' if on_gpu else 'CPU (this takes a minute or two)'} ...")
        tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, subfolder="tokenizer")
        encoder = UMT5EncoderModel.from_pretrained(
            MODEL_ID, subfolder="text_encoder", torch_dtype=torch.bfloat16, low_cpu_mem_usage=True
        ).to(device)
        max_len = 512  # the pipeline's default
        with torch.no_grad():
            for text in missing:
                tokens = tokenizer([prompt_clean(text)], padding="max_length", max_length=max_len,
                                   truncation=True, add_special_tokens=True, return_attention_mask=True,
                                   return_tensors="pt")
                length = int(tokens.attention_mask.sum())
                hidden = encoder(tokens.input_ids.to(device), tokens.attention_mask.to(device)).last_hidden_state
                embeds = torch.zeros_like(hidden)
                embeds[:, :length] = hidden[:, :length]
                torch.save(embeds.cpu(), paths[text])
        del encoder
        import gc

        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    return {t: torch.load(p) for t, p in paths.items()}


# --- the model --------------------------------------------------------------------------------


def load_pipeline(guard):
    import torch
    from diffusers import AutoencoderKLWan, UniPCMultistepScheduler, WanVACEPipeline

    print(f"  Loading {MODEL_ID} (downloads about 7 GB the first time) ...")
    vae = AutoencoderKLWan.from_pretrained(MODEL_ID, subfolder="vae", torch_dtype=torch.float32)
    pipe = WanVACEPipeline.from_pretrained(
        MODEL_ID, vae=vae, text_encoder=None, tokenizer=None, torch_dtype=torch.bfloat16
    )
    pipe.scheduler = UniPCMultistepScheduler.from_config(pipe.scheduler.config, flow_shift=FLOW_SHIFT)
    pipe.vae.enable_tiling()  # encode and decode the video in tiles: much less video memory
    guard.place_pipeline(pipe)
    pipe.set_progress_bar_config(leave=False)
    return pipe


def soft_mask(mask, shrink_px=6, blur_px=15):
    """A feathered version of the mask, so pasted-back background blends in."""
    import cv2

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (shrink_px * 2 + 1, shrink_px * 2 + 1))
    inner = cv2.erode(mask.astype(np.uint8) * 255, kernel)
    return cv2.GaussianBlur(inner, (blur_px * 2 + 1, blur_px * 2 + 1), 0).astype(np.float32)[..., None] / 255


def composite(generated, original, mask):
    alpha = soft_mask(mask)
    return (generated * alpha + original * (1 - alpha)).round().astype(np.uint8)


def render_chunks(pipe, job_path, total, embeds, guard, steps, call_model=None):
    """Render every chunk not yet on disk. call_model is replaceable for tests."""
    raw_dir, gen_dir = job_path / "raw", job_path / "gen"
    raw_dir.mkdir(exist_ok=True)
    gen_dir.mkdir(exist_ok=True)
    ctrl = frame_paths(job_path / "ctrl")
    masks = frame_paths(job_path / "mask")
    srcs = frame_paths(job_path / "src")
    ref = Image.open(job_path / "ref.png").convert("RGB")
    black = Image.new("L", (WIDTH, HEIGHT), 0)

    done = len(frame_paths(raw_dir))
    if done >= total:
        print("  Already rendered.")
        return
    if done:
        print(f"  Carrying on from frame {done} of {total}.")
    plan = plan_chunks(total, done)

    for number, (keep, start, new) in enumerate(plan, 1):
        began = time.time()
        frames = [Image.open(raw_dir / f"{i:06d}.png").convert("RGB") for i in range(start - keep, start)]
        frame_masks = [black] * keep
        frames += [Image.open(p).convert("RGB") for p in ctrl[start : start + new]]
        frame_masks += [Image.open(p).convert("L") for p in masks[start : start + new]]
        count = round_up_4k1(len(frames))
        frames += [frames[-1]] * (count - len(frames))
        frame_masks += [frame_masks[-1]] * (count - len(frame_masks))

        print(f"  Chunk {number}/{len(plan)}: frames {start}-{start + new - 1} ({count} rendered, {steps} steps)", flush=True)
        if call_model is None:
            import torch

            out = pipe(
                video=frames,
                mask=frame_masks,
                reference_images=[ref],
                prompt_embeds=embeds["prompt"],
                negative_prompt_embeds=embeds["negative"],
                height=HEIGHT,
                width=WIDTH,
                num_frames=count,
                num_inference_steps=steps,
                guidance_scale=GUIDANCE,
                generator=torch.Generator("cpu").manual_seed(SEED + start),
                output_type="np",
                callback_on_step_end=guard.step_callback,
            ).frames[0]
        else:
            out = call_model(frames, frame_masks, count)

        for j in range(new):
            idx = start + j
            drawn = (np.clip(out[keep + j], 0, 1) * 255).round().astype(np.uint8)
            save_png(drawn, raw_dir / f"{idx:06d}.png")
            save_png(composite(drawn.astype(np.float32), load_rgb(srcs[idx]).astype(np.float32),
                               load_mask(masks[idx])), gen_dir / f"{idx:06d}.png")
        minutes = (time.time() - began) / 60
        print(f"  Chunk {number} done in {minutes:.1f} min.", flush=True)
        if number < len(plan):
            guard.rest_between_chunks()


def generate(names, guard, preview=False):
    import json

    from common import get_job

    jobs = {n: get_job(n) for n in names}
    for name in names:
        if not (job_dir(name) / "meta.json").exists():
            raise SystemExit(f"Job {name} is not prepared yet. Run:  python run.py prep {name}")

    guard.setup_torch()
    print("[generate]", guard.describe())
    texts = set()
    for job in jobs.values():
        texts.update([job["prompt"], job["negative"]])
    embeds = encode_prompts(sorted(texts), guard)
    pipe = load_pipeline(guard)
    steps = PREVIEW_STEPS if preview else STEPS

    for name, job in jobs.items():
        path = job_dir(name)
        total = json.loads((path / "meta.json").read_text())["frames"]
        if preview:
            total = min(total, CHUNK_FRAMES)
            path = preview_copy(path, total)
        print(f"[generate] {name}: {total} frames ({total / FPS:.1f} s)")
        render_chunks(pipe, path, total, {"prompt": embeds[job["prompt"]], "negative": embeds[job["negative"]]},
                      guard, steps)


def preview_copy(path, total):
    """Previews render into work/<job>/preview so they never mix with the full render."""
    import shutil

    prev = path / "preview"
    prev.mkdir(exist_ok=True)
    for sub in ("src", "mask", "ctrl"):
        (prev / sub).mkdir(exist_ok=True)
        for p in frame_paths(path / sub)[:total]:
            if not (prev / sub / p.name).exists():
                shutil.copy(p, prev / sub / p.name)
    shutil.copy(path / "ref.png", prev / "ref.png")
    if (path / "audio.wav").exists():
        shutil.copy(path / "audio.wav", prev / "audio.wav")
    return prev
