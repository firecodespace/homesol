# Demo video: plan and hand-off

Written 11 October 2026 for the session that finishes the 3-minute product demo. Read this, then `demo_script.md` and `demo_shot_list.md`. The product itself is described in `../docs/handoff.md` and `../docs/how-it-works.md`.

## The brief, in short

The owner asked for a finished, exactly 180-second product demo of homesol, made by operating the real application in a browser here, not a storyboard. Deliverables, all inside `demo/`:

- `project_demo_final.mp4`: exactly 180.000 s, 1920×1080, 30 fps, H.264 + AAC.
- `demo_script.md`: narration and on-screen text with timestamps.
- `demo_shot_list.md`: the footage captured and what each segment is for.
- `demo_assets/`: original recordings, captions, graphics and audio.

Story beats are fixed: hook 0:00–0:15, problem 0:15–0:40, reveal 0:40–1:00, live demo 1:00–2:15, proof 2:15–2:40, close 2:40–3:00. Non-negotiable: real product footage only; no invented numbers, testimonials or benchmarks; no keys, credentials or personal data on screen; licensed (here, original) music; honest final report of duration, specs, tools and limits.

## Decisions already made with the owner

- **Recorded here**, by driving the real app with Playwright in a headed Chromium on a virtual display.
- **Property:** a home in Chandigarh, or wherever the demo works best. Choose by scouting (below). Keep house numbers off screen; the location card may show a street or sector.
- **Voice:** neural, Kokoro-82M (Apache-2.0), run locally. Voice `af_heart`.
- **Music:** original, synthesised by `tools/music.py`; no licence question.
- **Commits:** the owner commits and pushes themselves unless they say otherwise. Large media is git-ignored; deliver the finished files to the owner directly.

## What this session needs (the owner adds these in the environment settings)

| Need | Why |
|---|---|
| Secrets `GOOGLE_MAPS_API_KEY`, `AWS_BEARER_TOKEN_BEDROCK`, `AWS_REGION=us-east-1` | Google's 3D survey; Claude on Bedrock for obstruction names and the advisor |
| Allowed hosts `server.arcgisonline.com`, `services.arcgisonline.com` | Satellite base map and imagery dates |
| `photon.komoot.io` | Address search, the location card, country and state |
| `power.larc.nasa.gov` | Monthly sunlight; without it there is no generation, cost or savings |
| `huggingface.co`, `cdn-lfs.huggingface.co`, `cdn-lfs-us-1.huggingface.co`, `cas-bridge.xethub.hf.co` | Kokoro model and voice download |

Already reachable without changes: `solar.googleapis.com`, `bedrock-runtime.us-east-1.amazonaws.com`, Google Fonts, PyPI, npm.

Check before anything else:

```bash
env | grep -oE '^(GOOGLE_MAPS_API_KEY|AWS_BEARER_TOKEN_BEDROCK|AWS_REGION)=' # names only, never print values
for u in https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/3/3/5 https://photon.komoot.io/api/?q=Chandigarh https://power.larc.nasa.gov/ https://huggingface.co/; do echo "$(curl -s -o /dev/null -m 12 -w '%{http_code}' "$u") $u"; done
```

If something is still blocked, tell the owner which host, and carry on with what does not depend on it.

## Setting up a fresh container

```bash
cd api && python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt && cd ..
cd web && pnpm install --frozen-lockfile && NEXT_PUBLIC_API_URL=http://localhost:8000 pnpm build && cd ..
cd demo && python3 -m venv .venv && .venv/bin/pip install -q -r tools/requirements.txt && cd ..
# run in the background:
(cd api && .venv/bin/uvicorn homesol.main:app --port 8000 --log-level warning)
serve -s web/out -l 3000 --no-clipboard
```

The API reads its keys from the environment (`api/.env` is optional). Record against the production build on port 3000, never `pnpm dev`: the dev server shows Next's "Issues" badge.

All Node tools run with `NODE_PATH=$(npm root -g)`, which has Playwright 1.56 and Chromium at `/opt/pw-browsers`.

## What is built and tested

