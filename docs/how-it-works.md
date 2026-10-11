# How homesol works

A reference for tuning and troubleshooting. Each section says what the system does, how it works step by step, which settings control it, how far it has been tested, its known limits, and what to check when it misbehaves.

Last updated 11 October 2026.

## Contents

1. [The big picture](#1-the-big-picture)
2. [Map and imagery](#2-map-and-imagery)
3. [Finding the roof from a tap](#3-finding-the-roof-from-a-tap)
4. [Sun on the roof: measured (Google)](#4-sun-on-the-roof-measured-google)
5. [Sun on the roof: estimated (fallback)](#5-sun-on-the-roof-estimated-fallback)
6. [Height from a satellite shadow](#6-height-from-a-satellite-shadow)
7. [Obstruction detection (AI vision)](#7-obstruction-detection-ai-vision)
8. [Detection feedback](#8-detection-feedback)
9. [Phone skyline scan](#9-phone-skyline-scan)
10. [Electricity use and the bill reader](#10-electricity-use-and-the-bill-reader)
11. [System sizing](#11-system-sizing)
12. [Cost and savings](#12-cost-and-savings)
13. [Policy data](#13-policy-data)
14. [Advisor (AI chat)](#14-advisor-ai-chat)
15. [Voice questions](#15-voice-questions)
16. [Save and share](#16-save-and-share)
17. [Screen layout](#17-screen-layout)
18. [Deployment and configuration](#18-deployment-and-configuration)

---

## 1. The big picture

```
Browser (web/)                         API (api/, AWS Lambda)                External services
─────────────────                      ───────────────────────               ─────────────────
Map, outline, tools ── /picture ─────▶ google_solar.py ───────────────────▶ Google Solar API
                    ── /roof-at ─────▶ google_solar.py
                    ── /measured-sun ▶ google_solar.py
Fallback shade maths (in browser)
Sizing maths (in browser) ───────────────────────────────────────────────▶ NASA POWER (sunlight)
                    ── /bill ────────▶ bill.py ───────────────────────────▶ Amazon Bedrock (Nova Pro)
                    ── /detect ──────▶ detect.py ─────────────────────────▶ Amazon Bedrock (Nova Pro)
                    ── /feedback ────▶ feedback.py ───────────────────────▶ DynamoDB homesol-feedback
                    ── /finance ─────▶ finance.py + policy.py (data/policies.json)
                    ── /advise ──────▶ agents.py (Strands Agents) ────────▶ Amazon Bedrock (Nova Pro)
                    ── /transcribe ──▶ speech.py ─────────────────────────▶ Amazon Transcribe
                    ── /surveys ─────▶ surveys.py ────────────────────────▶ DynamoDB homesol-surveys
```

Two rules run through the design:

- **Models perceive and explain; code calculates.** Every number on screen comes from deterministic code. The AI models read images, read bills and write answers, and are given numbers rather than asked to work them out.
- **Measured beats estimated.** Where Google has surveyed a building, its measured shade is used and the hand-marked tools are optional. Where it has not, the app falls back to obstructions and the phone scan.

**Which shade source wins:** Google's measured sun map, if available for the spot. Otherwise the estimate from marked obstructions combined with the phone skyline scan. The two are not blended.

---

## 2. Map and imagery

**What it does.** Shows a satellite map, lets the user search for a place, and overlays Google's own photo of the property.

**How it works.**
- Base map: Esri World Imagery tiles, drawn with MapLibre (`web/src/components/MapView.tsx`).
- Address search: Photon (Komoot's free geocoder), limited to a bounding box around India (`web/src/lib/imagery.ts`).
- Google photo overlay: when the user is looking for their roof and zoomed in past level 16.5, the app calls `/picture` for the map centre and lays Google's photo over the base map (about 220 m across at 0.5 m per pixel).

**Why the overlay exists.** Google's height and sunlight data line up with Google's imagery, which sits roughly 5–10 m off Esri's in the places tested. Without the overlay, a tap on the Esri picture can select the neighbour's roof.

**Settings.**
| Setting | Where | Value |
|---|---|---|
| Zoom needed before a tap counts | `MapView.tsx` `PICK_MIN_ZOOM` | 16.5 |
| Photo radius and resolution | `google_solar.py` `PREVIEW_RADIUS_M`, `PREVIEW_PIXEL_M` | 110 m, 0.5 m |
| Delay after the map stops moving before fetching a photo | `MapView.tsx` | 700 ms |

**Limits.**
- The Google patch looks different from the surrounding Esri map and its edges visibly don't line up.
- Each photo fetch is a billed Google request. Panning to a new area fetches another.
- Esri tiles are used without an API key, which is acceptable for a demo but should be checked against Esri's terms before real traffic.
- Photon is a free community service with no uptime guarantee.

**Troubleshooting.**
- *Map is blank or slow:* Esri tiles are loading. The Google photo and the tiles load independently.
- *No Google photo appears:* check the `/picture` response. `available: false` carries a reason (no key, or Google has no data there).

---

## 3. Finding the roof from a tap

**What it does.** The user taps their roof; the app outlines that roof and measures its height. Code: `find_surface` in `api/homesol/google_solar.py`, endpoint `/roof-at`.

**How it works.**
1. Fetch Google's height raster (DSM, metres above sea level, 0.25 m per pixel) and building mask for 60 m around the tap.
2. **Grow the surface.** Starting at the tapped pixel, add neighbouring pixels while the height changes by no more than 0.3 m per pixel and stays within 2 m of the tapped height. A flat roof ends where the height drops to the ground or steps to a neighbour, so this traces one roof even in a terrace of joined buildings.
3. **Measure height.** Roof height is the surface's median height minus the ground beside it (the lowest 5% of heights within 12 m of the surface).
4. **Decide what it is.**
   - Lower than 1.5 m above nearby ground: open ground, not a roof.
   - At least half of it marked as building in Google's mask: a roof (and the surface is clipped to the mask).
   - Not in the mask, but at least 70% of its edge ends in a height change of 1.2 m or more: a roof. Google's mask misses many Indian buildings, so walls are the second test.
   - Otherwise: not a building, most likely a tree canopy.
5. **Tidy and outline.** Small holes and threads are removed, the outer boundary is traced, and it is simplified to a polygon accurate to about 0.4 m.

**Settings** (all in `google_solar.py`).
| Setting | Value | Effect of raising it |
|---|---|---|
| `SURFACE_STEP_M` | 0.3 m | Surface spreads across bigger steps; more bleeding onto neighbours |
| `SURFACE_DRIFT_M` | 2.0 m | Tolerates steeper slopes; more bleeding onto trees |
| `ROOF_MIN_HEIGHT_M` | 1.5 m | More low structures called ground |
| `WALL_DROP_M` | 1.2 m | Stricter definition of a wall |
| `ROOF_WALL_SHARE` | 0.7 | Fewer unmasked surfaces accepted as roofs |
| `GROUND_SEARCH_M` | 12 m | Ground looked for further away |
| `TAP_RADIUS_M` | 60 m | Larger roofs fit; slower |

**Tested on.** Real taps in Bengaluru, Jaipur and Pune: flat roofs found, a joined terrace separated by level, a courtyard and a street reported as ground, tree canopies rejected. The wall rule was tuned on about fifteen real surfaces: roofs scored 0.74–0.92, tree canopies 0.27–0.49. Covered by unit tests on synthetic height data.

**Limits.**
- **Sloped and sheet-metal roofs are not found.** The surface is cut off by the drift limit and fails the wall test. The user is told to outline by hand.
- **One tap gives one level.** A house with terraces at two heights gets only the tapped one.
- **Roofs touching trees at the same height** can bleed into the canopy when the building is not in Google's mask.
- **Joined roofs at the same height** (two neighbours with level terraces and no parapet step) come out as one roof.
- Fifteen surfaces is a small tuning set. Expect wrong calls in building styles not yet seen.
- Takes about 5–7 seconds.

**Troubleshooting.**
- *"Open ground" on a real roof:* the ground estimate is too high, usually because everything within 12 m is also roof. Raise `GROUND_SEARCH_M`.
- *"Couldn't find a flat roof" on a flat roof:* the building is missing from Google's mask and its wall share fell below 0.7, often because a neighbour at the same height shares an edge. Check the response's `kind`, then try lowering `ROOF_WALL_SHARE`.
- *Outline covers two buildings:* lower `SURFACE_STEP_M`.
- *Wrong building selected:* the tap landed on Esri imagery instead of the Google photo; see section 2.

---

## 4. Sun on the roof: measured (Google)

**What it does.** Produces the coloured sun map and the "share of full sun", "good for panels" and "room for up to" figures from Google's survey. Code: `analyse` and `fetch` in `google_solar.py`, endpoint `/measured-sun`.

**How it works.**
1. Fetch Google's yearly sunlight raster ("annual flux", kWh per kW per year at each point, with shade from the 3D model already included) and the height raster for the outlined area plus 25 m.
2. **Find the surface inside the outline.** Sort the outline's pixels by height in half-metre bands; the fullest band is the surface's level. Pixels more than 1.5 m above it (stair rooms, tanks) or below it (ground next to the building) are left out. So a loosely drawn outline still describes one surface.
3. **Roof or ground.** If that level is under 1.5 m above nearby ground, the area is labelled open land.
4. **Scale to "share of full sun".** Each pixel's sunlight is divided by an open-sky reference: the 95th percentile of sunlight in the whole fetched area, or the surface's own 99th percentile if that is higher.
5. **Cells.** Pixels are merged into at most 2,500 square cells, each with an access value from 0 to 1, drawn on the map.
6. In the browser (`summariseCells` in `web/src/lib/solar/shading.ts`): a cell is good for panels at 0.85 or more; capacity is good area ÷ 10 m² per kW.

**Settings.**
| Setting | Where | Value |
|---|---|---|
| Pixel size requested | `google_solar.py` `PIXEL_M` | 0.25 m |
| Height band that counts as the surface | `LEVEL_BAND_M` | 1.5 m |
| Cell limit | `MAX_CELLS` | 2,500 |
| "Good for panels" threshold | `shading.ts` `USABLE_ACCESS` | 0.85 |
| Area per kW | `shading.ts` `AREA_PER_KW_M2` | 10 m² |

**Tested on.** Real data for Mumbai, Delhi, Bengaluru and rural Rajasthan. Open ground in Rajasthan read 98.5% of full sun and 0.3 m high, as it should. Google's open-sky figure for Mumbai (about 1,684 before losses) agrees with the NASA-based figure used for sizing (about 1,449 after 25% losses). Unit tests cover placement, the shaded/unshaded split, height, ground detection and structure exclusion on synthetic data.

**Limits.**
- **Not validated against a surveyed roof.** Google publishes no accuracy figure for its India data, which is satellite-derived at its lowest quality tier ("BASE").
- **Imagery dates vary** (2023 to 2025 in tests). A building put up since then casts no shade in the result.
- **The open-sky reference is relative to the neighbourhood.** In a tile where everything is shaded, percentages read too high.
- **The area-per-kW figure is the same for roofs and open land.** Ground-mounted arrays usually need more spacing.
- **Google's sunlight figure is used only for the shade pattern**, not for generation. Generation uses NASA data (section 11).
- Takes about 12 seconds on the live server.
- The live shadow slider does not use this data; it is hidden when Google data is in use.

**Troubleshooting.**
- *Everything reads 100%:* the outline's own best pixel set the reference. Normal for an open roof.
- *"Open land" on a real roof:* same cause and fix as in section 3.
- *`available: false`:* the reason is in the response. "Google has no 3D survey of this location yet" is a real coverage gap; anything mentioning decoding is a file-format problem (the reader supports deflate-compressed, north-up UTM files only).

---

## 5. Sun on the roof: estimated (fallback)

**What it does.** Where Google has no data, estimates the same sun map from obstructions the user marks and the phone skyline scan. Runs entirely in the browser. Code: `web/src/lib/solar/shading.ts`, `sun.ts`.

**How it works.**
1. The roof is treated as a flat surface at `floors × 3 m`.
2. Each obstruction is a vertical block: its outline, extruded to its height. Heights given "above the ground" have the roof height subtracted.
3. The roof is covered with a grid of cells (at least 0.5 m, at most 2,500 cells).
4. Sun positions are sampled every 30 minutes on the 21st of each month, when the sun is at least 5° up (SunCalc library).
5. For each cell and each sample, a line is drawn from the cell towards the sun for a distance of `height ÷ tan(sun elevation)`. If it crosses an obstruction's outline, the cell is shaded then.
6. If a skyline scan exists and the sun is below the scanned skyline in that direction, the whole roof is shaded for that sample.
7. Samples are weighted by the sine of the sun's elevation (high sun counts more). A cell's access is its lit weight ÷ total weight.

**Shadow preview.** The sliders pick a month and time; each obstruction's shadow outline is drawn for that moment.

**Limits.**
- **Only as good as what is marked.** An unmarked neighbour casts no shade.
- **Flat roofs only.**
- **Clear-sky geometry.** No clouds or monsoon in the shade pattern (they are in the generation figures, section 11).
- **Blocks, not shapes.** A tree is a solid prism.
- Times are in India Standard Time for all locations.

---

## 6. Height from a satellite shadow

**What it does.** Gives an obstruction's height from two clicks: the foot of the corner casting a shadow, and the shadow's tip. Code: `web/src/lib/solar/shadowHeight.ts`.

**How it works.**
1. Look up the capture date of the Esri image at that spot (Esri's metadata service). Only the date is published, not the time.
2. **Solve the time from the shadow.** A shadow points directly away from the sun, and on a given day each sun direction happens at one moment. The code scans that day minute by minute for the moment the sun was opposite the drawn shadow.
3. That moment gives the sun's elevation. Height = shadow length × tan(elevation).
4. A range is shown assuming each click is off by up to 0.75 m.

**Warnings shown.** Shadow direction impossible for that date (off by more than 4°); solved time outside 9:00–13:30 solar time, when imaging satellites don't normally pass; shadow shorter than 3 m.

**Limits.**
- **Never checked against a building of known height.**
- Uses Esri's imagery and date, not Google's. Do the clicks on the Esri map, with the Google photo not covering the shadow.
- Both clicks must be on the same level. A shadow falling across roofs of different heights gives a wrong answer.
- Esri's date is for a mosaic and can be wrong for a given spot; the time-of-day warning is the signal for that.

---

## 7. Obstruction detection (AI vision)

**What it does.** Proposes obstructions from the satellite picture. Now a fallback under "Improve the shade estimate", for places without Google data. Code: `web/src/lib/detect/`, `api/homesol/detect.py`, endpoint `/detect`.

**How it works.**
1. The browser stitches Esri tiles into a 768 × 768 picture of the roof plus 25 m, north up, with the roof outlined in yellow.
2. It also works out which way shadows should point, assuming the image was taken at 10:30 solar time on its capture date.
3. The picture and that hint go to Amazon Nova Pro with a system prompt describing what to look for (stair rooms, tanks, taller neighbours, trees) and a tool it must call with its findings: kind, label, on the roof or not, outline, optional shadow base and tip, and a typical-size height guess. Positions are on a 0–1000 grid.
4. The browser converts positions to map coordinates. If the model gave a shadow, the height is computed by the section 6 method and kept only if it raises no warnings; otherwise the model's guess is used.
5. Each result is shown as a suggestion for the user to confirm or remove.

**Settings.** Model: `BEDROCK_VISION_MODEL_ID` (default `us.amazon.nova-pro-v1:0`). Prompt: `SYSTEM` in `detect.py`.

**Tested on.** Two roofs in Mumbai. It returned rough boxes for some neighbours, missed objects on the roof itself, and gave no usable shadow points. Nova 2 Lite found nothing on the same roof.

**Limits.**
- **Weak.** Outlines are rough boxes and rooftop objects are missed.
- No accuracy has been measured; that is what section 8 collects data for.
- Uses Esri imagery, so its positions carry the Esri–Google offset.
- Claude models are not available on this AWS account, so the comparison planned with Claude has not been run.

---

## 8. Detection feedback

**What it does.** Records a person's verdict on each detected obstruction, to measure detection and eventually train a better model. Code: `api/homesol/feedback.py`, `web/src/lib/feedback.ts`.

**How it works.**
- Each `/detect` run is stored with what the model reported and gets an id.
- "Yes, it's there" stores a *confirmed* verdict with the final (possibly corrected) outline, type and height.
- "No, remove it" stores a *rejected* verdict.
- An obstruction drawn by hand after a run stores a *missed* verdict.
- `GET /feedback/summary` reports counts, precision (confirmed ÷ judged) and recall (confirmed ÷ confirmed plus missed).

**What is stored.** Outlines, heights, types and the roof outline as map coordinates. No names or contact details, and no satellite pixels (the imagery belongs to its provider; coordinates allow re-fetching under a proper licence).

**Limits.**
- **No model is trained.** This only collects labels. Training becomes worthwhile after a few hundred judged roofs.
- A user who ignores a suggestion without pressing either button leaves no verdict.
- "Missed" counts anything drawn after a run, including things the user would have drawn anyway.
- Zero real verdicts have been collected so far.

---

## 9. Phone skyline scan

**What it does.** Standing on the roof, the user traces the tops of surrounding buildings and trees with the phone camera. The result is a skyline: for each compass direction, how high the sky is blocked. Code: `web/src/components/HorizonScan.tsx`, `web/src/lib/solar/horizon.ts`.

**How it works.**
1. The browser asks for motion-sensor access (required on iPhones) and the rear camera.
2. Orientation readings (compass heading, tilt, roll) are converted to the direction the rear camera points: a compass bearing and an angle above the horizon. On iPhones the compass heading comes from `webkitCompassHeading`; on Android from the absolute orientation event.
3. Readings are smoothed (each new reading counts 35%) to steady compass jitter.
4. While the button is held, each reading writes the angle into a 5°-wide compass slot, replacing what was there. Untraced slots count as open sky.
5. A chart shows the skyline against the sun's paths in June, March and December.
6. In the shade estimate (section 5), the roof is in shade whenever the sun is below the skyline in its direction.

**No AI is involved.** The camera is only a viewfinder; nothing is recognised in the image.

**Limits.**
- **Never run on a real phone.** It has only been driven with simulated sensor readings. Real compass behaviour, the iPhone permission prompt and the camera are unverified.
- Needs HTTPS (the deployed site has it).
- Assumes the phone is held upright in portrait.
- Measured from one standing point at eye level, so it understates shade at panel height and treats the whole roof alike.
- Compasses are pulled off by metal railings and tanks; magnetic versus true north is not corrected (under about 2° across India).
- **Ignored when Google data is in use.**

**Troubleshooting.**
- *"This device has no compass or tilt sensor":* no orientation reading arrived within 2.5 seconds. On a phone, check the site has motion permission.
- *Skyline rotated:* compass calibration; move the phone in a figure of eight and rescan away from metal.

---

## 10. Electricity use and the bill reader

**What it does.** Gets the household's monthly units, bill amount, electricity company and sanctioned load, either typed or read from a photo of the bill. Code: `web/src/components/BillUpload.tsx`, `api/homesol/bill.py`, endpoint `/bill`.

**How the bill reader works.**
1. The browser shrinks the photo to at most 1,800 pixels on its long side and sends it as a JPEG.
2. Amazon Nova Pro reads it with a system prompt explaining what each figure means on an Indian bill, and must call a tool with: units consumed, bill amount (before arrears), billing days, distributor name, state, sanctioned load, and any printed monthly history. It is told to leave out anything it cannot read and not to report personal details.
3. Code then turns that into monthly figures (`to_monthly`):
   - If the bill prints at least three earlier months, units are the average of those and this bill.
   - Otherwise this bill's units, scaled to 30 days if the billing period is 20–100 days (some distributors bill every two months).
   - The bill amount is scaled to match, so the price per unit stays the bill's own.
4. The distributor is matched by words in its name (for example "mahavitaran", "bses", "bescom", "dgvcl"), falling back to the state only when no name was read.
5. The fields are filled in, and the user is asked to check them.

**Nothing is stored.** The photo is read once.

**Tested on.** Two mock bills generated for the purpose (one bilingual and tilted). Both read correctly. The monthly-figure logic has unit tests.

**Limits.**
- **Not tested on a real bill photo.** Real bills are creased, lit unevenly and vary widely by distributor.
- Only four distributor families are recognised by name.
- A bill with a non-typical month (summer peak) and no printed history gives a non-typical figure.
- The model can still misread a number; the app shows what it read for that reason.

---

## 11. System sizing

**What it does.** Works out the system size that matches the household's use, and how much it will generate each month. Runs in the browser. Code: `web/src/lib/solar/sizing.ts`, `web/src/lib/useSizing.ts`.

**How it works.**
1. Fetch long-term average sunlight for the location for each month from NASA POWER (25-year satellite climatology, kWh per m² per day on a flat surface). This includes clouds and the monsoon.
2. Units per kW in a month = sunlight × days × 0.75 × solar access, where solar access is the average over the good-for-panels cells (sections 4 and 5).
3. Panels wanted = yearly use ÷ yearly units per kW ÷ 0.55 kW per panel, rounded up.
4. Panels that fit = roof capacity ÷ 0.55, rounded down. The smaller of the two is the system.
5. The result says whether the roof or the usage was the limit.

**Settings** (`sizing.ts`).
| Setting | Value | Meaning |
|---|---|---|
| `PERFORMANCE_RATIO` | 0.75 | Share of sunlight reaching the meter after heat, dust, wiring and inverter losses |
| `PANEL_KW` | 0.55 | Rated output of one panel |

**Limits.**
- **Flat-panel sunlight.** Panels tilted towards the south gain a few percent, which is not counted, so generation is slightly understated.
- **One performance ratio for all of India.** Hot, dusty sites do worse.
- **Sized to yearly use.** In states that pay little for monthly surplus (Karnataka), a slightly smaller system can pay back faster; the app does not optimise for that.
- NASA's grid is coarse (roughly 50–100 km), so local haze or hills are not seen.

---

## 12. Cost and savings

**What it does.** Price, subsidy, bill before and after, first-year savings, payback and 25-year savings. Code: `api/homesol/finance.py`, endpoint `/finance`. The same code serves the dashboard and the advisor.

**How it works.**
1. **Price.** The vendor's quote if given; otherwise system size × ₹60,000 per kW, with a range of ₹47,000–73,000 per kW.
2. **Subsidy.** PM Surya Ghar: ₹30,000 per kW for the first 2 kW, ₹18,000 for the third, capped at ₹78,000, and never more than the price.
3. **Pricing a month's bill.**
   - If the household gave their bill amount: units × their own average rate.
   - Otherwise the distributor's tariff: each slab's units at that slab's rate, plus the fixed charge (flat, per kW of sanctioned load, or by load band, depending on the distributor), then any percentage surcharge.
4. **Net metering, month by month.**
   - *Annual settlement* (Maharashtra, Delhi): solar units offset that month's use; extra units carry forward as credit; what is left at year end is paid at the surplus rate.
   - *Monthly settlement* (Karnataka, Gujarat): each month's extra units are paid at the surplus rate and nothing carries forward.
5. **Savings** = bill before − bill after + surplus payments.
6. **Payback and 25 years.** Each year's savings shrink 0.5% (panel ageing) and grow 2% (assumed tariff rise). Payback is when cumulative savings reach the net cost.

**Settings** (`finance.py`).
| Setting | Value |
|---|---|
| `SYSTEM_LIFE_YEARS` | 25 |
| `PANEL_DEGRADATION` | 0.5% a year |
| `TARIFF_ESCALATION` | 2% a year (an assumption, not a forecast) |
| `DEFAULT_LOAD_KW` | 3 kW, used when the sanctioned load is unknown |

**Limits.**
- **Left out of savings:** fuel adjustment charges (except Gujarat's, which are included), electricity duty, Delhi's monthly power-purchase surcharge and its low-usage subsidy. Real savings are usually somewhat higher.
- **Left out of costs:** maintenance, a replacement inverter, loan interest, net-meter fees.
- **Using the household's own bill amount** prices every unit at their average rate. Solar removes the most expensive units first, so this understates savings.
- **The price per kW is a market range from installer guides**, not an official benchmark.
- State top-up subsidies are not included.
- Runs the year from January, not from the distributor's settlement month, which shifts carry-forward slightly.

---

## 13. Policy data

**What it is.** One file, `api/data/policies.json`, holding the central subsidy, the price range, and for each distributor its tariff and net-metering terms. Every entry has a `source` link and a `verified` flag. Loaded by `api/homesol/policy.py`.

**Coverage and confidence.**
| Distributor | Tariff | Net metering |
|---|---|---|
| MSEDCL (Maharashtra) | From the MERC order of 25 March 2026 | Carry-forward rule from MERC's 2019 regulations; the ₹2.82 surplus rate is from trade press only |
| Delhi (BSES, Tata Power-DDL) | DERC schedule of 2021, still in force | Rule from the distributor's FAQ; surplus rate unknown, so surplus counts as zero |
| BESCOM (Karnataka) | KERC order of March 2025 for 2026-27 | From KERC's August 2026 regulations and tariff order |
| Gujarat state DISCOMs | GERC schedule from 1 April 2026, with fuel surcharge | ₹2.25 from summaries of the 2021 policy; not confirmed for 2026 |

**How a property is matched.** The roof's location is reverse-geocoded to a state (Photon), and the state maps to a distributor (`STATE_TO_DISCOM` in `policy.py`). The user can change it.

**Limits.**
- **Four distributor families only.** Everyone else must enter their bill amount.
- **One distributor per state.** Mumbai's Adani, Tata and BEST customers, and Gujarat's Torrent customers, are mapped to the state distributor.
- **Hand-maintained.** Tariffs change yearly and some surcharges monthly. The file's `as_of` date shows when it was last checked.
- MSEDCL's top slab (above 500 units) came from a table that extracted poorly and should be re-read from the order.

**To add or update a distributor:** edit `policies.json` (copy an existing entry's shape), add the state to `STATE_TO_DISCOM`, add name keywords to `DISTRIBUTOR_NAMES` in `bill.py`, run the tests, redeploy.

---

## 14. Advisor (AI chat)

**What it does.** Answers the household's questions about their own plan in English, Hindi or Hinglish. Code: `api/homesol/agents.py`, endpoint `/advise`. Built with the Strands Agents SDK on Amazon Nova Pro.

**How it works.**
1. The browser sends the question, the conversation so far, and a "survey": roof figures, obstructions, household inputs and the recommended system.
2. The server writes a **fact sheet** (`fact_sheet`): every figure as a labelled sentence with its period, for example "Electricity bill today: Rs 37,992 PER YEAR (about Rs 3,166 a month)". Money figures come from the section 12 code. Caveats are listed at the end.
3. Three agents are built for the request:
   - **Advisor.** Talks to the household. Has the fact sheet and two specialists as tools.
   - **Site analyst.** Explains roof, shade and placement. Has the fact sheet in its prompt.
   - **Policy and finance analyst.** Has two tools: `lookup_policy` (returns the policy entries with sources) and `estimate_finances` (re-runs section 12 for a different size or a vendor quote).
4. **The tools are bound to the survey.** The model cannot supply usage, generation or the distributor; it can only ask for a different system size or quote. This is what stops wrong figures.
5. The answer is cleaned in code (`clean_answer`): reasoning tags, markdown symbols and any web link not on a site the policy data cites are removed.

**Prompt rules** (in `ADVISOR_PROMPT`): answer in the question's language; first sentence answers the question; three or four facts with their numbers; one next step; under 150 words; plain text; say so when homesol has no data and never estimate or give made-up examples; no comparisons with other investments; flag an out-of-range quote.

**Test set.** `api/evals/` holds 44 questions across six households in three languages, with automatic checks (language, every figure traceable to the facts, length, no markdown, no leaked reasoning) and model-graded checks. Run with `api/.venv/bin/python api/evals/run.py`. Each run makes paid model calls.

| | Before fixes | After fixes |
|---|---|---|
| Pass every automatic check | 16 of 44 | 38 of 44 |
| Leaked reasoning text | 13 | 0 |
| Markdown symbols | 8 | 0 |

**Known remaining faults** (from the last run): one invented loan example with a made-up interest rate (the rule was tightened afterwards and not re-run); one Hinglish question answered in English; one made-up quote figure passed to the calculator; occasional mention of internal names.

**Limits.**
- **The model varies between runs.** One sample per question; differences of a few cases are noise.
- **The grader is the same model as the advisor**, and was seen passing answers it should have failed.
- The test households were written before the tariffs were corrected, so some descriptions are stale.
- No memory between sessions; the conversation is lost on reload.
- Roughly 7–13 seconds per answer.
- Anyone with the API address can call it; there is no login or rate limit, only a cap of 10 simultaneous requests.

**Troubleshooting.**
- *Wrong figure in an answer:* run the eval and look at `rupee_figures_traceable` and `figures_match_their_label`. Check the fact sheet first; if the figure is right there, it is a model slip.
- *"The advisor's model is unavailable":* a Bedrock error; the message carries Bedrock's reason.
- *Wrong language:* the language rule in `ADVISOR_PROMPT`.

---

## 15. Voice questions

**What it does.** Turns a spoken question into text in the question box. Code: `web/src/lib/audio.ts`, `api/homesol/speech.py`, endpoint `/transcribe`.

**How it works.**
1. The browser records from the microphone, then decodes the clip and resamples it to 16 kHz, 16-bit, mono.
2. The server streams it to Amazon Transcribe in the language the user picked (Indian English or Hindi) and returns the final text.
3. The text is put in the question box for the user to check and send.

**Limits.**
- **Tested only with computer-generated speech**, not a real microphone or real accents.
- **The language must be picked.** Automatic detection returned nothing on clips under about three seconds, so it is not used.
- No Hinglish mode; mixed speech is transcribed in whichever language is selected.
- Clips are limited to 60 seconds. Answers are not read aloud.
- Needs HTTPS and microphone permission.

---

## 16. Save and share

**What it does.** Saves the survey and gives a link and QR code that open it on another device. Code: `api/homesol/surveys.py`.

**How it works.** The survey (roof outline, floors, obstructions, skyline scan, electricity inputs) is stored in DynamoDB under an 8-character code and expires after 90 days. Opening `?s=CODE` loads it. Each device also keeps its last survey in the browser's own storage.

**Limits.**
- **Anyone with the link can open it.** There are no accounts.
- **A saved link is a snapshot.** Changes made after saving need "Save again".
- The advisor conversation and the Google results are not saved; the Google results are re-fetched when the link opens.

---

## 17. Screen layout

Three areas, following Material Design 3 (`web/src/app/globals.css` holds the colour roles, type scale, shapes and component styles):

- **Left, tools** (`ToolsPanel.tsx`): everything the user does. Property, electricity, cost details, map display, improve the shade estimate, ask a question, save or share. Each has a title and a line saying what it does.
- **Middle, map** (`MapView.tsx`).
- **Right, results** (`ResultsPanel.tsx`): every number and how it was worked out. The plan, the roof, the sun, the system, cost and savings, the advisor's answers, the saved link. Nothing on this side is an input.

On screens narrower than 1,024 pixels the three stack: map, then tools, then results.

Tools appear as they become relevant: electricity after a property is chosen, cost details after electricity use is known.

**Limits.** The styling follows Material Design 3's roles and shapes but is hand-built, not Google's component library, so details such as ripple effects and floating labels are absent. There is a light theme only.

---

## 18. Deployment and configuration

| Piece | Where |
|---|---|
| Website | AWS Amplify Hosting, a static export of `web/` |
| API | AWS Lambda `homesol-api` (Python 3.13, arm64) behind a function URL, running the FastAPI app through Mangum |
| Saved surveys | DynamoDB `homesol-surveys` |
| Detection feedback | DynamoDB `homesol-feedback` |
| Deploy package | S3 `homesol-deploy-<account>` |

**To deploy:** `scripts/deploy.sh` from the repository root, with the AWS CLI logged in. It packages the API, updates the Lambda, passes the Google key from `api/.env` to the Lambda, builds the website against the API's address, and publishes it.

**Settings.**
| Setting | Where | Purpose |
|---|---|---|
| `GOOGLE_MAPS_API_KEY` | `api/.env`, Lambda environment | Google Solar API |
| `BEDROCK_AGENT_MODEL_ID` | Lambda environment, `api/.env` | Advisor model |
| `BEDROCK_VISION_MODEL_ID` | Lambda environment, `api/.env` | Bill reader and obstruction detection |
| `ALLOWED_ORIGINS` | Lambda environment | Which websites may call the API |
| `AWS_BEARER_TOKEN_BEDROCK` | `api/.env` only | Bedrock access when running locally; the Lambda uses its role |
| `NEXT_PUBLIC_API_URL` | Set by the deploy script at build time | API address the website calls |

**Limits and risks.**
- The API is public: no login and no rate limit, capped at 10 simultaneous requests. A budget alert on the AWS account is the backstop.
- The Lambda package is close to the 250 MB limit, which is why no image-codec library is included.
- A first request after idle time is slower while the Lambda starts.
- Region is `us-east-1`. Roof locations and bill photos are processed there.

**Tests.** `api/.venv/bin/python -m pytest api/tests` (38 tests) and `pnpm test` in `web/` (23 tests). Neither calls a paid service.
