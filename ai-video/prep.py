"""Step 1: turn the inputs into what the video model reads.

For every job this writes, under work/<job>/:
  src/    the reference clip cut out of the phone recording, at 848x480 and 16 frames a second
  mask/   white where the picture is regenerated (the person, plus the app icons on the right)
  pose/   the original person's body, hand and face pose, drawn as an OpenPose skeleton
  ctrl/   what the model is given: the original picture, with the masked area replaced by the skeleton
  ref.png the new person, cut out of the photo onto a white background
  audio.wav  the matching sound from the reference clip, if the job keeps it
"""

import json
import shutil
import subprocess

import numpy as np
from PIL import Image

from common import (
    FPS,
    HEIGHT,
    WIDTH,
    fresh_dir,
    frame_paths,
    job_dir,
    load_rgb,
    require_ffmpeg,
    resolve,
    run,
    save_png,
    torch_device,
)

GRAY = 128  # "nothing here yet" for the model
PERSON_CLASS = 15  # 'person' in the segmentation model's label set


# --- finding and cutting the clip ---------------------------------------------------------


def probe(video):
    out = run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height:format=duration",
         "-of", "json", str(video)]
    ).stdout
    info = json.loads(out)
    vstream = next(s for s in info["streams"] if s["codec_type"] == "video")
    has_audio = any(s["codec_type"] == "audio" for s in info["streams"])
    return vstream["width"], vstream["height"], float(info["format"]["duration"]), has_audio


def grab_gray(video, t, width, height):
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1",
         "-f", "rawvideo", "-pix_fmt", "gray", "-"],
        capture_output=True,
    ).stdout
    return np.frombuffer(raw, np.uint8)[: width * height].reshape(height, width)


def longest_run(flags):
    best, start = (0, 0), None
    for i, f in enumerate(list(flags) + [False]):
        if f and start is None:
            start = i
        elif not f and start is not None:
            if i - start > best[1] - best[0]:
                best = (start, i)
            start = None
    return best


def find_clip_box(video):
    """Find the bright video picture inside the dark phone-app screen."""
    from jobs import REFERENCE_CROP

    width, height, duration, _ = probe(video)
    if REFERENCE_CROP:
        return tuple(REFERENCE_CROP)
    times = np.linspace(duration * 0.2, duration * 0.8, 5)
    gray = np.median(np.stack([grab_gray(video, t, width, height) for t in times]), axis=0)
    # The app's dark interface is near black; the clip is much brighter on average.
    rows = gray[:, : int(width * 0.8)].mean(axis=1) > 40
    y0, y1 = longest_run(rows)
    cols = gray[y0:y1].mean(axis=0) > 40
    x0, x1 = longest_run(cols)
    if y1 - y0 < height * 0.15:
        # No app frame around it: use the whole picture.
        x0, y0, x1, y1 = 0, 0, width, height
    w, h = (x1 - x0) // 2 * 2, (y1 - y0) // 2 * 2
    return x0, y0, w, h


def cut_clip(job, out):
    """Cut the job's time ranges out of the reference clip, cropped, resized and resampled."""
    from jobs import REFERENCE_VIDEO

    video = resolve(REFERENCE_VIDEO)
    if not video.exists():
        raise SystemExit(f"Missing {video}. Put the racetrack video there (see inputs/README.md).")
    x, y, w, h = find_clip_box(video)
    print(f"  Clip found at x={x} y={y}, {w}x{h} pixels inside the recording.")
    segments = job["segments"]

    chains, labels = [], []
    for i, (a, b) in enumerate(segments):
        chains.append(
            f"[0:v]trim=start={a}:end={b},setpts=PTS-STARTPTS,crop={w}:{h}:{x}:{y},"
            f"fps={FPS},scale={WIDTH}:{HEIGHT}:flags=lanczos,setsar=1[v{i}]"
        )
        labels.append(f"[v{i}]")
    graph = ";".join(chains) + ";" + "".join(labels) + f"concat=n={len(segments)}:v=1:a=0[v]"
    src = fresh_dir(out / "src")
    run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-filter_complex", graph, "-map", "[v]",
         "-start_number", "0", str(src / "%06d.png")])

    if job.get("audio") == "reference":
        extract_audio(video, segments, out / "audio.wav")
    return (x, y, w, h)


# Makes the original clip's voice clear: cut rumble, reduce hiss, lift speech presence,
# then bring it to a steady, phone-friendly loudness.
VOICE_CLEANUP = (
    "highpass=f=70,afftdn=nf=-25,"
    "equalizer=f=250:t=q:w=1:g=-2,equalizer=f=3200:t=q:w=1.2:g=3,"
    "loudnorm=I=-14:TP=-1.5:LRA=11"
)


