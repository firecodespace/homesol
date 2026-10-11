"""Assembles the demo from a timeline file into the final MP4 with one ffmpeg render.

    python assemble.py timeline.json out.mp4 [--preview]

The timeline (paths relative to the timeline file):

    {
      "duration": 180, "fps": 30,
      "video": [                       # the picture, clip after clip
        {"src": "raw/t1.mkv", "in": 3.0, "dur": 15.0,
         "push": [[0, 0, 1920, 1080], [120, 60, 1680, 945]],   # optional: crop rect at start and end
         "xfade": 0.5},                # dissolve into the NEXT clip, overlapping it by this much
        ...
      ],
      "overlays": [{"src": "graphics/lower_1.mov", "at": 64.0}],   # alpha graphics, placed in time
      "voice": [{"src": "audio/vo_01.wav", "at": 0.6}],            # narration lines
      "music": "audio/music.wav"
    }

Clips are placed back to back; a dissolve overlaps the next clip by `xfade` seconds, so the
clip durations, minus the dissolves, must add up to `duration` exactly. The render is cut to
exactly duration x fps frames, and the audio to the same length.
"""

import json
import os
import subprocess
import sys

W, H = 1920, 1080


def clip_filter(i: int, clip: dict, fps: int) -> str:
    """Trim one clip, normalise it to 1080p30, and apply its slow push-in if it has one."""
    # Screen captures carry wall-clock timestamps; zero them before trimming.
    f = [f"[{i}:v]setpts=PTS-STARTPTS", f"trim=start={clip.get('in', 0)}:duration={clip['dur']}", "setpts=PTS-STARTPTS", f"fps={fps}", "format=rgb24"]
    if "push" in clip:
        (x0, y0, w0, h0), (x1, y1, w1, h1) = clip["push"]
        d = clip["dur"]
        # Ease in and out; the crop works on a 2x upscale so the move steps in half pixels.
        k = f"(0.5-0.5*cos(PI*min(t/{d},1)))"
        f += [
            f"scale={2 * W}:{2 * H}:flags=lanczos",
            f"crop=w='2*({w0}+({w1}-{w0})*{k})':h='2*({h0}+({h1}-{h0})*{k})':x='2*({x0}+({x1}-{x0})*{k})':y='2*({y0}+({y1}-{y0})*{k})'",
        ]
    f += [f"scale={W}:{H}:flags=lanczos", "setsar=1", "format=yuv444p"]
    return ",".join(f) + f"[c{i}]"


def build(timeline_path: str, out: str, preview: bool) -> list[str]:
    base = os.path.dirname(os.path.abspath(timeline_path))
    tl = json.load(open(timeline_path))
    fps, duration = tl.get("fps", 30), tl["duration"]
    video, overlays, voice = tl["video"], tl.get("overlays", []), tl.get("voice", [])
    path = lambda p: os.path.join(base, p)

    total = sum(c["dur"] for c in video) - sum(c.get("xfade", 0) for c in video[:-1])
    if abs(total - duration) > 1e-6:
        raise SystemExit(f"clips add up to {total:.3f} s, not {duration} s")

    # A clip asking for more than its source holds would silently break the dissolves.
    for c in video:
        have = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path(c["src"])],
                                    capture_output=True, text=True, check=True).stdout)
        if c.get("in", 0) + c["dur"] > have + 1e-3:
            raise SystemExit(f"{c['src']}: wants {c.get('in', 0)} + {c['dur']} s but holds {have:.3f} s")

    inputs, graph = [], []
    for c in video:
        inputs += ["-i", path(c["src"])]
    for i, c in enumerate(video):
        graph.append(clip_filter(i, c, fps))

    # Chain the clips: a dissolve where one is asked for, a straight cut otherwise.
    current, t = "c0", video[0]["dur"]
    for i in range(1, len(video)):
        fade = video[i - 1].get("xfade", 0)
        label = f"v{i}"
        if fade > 0:
            graph.append(f"[{current}][c{i}]xfade=transition=fade:duration={fade}:offset={t - fade:.4f}[{label}]")
        else:
            graph.append(f"[{current}][c{i}]concat=n=2:v=1:a=0[{label}]")
        current, t = label, t + video[i]["dur"] - fade

    n = len(video)
    for j, o in enumerate(overlays):
        inputs += ["-i", path(o["src"])]
        idx = n + j
        graph.append(f"[{idx}:v]format=rgba,setpts=PTS-STARTPTS+{o['at']}/TB[o{j}]")
        graph.append(f"[{current}][o{j}]overlay=eof_action=pass:format=auto[ov{j}]")
        current = f"ov{j}"
    graph.append(f"[{current}]format=yuv420p,trim=duration={duration},setpts=PTS-STARTPTS[vout]")

    # Audio: narration lines placed in time, music ducked under them.
    a0 = n + len(overlays)
    for k, v in enumerate(voice):
        inputs += ["-i", path(v["src"])]
        ms = int(round(v["at"] * 1000))
        graph.append(f"[{a0 + k}:a]aresample=48000,aformat=channel_layouts=stereo,adelay={ms}|{ms}[vo{k}]")
    music_idx = a0 + len(voice)
    inputs += ["-i", path(tl["music"])]
    if voice:
        graph.append("".join(f"[vo{k}]" for k in range(len(voice))) + f"amix=inputs={len(voice)}:normalize=0,apad[voice]")
        graph.append("[voice]asplit=2[vmix][vkey]")
        # Under the voice, the music drops by about 12 dB and loses some of its middle, where speech lives.
        graph.append(
            f"[{music_idx}:a]aresample=48000,volume=0.9,equalizer=f=1600:t=q:w=1.1:g=-4[mus]"
        )
        graph.append("[mus][vkey]sidechaincompress=threshold=0.03:ratio=4:attack=80:release=700:makeup=1[ducked]")
        graph.append("[vmix]volume=1.0[vfinal]")
        graph.append("[ducked][vfinal]amix=inputs=2:normalize=0[amixed]")
        audio = "amixed"
    else:
        audio = f"{music_idx}:a"
        graph.append(f"[{audio}]anull[amixed]")
        audio = "amixed"
    graph.append(f"[{audio}]atrim=duration={duration},asetpts=PTS-STARTPTS,loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000[aout]")

    frames = int(round(duration * fps))
    encode = (
        ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23"]
        if preview
        else ["-c:v", "libx264", "-preset", "slow", "-crf", "16", "-profile:v", "high", "-level", "4.2", "-tune", "stillimage"]
    )
    return [
        "ffmpeg", "-y", "-loglevel", "error", "-stats", *inputs,
        "-filter_complex", ";\n".join(graph),
        "-map", "[vout]", "-map", "[aout]",
        "-r", str(fps), "-frames:v", str(frames), *encode, "-pix_fmt", "yuv420p", "-g", str(fps * 2),
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-t", str(duration),
        "-movflags", "+faststart", out,
    ]


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    cmd = build(args[0], args[1], "--preview" in sys.argv)
    if "--print" in sys.argv:
        print(" ".join(f"'{c}'" if " " in c or ";" in c else c for c in cmd))
    else:
        subprocess.run(cmd, check=True)