| Piece | File | State |
|---|---|---|
| Recording harness | `tools/rec.cjs` | Tested. Xvfb 1920×1080, kiosk Chromium at 1.25× (CSS viewport 1536×864), ffmpeg x11grab 30 fps lossless RGB. In-page cursor with eased, slightly arced moves and a click ripple. Marks every action with its time in the capture (`<take>.marks.json`, already corrected by the capture's start offset). Cleans up ffmpeg and Xvfb if a take dies. |
| Example take | `tools/take-smoke.cjs` | Tested on the local fallback app; copy its shape for real takes |
| Graphics renderer | `tools/render.cjs` | Tested. Frame-exact (seeked, not real-time), about 5 frames a second; `--stills t1,t2` for layout checks; `--alpha` for overlays |
| Scenes | `graphics/{hook,problem,reveal,lower,callout,evidence,close}.html` | Laid out and checked as stills; parameters by `--p '<json>'` |
| Evidence figures | `tools/evidence_params.py` | Quotes `api/evals/runs/20261011-final-opus-sonnet/summary.txt` verbatim and asserts it |
| Music | `tools/music.py` | Rendered: 180.000 s, −20 LUFS, peak −5.5 dBFS, no clicks, fades to true silence. Not listened to by a person yet. |
| Assembler | `tools/assemble.py` | Tested on a 40 s timeline: exact frame count, dissolves, push-ins, alpha overlays, ducked music, loudness to −16 LUFS. Checks every clip against its source length. |
| Narration | `tools/narrate.py` | Written, untested: needs the Hugging Face hosts for the model |
| Property scouting | `tools/scout.py` | Written, untested: needs the Google key |
| Demo takes T1–T9 | `tools/take-demo.cjs` | Written, untested: needs the real data; rehearse each take and fill in `property.json` (outline, screen positions) |

## What remains, in order

1. **Check access** (above). Re-run `pnpm build` if the API address changed.
2. **Scout the property.** Run `demo/.venv/bin/python demo/tools/scout.py <lng> <lat> --grid 3 --step 60` on two or three residential sectors of Chandigarh (for example Sector 15 around 76.768, 30.744; Sector 21 around 76.774, 30.721; Sector 35 around 76.762, 30.722; confirm each on the map first). Pick by the criteria in the script's docstring. If Chandigarh's survey is BASE-only or no roof shows shade worth showing, try Delhi (distributor tariffs are in the policy data, so money figures need no bill amount), then Bengaluru. Keep spend to about 30 taps.
3. **Rehearse in the app** at that property: what Claude names the obstructions, the shade breakdown, how many panels, the plan and money figures with a realistic monthly use (300–400 units). Chandigarh has no distributor data in `policies.json`, so type a bill amount too (about ₹7 a unit). Choose an advisor what-if question that makes the specialist call `estimate_finances` (for example "What if I install 3 kW instead?") and check the answer quotes the calculator.
4. **Record takes T1–T9** from `demo_shot_list.md` with `tools/take-demo.cjs <property.json> [take]`. Seed `localStorage["homesol-survey"]` to start a take at the property without re-tapping. For the two map-only shots, hide the side panels with injected CSS (`aside { display: none }`), and say so in the shot list. Step the shadow slider with the keyboard (focus the "Time of day" slider, ArrowRight every 0.2 s) for a slower, smoother day than the play button. Record each take twice; keep the better.
5. **Fill the script.** Put the recorded figures into `demo_script.md`, then write `demo_assets/audio/lines.json` (`id`, `say`) with the narration as spoken (amounts in words). Generate with `tools/narrate.py`, read `durations.json`, and adjust wording or pauses until each beat fits.
6. **Render graphics** with final timings (`hook` with the property's stamp, `problem` card times matched to the narration, lower thirds and callouts at the real UI positions taken from the takes).
7. **Write `demo_assets/timeline.json`** and assemble: `demo/.venv/bin/python demo/tools/assemble.py demo/demo_assets/timeline.json demo/project_demo_final.mp4`. Durations minus dissolves must equal 180.
8. **QA**, all written down in the final report: ffprobe (duration 180.000, 1920×1080, 30/1, h264 + aac, 5400 frames); contact sheets every 5 s; first and last frames; check every caption against the frame under it; loudness about −16 LUFS with narration clearly above music; every claim checked against the claims table in `demo_script.md`.
9. **Deliver**: send the MP4 and the two Markdown files to the owner; report path, measured specs, the workflow shown, the tools used, remaining limits and the QA result.

## Honesty rules for this video

- Only show results the app produced in the recording. Never patch a figure in the edit.
- Cutting a wait is fine and disclosed (a dissolve, listed in the shot list). Speeding up a process is not used.
- The evidence card quotes the test run's file verbatim, with its caveat.
- If a feature fails on the day, fix the smallest thing if it is safe and in scope, or show a different working feature; say so in the report.