def extract_audio(video, segments, out_path):
    """The reference clip's own sound for these time ranges, joined and cleaned up."""
    if not probe(video)[3]:
        print("  The reference video has no sound; the result will be silent.")
        return
    chains, labels = [], []
    for i, (a, b) in enumerate(segments):
        chains.append(f"[0:a]atrim=start={a}:end={b},asetpts=PTS-STARTPTS[a{i}]")
        labels.append(f"[a{i}]")
    graph = (";".join(chains) + ";" + "".join(labels)
             + f"concat=n={len(segments)}:v=0:a=1,{VOICE_CLEANUP}[a]")
    run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-filter_complex", graph, "-map", "[a]",
         "-ac", "2", "-ar", "48000", str(out_path)])


def make_background_shot(job, out):
    """For a 'place' job: one still frame of the clip, with a slow camera push-in."""
    from jobs import REFERENCE_VIDEO

    video = resolve(REFERENCE_VIDEO)
    if not video.exists():
        raise SystemExit(f"Missing {video}. Put the racetrack video there (see inputs/README.md).")
    x, y, w, h = find_clip_box(video)
    still = out / "background.png"
    run(["ffmpeg", "-v", "error", "-y", "-ss", str(job["background_at"]), "-i", str(video),
         "-frames:v", "1", "-vf", f"crop={w}:{h}:{x}:{y},scale={WIDTH * 2}:{HEIGHT * 2}:flags=lanczos",
         str(still)])
    big = Image.open(still).convert("RGB")
    count = int(round(job["seconds"] * FPS))
    src = fresh_dir(out / "src")
    for i in range(count):
        zoom = 1 + (job["push_in"] - 1) * i / max(1, count - 1)
        cw, ch = big.width / zoom, big.height / zoom
        left, top = (big.width - cw) / 2, (big.height - ch) / 2
        frame = big.resize((WIDTH, HEIGHT), Image.LANCZOS, box=(left, top, left + cw, top + ch))
        save_png(frame, src / f"{i:06d}.png")
    if job.get("audio") == "reference":
        extract_audio(video, job["audio_segments"], out / "audio.wav")
    return (x, y, w, h)


# --- people: segmentation, pose, and the reference photo ----------------------------------


class PersonSegmenter:
    def __init__(self):
        import torch
        from torchvision.models.segmentation import DeepLabV3_ResNet50_Weights, deeplabv3_resnet50

        self.torch = torch
        self.device = torch_device()
        self.model = deeplabv3_resnet50(weights=DeepLabV3_ResNet50_Weights.DEFAULT).eval().to(self.device)
        self.mean = torch.tensor([0.485, 0.456, 0.406], device=self.device).view(1, 3, 1, 1)
        self.std = torch.tensor([0.229, 0.224, 0.225], device=self.device).view(1, 3, 1, 1)

    def __call__(self, rgb_frames, batch=4):
        torch = self.torch
        masks = []
        with torch.no_grad():
            for i in range(0, len(rgb_frames), batch):
                x = torch.from_numpy(np.stack(rgb_frames[i : i + batch])).to(self.device)
                x = (x.permute(0, 3, 1, 2).float() / 255 - self.mean) / self.std
                labels = self.model(x)["out"].argmax(1)
                masks.extend((labels == PERSON_CLASS).cpu().numpy())
        return masks


def grow_masks(masks, grow_px, spread_frames=2):
    """Widen each person mask, and let it cover where the person is a moment before and after."""
    import cv2

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (grow_px * 2 + 1, grow_px * 2 + 1))
    grown = np.stack([cv2.dilate(m.astype(np.uint8), kernel) > 0 for m in masks])
    spread = np.zeros_like(grown)
    for i in range(len(grown)):
        spread[i] = grown[max(0, i - spread_frames) : i + spread_frames + 1].any(axis=0)
    return spread


def overlay_strip(width, height):
    from jobs import OVERLAY_STRIP_FROM

    strip = np.zeros((height, width), bool)
    strip[:, int(width * OVERLAY_STRIP_FROM) :] = True
    return strip


def box_mask(box, width, height):
    left, top, right, bottom = box
    m = np.zeros((height, width), bool)
    m[int(top * height) : int(bottom * height), int(left * width) : int(right * width)] = True
    return m


def draw_poses(frames):
    from controlnet_aux.open_pose import OpenposeDetector

    detector = OpenposeDetector.from_pretrained("lllyasviel/Annotators").to(torch_device())
    poses = []
    for i, frame in enumerate(frames):
        pose = detector(frame, detect_resolution=512, image_resolution=HEIGHT,
                        include_body=True, include_hand=True, include_face=True)
        poses.append(np.asarray(pose.convert("RGB").resize((WIDTH, HEIGHT), Image.BILINEAR)))
        if i % 40 == 0:
            print(f"  pose {i + 1}/{len(frames)}", flush=True)
    return poses


