# homesol demo: shot list and production notes

Final, 11 October 2026, for `project_demo_final.mp4`. The full edit decision list is `demo_assets/edl.md`; the machine-readable edit is `demo_assets/timeline.json`.

## How the footage was captured

- **The real application**, built for production (`pnpm build`, served from `web/out`) and talking to the real API on this machine with the owner's Google and Bedrock keys. Nothing in the footage is staged or replaced by a still.
- **Recording:** headed Chromium in kiosk mode on a 1920×1080 virtual display (Xvfb), captured by `ffmpeg x11grab` at 30 fps, lossless RGB. The page is drawn at 1.25× (1536×864 CSS pixels) so its text reads at 1080p: this is native 1080p capture, not an upscale.
- **Cursor:** automated input does not move the system pointer, so a cursor is drawn inside the page, following every real mouse event the app receives, with a ripple on each press. Moves are eased and slightly arced.
- **Timing:** every action is logged with its time in the capture (`*.marks.json`), corrected by the capture's measured start offset; the edit cuts to those marks.

## Property

A flat-roofed home in a residential sector of Chandigarh (roof B in `demo_assets/rehearsal/`), chosen after rehearsing two roofs: one dominant cause of shade (a tree cluster, 56%) makes the clearest story. Its survey is Google's satellite tier (BASE), imagery dated 8 April 2025. The home's coordinates in the location card are blurred throughout; no street address is shown.

## Takes used

| Take | File | Length | What it shows | Used |
|---|---|---|---|---|
| Workflow | `raw/workflow/workflow_2.mkv` | 134.4 s | One continuous run of the whole flow: tap, measure, Claude's names and tooltips, the day's shadows, what shades it and when, panels, electricity, the plan, cost and savings, the advisor's what-if and its answer | 0:46–2:36, in nine segments |
| Hook | `raw/hook/hook_3.mkv` | 19.0 s | Map only, Shadows view, 21 December stepped from 07:00 | 0:00–0:15.6 |
| Close | `raw/close/close_1.mkv` | 15.0 s | Map only, the finished plan in Year's sun | 2:46.4–2:53.4 |

Earlier takes: `workflow_1` (map tooltips missed their targets; tooltip positions were then measured with `tools/scan-tips.cjs`), `hook_1` and `hook_2` (roof centred under the caption, then an over-pan that exposed the photo's edge).

## Segments

| Film | Segment | Source | Purpose |
|---|---|---|---|
| 0:00.0 | Hook | hook_3 from 1.15 s | Shadows across one real roof through a winter day |
| 0:15.0 | Problem | graphics `problem` | The four questions; today's process |
| 0:40.0 | Reveal | graphics `reveal` | What homesol is, in one line |
| 0:46.0 | Tap and measure | workflow 0.6–33.9 s | The app, the tap, the measured roof, Claude's names |
| 1:18.9 | Shadows | workflow 34.8–48.4 s | The simulation stepping through 21 December |
| 1:32.1 | What shades it | workflow 48.6–60.6 s | Shade traced to each cause; clear-of-shadow hours |
| 1:43.7 | Panels | workflow 62.9–70.5 s | Where panels fit in good sun |
| 1:50.9 | Plan | workflow 71.8–87.6 s | Electricity entered; the plan; a planned panel's tooltip |
| 2:06.3 | Money | workflow 90.2–102.8 s | Generation, cost, subsidy, payback, and where each came from |
| 2:18.5 | Ask | workflow 104.9–113.5 s | The what-if question to the advisor |
| 2:26.5 | Answer | workflow 122.2–131.8 s | The advisor's answer |
| 2:35.6 | Evidence | graphics `evidence` | The advisor test run, quoted from its summary file |
| 2:46.4 | Close | close_1 from 0.5 s | The finished plan on the roof |
| 2:52.8 | End card | graphics `close` | Statement, wordmark, what it is built with |

## Edits that change what the viewer sees (disclosed)

- **Waits cut with dissolves:** the advisor took about 14 s to answer; the middle 8.7 s are cut (2:26.5). Google's measurement took about 6 s and is shown in full.
- **Map-only shots** (hook and close): the side panels, header, controls row and zoom buttons are hidden with injected CSS so the real map fills the frame. The map, shadows, panels and outlines are the app's own rendering.
- **Privacy:** the location card's coordinates are blurred in every app shot.
- **Slow push-ins** on the hook (about 8%) and the close (about 11%).
- **NASA POWER sunlight data** came from NASA's own mirror on AWS Open Data (`s3://nasa-power`, CERES SYN1deg climatology), because this environment cannot reach `power.larc.nasa.gov`. `tools/nasa_power.py` extracted the 1-degree cells and the recorder answered the app's request with that cell's values in the API's JSON shape (`routeNasa` in `tools/rec.cjs`). This is the CERES SYN1deg climatology POWER publishes for this parameter, monthly means in W/m² converted to the API's kWh/m²/day; it could not be compared with the API's own response, because that host is blocked here.
- **Blocked services, visible in the app:** Esri's base imagery and the Photon address service are blocked here. Google's own photo covers the property, so the map is full; but the location card shows coordinates (blurred) instead of an address, and the electricity company reads "Another company", so savings are priced from the typed bill.
- **Household figures** (350 units, ₹1,900 a month) are example inputs, introduced in the narration with "Say".

## Graphics (rendered by `tools/render.cjs` from `graphics/*.html`, frame by frame)

| Scene | Film | Content |
|---|---|---|
| `hook` (overlay) | 0:00–0:15.6 | Three statements over the footage, left scrim |
| `problem` | 0:15–0:40.6 | Four question cards timed to the narration; the "today" line |
| `reveal` | 0:40–0:46.6 | Wordmark, tagline, four steps |
| `lower` (three captions) | 0:59.6, 1:07.6, 2:20.4 | Kicker and one line, top of the map, clear of tooltips and results |
| `callout` (three rings) | 1:35.6, 1:59.3, 2:15.7 | Amber ring and label on the real UI: the top shade cause, the plan, the money notes |
| `evidence` | 2:35.6–2:46.8 | 789/790, 57/57, 81/81 and the summary file's lines, verbatim, with its caveat |
| `close` | 2:52.8–3:00 | Closing statement, wordmark, what it is built with |

## Audio

| Asset | Source |
|---|---|
| Narration | Kokoro-82M (Apache-2.0) via kokoro-onnx, voice `af_heart`, run locally; model files from kokoro-onnx's GitHub release. Three words corrected for Indian pronunciation (Chandigarh, Surya, lakh) |
| Music | `tools/music.py`: original, synthesised from scratch (no samples, no third-party material), 96 BPM, sections on the story beats |
| Mix | `tools/mix.py`: one gain for all narration lines; music about 6 dB under the voice in pauses and about 12 dB under it while speaking, with smooth ramps and a 1.6 kHz cut; two-pass loudness normalisation to −16 LUFS (linear) and a −1.5 dBTP limit |
