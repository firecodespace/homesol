# homesol demo: shot list

Draft 1, 11 October 2026. "Recorded" fills in as takes are captured; each take's raw file and its timestamped markers (`<take>.marks.json`, written by `tools/rec.cjs`) live in `demo_assets/raw/`.

All footage is the real application, built for production (`pnpm build`, served from `web/out`) against the real API on this machine, recorded on a 1920×1080 virtual display at 30 fps (`ffmpeg x11grab`, lossless). The page is drawn at 1.25× so its text reads clearly at 1080p. The cursor is drawn inside the page because automated input does not move the system pointer; it follows every real mouse event the app receives.

Edits that change what the viewer sees are listed under "Edit" and disclosed here: waits are cut with a visible dissolve; two map-only shots hide the side panels with injected CSS so the real map fills the frame. No result is staged, replaced by a still, or altered.

| # | Take | Purpose | Action in the real app | Edit | Recorded |
|---|---|---|---|---|---|
| T1 | `hook-shadows` | Hook (0:00–0:15) | Measured property, Shadows view, 21 December; the app's own time slider stepped by keyboard from about 07:00 to 17:30, one step every 0.2 s | Side panels hidden (map only); hook text overlay; slight slow push-in | — |
| T2 | `reveal-search` | Reveal (0:47–1:00) | Empty app; type the area into "Search your area"; pick the result; map flies in; Google's photo of the street loads | Cut the fly-in to its last 2 s if long | — |
| T3 | `tap-measure` | Demo (1:00–1:16) | Tap the roof; "Measuring your property…"; outline, obstructions and results appear | Dissolve across the 5–30 s wait for Google's survey; callout on Area and Height | — |
| T4 | `names` | Demo (1:16–1:28) | After Claude's names arrive, point at two obstructions so their tooltips show name, distance, height, share of shade | — | — |
| T5 | `shade` | Demo (1:28–1:44) | Shadows view, step through the day; scroll results to "What shades it" and "When the panel positions are clear" | Callout on "What shades it" | — |
| T6 | `panels` | Demo (1:44–1:53) | Year's sun view; point at a planned panel; "Where the panels go" card | — | — |
| T7 | `plan` | Demo (1:53–2:15) | Type monthly units (and bill amount if the distributor has no tariff data); plan card; scroll through "What it generates" and "Cost and savings" notes | Callout on the plan card | — |
| T8 | `advisor` | Proof (2:15–2:30) | Type a what-if question in "Ask a question"; the answer appears in "Answers" | Dissolve across the agent's 7–15 s wait; callouts on the matching figures | — |
| T9 | `close-hero` | Close (2:40–2:52) | The finished plan: Year's sun with planned panels | Side panels hidden (map only); slow push-in | — |

## Graphics (rendered from `graphics/*.html` by `tools/render.cjs`)

| Scene | Used at | Content |
|---|---|---|
| `hook` (alpha) | 0:00–0:15 over T1 | Three statements; date and place stamp |
| `problem` | 0:15–0:40 | Four questions, then the "today" line |
| `reveal` | 0:40–0:47 | Wordmark, tagline, four steps |
| `lower` (alpha) | over demo takes | Short captions, bottom left |
| `callout` (alpha) | over demo takes | Amber ring and label on one part of the real UI |
| `evidence` | 2:30–2:40 | The advisor test run's figures, quoted verbatim from `api/evals/runs/20261011-final-opus-sonnet/summary.txt` by `tools/evidence_params.py` |
| `close` | 2:52–3:00 | Closing statement, wordmark, what it is built with |

## Audio

| Asset | Source |
|---|---|
| Music | `tools/music.py`: original, synthesised from scratch (no samples), 180.000 s, sections on the brief's beats |
| Narration | Kokoro-82M (Apache-2.0), voice `af_heart`, generated locally from `demo_script.md` |
