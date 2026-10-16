"""One command for everything.

  python run.py check                     what your laptop has, and whether the inputs are in place
  python run.py preview me_sunglasses     a quick 5-second, 1080p test of one job
  python run.py all                       every job, start to finish, in 4K
  python run.py prep|generate|finish JOB  one step of one job ('all' for every job)

Add --profile cool to keep the GPU cooler (slower). Jobs and prompts live in jobs.py.
"""

import argparse
import shutil

from common import OUTPUT, ROOT, resolve
from gpu_guard import PROFILES, GpuGuard
from jobs import COMBINED, JOBS, REFERENCE_VIDEO


def pick(target):
    if target in (None, "all"):
        return list(JOBS)
    if target not in JOBS:
        raise SystemExit(f"Unknown job '{target}'. Jobs: {', '.join(JOBS)}, or 'all'.")
    return [target]


def check(guard):
    ok = True
    try:
        import torch

        print("GPU:", guard.describe())
        if torch.cuda.is_available() and guard.vram_gb() < 6:
            print("  Under 6 GB of video memory: generation may run out of memory.")
    except ImportError:
        print("PyTorch is not installed. See README.md, step 2.")
        ok = False
    print("ffmpeg:", "found" if shutil.which("ffmpeg") else "MISSING (see README.md)")
    ok &= bool(shutil.which("ffmpeg"))
    files = {REFERENCE_VIDEO} | {job["photo"] for job in JOBS.values()}
    for f in sorted(files):
        exists = resolve(f).exists()
        ok &= exists
        print(f"{f}: {'found' if exists else 'MISSING'}")
    free = shutil.disk_usage(ROOT).free / 2**30
    print(f"Free disk: {free:.0f} GB (about 25 GB needed for models and frames)")
    print("Ready." if ok else "Not ready yet: fix the items above.")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["check", "prep", "generate", "finish", "preview", "all"])
    parser.add_argument("job", nargs="?", default="all", help="a job name from jobs.py, or 'all'")
    parser.add_argument("--profile", default="balanced", choices=list(PROFILES),
                        help="balanced (default): good speed, pauses if hot. cool: gentler and slower.")
    parser.add_argument("--upscaler", default="esrgan", choices=["esrgan", "esrgan-soft", "lanczos"])
    parser.add_argument("--no-smooth", action="store_true", help="skip motion interpolation to 30 fps")
    args = parser.parse_args()
    guard = GpuGuard(args.profile)
    names = pick(args.job)

    if args.command == "check":
        return check(guard)

    from finish import combine, finish
    from generate import generate
    from prep import prepare

    if args.command in ("prep", "all", "preview"):
        from common import job_dir

        for name in names:
            if args.command == "prep" or not (job_dir(name) / "meta.json").exists():
                prepare(name, JOBS[name])
    if args.command in ("generate", "all", "preview"):
        generate(names, guard, preview=args.command == "preview")
    if args.command in ("finish", "all", "preview"):
        for name in names:
            finish(name, guard, args.upscaler, preview=args.command == "preview", smooth=not args.no_smooth)
        for combined, parts in COMBINED.items():
            if set(parts) <= set(names):
                combine(combined, parts, preview=args.command == "preview")
    if args.command in ("all", "preview", "finish"):
        print(f"\nDone. Videos are in {OUTPUT}")


if __name__ == "__main__":
    main()