def control_frame(src, mask, pose=None):
    """The original picture outside the mask; inside it, grey with the pose skeleton on top."""
    ctrl = src.copy()
    ctrl[mask] = GRAY
    if pose is not None:
        lines = (pose.max(axis=2) > 20) & mask
        ctrl[lines] = pose[lines]
    return ctrl


def prepare_photo(job, out, segmenter):
    """Cut the person out of the photo onto white, framed as the job asks."""
    import cv2

    path = resolve(job["photo"])
    if not path.exists():
        raise SystemExit(f"Missing {path}. See inputs/README.md for which picture goes there.")
    rgb = np.asarray(Image.open(path).convert("RGB"))
    person = segmenter([rgb], batch=1)[0]
    if person.sum() < person.size * 0.01:
        print("  No person found in the photo; using the whole picture.")
        person = np.ones(person.shape, bool)
    ys, xs = np.where(person)
    px0, px1, py0, py1 = xs.min(), xs.max(), ys.min(), ys.max()
    H, W = person.shape

    box = (px0, py0, px1, py1)
    if job["photo_crop"] == "head" and not hasattr(cv2, "CascadeClassifier"):
        print("  This OpenCV has no face finder (install opencv-python<5); using the upper body.")
        box = (px0, py0, px1, py0 + 0.45 * (py1 - py0))
    elif job["photo_crop"] == "head":
        cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        faces = cascade.detectMultiScale(cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY), 1.1, 5, minSize=(40, 40))
        if len(faces):
            fx, fy, fw, fh = max(faces, key=lambda f: f[2] * f[3])
            # Head, hair, neck and the top of the shoulders.
            box = (fx - 1.1 * fw, fy - 0.9 * fh, fx + 2.1 * fw, fy + 2.0 * fh)
        else:
            print("  No face found in the photo; using the upper body instead.")
            box = (px0, py0, px1, py0 + 0.45 * (py1 - py0))
    elif job["photo_crop"] == "upper_body":
        box = (px0, py0, px1, py0 + 0.6 * (py1 - py0))

    x0, y0, x1, y1 = (int(max(0, box[0])), int(max(0, box[1])), int(min(W, box[2])), int(min(H, box[3])))
    keep = person[y0:y1, x0:x1]
    cut = np.where(keep[..., None], rgb[y0:y1, x0:x1], 255).astype(np.uint8)
    img = Image.fromarray(cut)
    scale = min(WIDTH / img.width, HEIGHT / img.height)
    img = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
    save_png(img, out / "ref.png")


# --- the step -------------------------------------------------------------------------------


def prepare(name, job):
    require_ffmpeg()
    out = job_dir(name)
    out.mkdir(parents=True, exist_ok=True)
    print(f"[prep] {name}")
    # New inputs make any earlier render of this job stale.
    for stale in ("raw", "gen", "preview"):
        if (out / stale).exists():
            shutil.rmtree(out / stale)

    if job["kind"] == "replace":
        box = cut_clip(job, out)
    elif job["kind"] == "place":
        box = make_background_shot(job, out)
    else:
        raise SystemExit(f"Job {name}: unknown kind '{job['kind']}'")
    srcs = [load_rgb(p) for p in frame_paths(out / "src")]
    print(f"  {len(srcs)} frames ({len(srcs) / FPS:.1f} s at {FPS} fps).")

    segmenter = PersonSegmenter()
    strip = overlay_strip(WIDTH, HEIGHT)
    if job["kind"] == "replace":
        print("  Finding the person in every frame ...")
        masks = grow_masks(segmenter(srcs), grow_px=int(WIDTH * 0.035))
        masks = [m | strip for m in masks]
        print("  Reading the pose in every frame ...")
        poses = draw_poses(srcs)
    else:
        place = box_mask(job["place_box"], WIDTH, HEIGHT)
        masks = [place | strip] * len(srcs)
        poses = [None] * len(srcs)

    mask_dir, ctrl_dir, pose_dir = fresh_dir(out / "mask"), fresh_dir(out / "ctrl"), fresh_dir(out / "pose")
    for i, (src, mask, pose) in enumerate(zip(srcs, masks, poses)):
        save_png((mask * 255).astype(np.uint8), mask_dir / f"{i:06d}.png")
        save_png(control_frame(src, mask, pose), ctrl_dir / f"{i:06d}.png")
        if pose is not None:
            save_png(pose, pose_dir / f"{i:06d}.png")

    prepare_photo(job, out, segmenter)
    (out / "meta.json").write_text(json.dumps({"frames": len(srcs), "clip_box": list(box)}, indent=2))
    print(f"  Ready: {out}")
