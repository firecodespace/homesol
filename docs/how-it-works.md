# How homesol works

A reference for tuning and troubleshooting. Each section says what the system does, how it works step by step, which settings control it, how far it has been tested, its known limits, and what to check when it misbehaves.

Last updated 11 October 2026.

## Contents

1. [The big picture](#1-the-big-picture)
2. [Map and imagery](#2-map-and-imagery)
3. [Finding the surface](#3-finding-the-surface)
4. [Finding obstructions](#4-finding-obstructions)
5. [Naming obstructions (AI vision)](#5-naming-obstructions-ai-vision)
6. [The year's sun map](#6-the-years-sun-map)
7. [Shadow simulation](#7-shadow-simulation)
8. [Panel layout](#8-panel-layout)
9. [Where there is no 3D survey: the estimate](#9-where-there-is-no-3d-survey-the-estimate)
10. [Electricity use and the bill reader](#10-electricity-use-and-the-bill-reader)
11. [System sizing](#11-system-sizing)
12. [Cost and savings](#12-cost-and-savings)
13. [Policy data](#13-policy-data)
14. [Advisor (AI chat)](#14-advisor-ai-chat)
15. [Voice questions](#15-voice-questions)
16. [Save and share](#16-save-and-share)
17. [Screen layout](#17-screen-layout)
18. [Working anywhere in the world](#18-working-anywhere-in-the-world)
19. [Deployment and configuration](#19-deployment-and-configuration)

---

## 1. The big picture

```
Browser (web/)                              API (api/, AWS Lambda)            External services
──────────────                              ──────────────────────            ─────────────────
Tap or outline ───────── /site ───────────▶ site.py + google_solar.py ──────▶ Google Solar API
  ◀── site model: heights, sunlight, labels, photo, surface, obstructions
Shadow simulation   (lib/site/shadows.ts)
Panel layout        (lib/site/panels.ts)
Annotated photo ──────── /site/names ─────▶ naming.py ──────────────────────▶ Amazon Bedrock (Claude)
Sizing              (lib/solar/sizing.ts) ──────────────────────────────────▶ NASA POWER (sunlight)
                 ─────── /bill ───────────▶ bill.py ────────────────────────▶ Amazon Bedrock (Claude)
                 ─────── /finance ────────▶ finance.py + policy.py (data/policies.json)
                 ─────── /advise ─────────▶ agents.py (Strands Agents) ─────▶ Amazon Bedrock (Claude)
                 ─────── /transcribe ─────▶ speech.py ──────────────────────▶ Amazon Transcribe
                 ─────── /surveys ────────▶ surveys.py ─────────────────────▶ DynamoDB homesol-surveys
```

The centre of the app is the **site model**: one grid of measured heights, measured yearly sunlight and labels (surface, each obstruction) covering the property and about 45 m around it. The server builds it once from Google's 3D survey. Everything the user sees on the map, including the sun map, the moving shadows, what causes the shade and where each panel goes, is worked out from that one grid in the browser.

Three rules run through the design:

- **Models perceive and explain; code calculates.** Every number on screen comes from deterministic code. AI models read bills, name what the measurements found, and write answers. They are given numbers and never asked to work them out.
- **Measured beats estimated.** Where Google has surveyed a place, everything comes from measurement and nothing needs to be marked by hand. Where it has not, the app falls back to an estimate from hand-marked obstructions and says so on screen.
- **Every figure says where it came from.** Policy entries carry a source and a verified flag; the results panel says whether shade is measured or estimated.

---

## 2. Map and imagery

**What it does.** Shows a satellite map, lets the user search for any address in the world, and overlays Google's own photo of the property so that taps land on the right building.

**How it works.**
- Base map: Esri World Imagery tiles, drawn with MapLibre (`web/src/components/MapView.tsx`).
- Address search: Photon (Komoot's free geocoder), worldwide (`web/src/lib/imagery.ts`).
- Google photo overlay: while the user is looking for their property and zoomed in past level 16.5, the app calls `/picture` for the map centre and lays Google's photo over the base map (about 220 m across at 0.5 m per pixel). Once a property is chosen, the photo that came with the site model is shown.

**Why the overlay exists.** Google's height and sunlight data line up with Google's imagery, which sits roughly 5–10 m off Esri's in the places tested. Without the overlay, a tap on the Esri picture can select the neighbour's roof.

**What is drawn on the map** (controls in `MapControls.tsx`).
| Layer | What it shows |
|---|---|
| Year's sun | Each point of the surface coloured by its share of open-sky sunlight over a year |
| Shadows | Shadows at the chosen month and time, cast by the measured heights; a play button runs the day |
| Photo | Google's photo with nothing over it |
| Trace | The surface's outline, in white |
| Panels | Each panel as a rectangle: solid for the recommended system, faint for positions with room for more |
| What casts shade | Each obstruction outlined: red on the surface, blue for buildings, green for trees. Faint when it causes under 5% of the shade |

Pointing at an obstruction, or tapping it on a touch screen, shows its name, where it is, how far it stands above the surface, the share of shade it causes and a one-sentence explanation. The same on a panel shows whether it is in the plan and its share of sun.

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

## 3. Finding the surface

**What it does.** Works out which surface the panels would sit on and what kind it is: a flat roof, a sloped roof, open land or a hillside. The user either taps a roof or draws an outline round any area. Code: `api/homesol/site.py`, endpoint `/site`.

**From a tap** (`grow_surface`, `surface_at`, `from_tap`).
1. Fetch Google's height raster (metres above sea level, 0.25 m per pixel), building mask, yearly sunlight and photo for 60 m around the tap.
2. **First patch.** Starting at the tapped pixel, take neighbouring pixels within 3 m of the tap that are within 0.4 m of the tapped height.
3. **Follow the plane.** Fit a flat plane through the patch, then spread again from the tap across every connected pixel within 0.5 m of that plane. Repeat up to eight times until the surface stops growing. On a flat roof this covers the whole roof and stops at walls and at a neighbour's step. On a pitched roof it covers the one face that was tapped and stops at the ridge or hip, where the next face leaves the plane.
4. **Classify** (see below). A tap that lands on ground or on a tree canopy is refused with a reason, and the user is offered the outline tool.
5. If the surface runs off the edge of the data, fetch again, centred on the surface and wide enough to hold it.
6. Tidy pinholes and threads, trace the boundary, simplify it to a polygon accurate to about 0.4 m.

**From an outline** (`surface_in_outline`, `from_outline`). An outline drawn by hand is loose: it takes in the stair room, a strip of ground, a neighbour's corner, the far side of a ridge. An outline is accepted on any kind of surface, which is how open land and hillsides are surveyed.
1. **Find the plane most of the outline lies on.** Planes are fitted to patches about 3 m wide all over the outline (up to about 400 of them). Each is scored by how much of the whole outline lies within 0.3 m of it, and the best wins. On a flat roof every patch agrees. On an outline drawn across the ridge of a pitched roof, the patches on the larger face win; one plane fitted to everything would cut through both faces and describe neither.
2. **Settle it** by refitting to everything within 0.3 m, up to four times.
3. **A roof** (raised, by the test below): the surface is every outlined pixel within 0.5 m of that plane. The plane is not refitted with the wider band, which would tip it across a ridge.
4. **Ground**: rougher and gently curved, so the band widens to 0.75 m and the plane is refitted up to six times to settle on all of it.
5. What stands above the surface becomes an obstruction (section 4). The response also carries `covers`, the share of the outline the surface takes up. When a sloped roof covers under 70% of its outline, the results say the outline takes in more than one slope and that the plan is for the largest.

**Classifying the surface** (`describe`, `height_above_ground`).
- **Tilt and facing** come from the fitted plane. A tilt of 8° or more is "sloped". Facing is the downhill direction as a compass bearing.
- **Raised or ground.** Look at everything within 12 m of the surface. Ground runs on smoothly into its surroundings, even on a hillside, so the land around it lies on the same plane. A roof has ground well below its plane somewhere nearby. The surface is raised when the lowest 5% of its surroundings lie at least 1.5 m below its plane.
- The four kinds: `roof`, `sloped_roof`, `ground`, `sloped_ground`.
- **Is a raised surface really a building?** (taps only) Yes if at least half of it is in Google's building mask. If not, yes if at least 70% of its edge ends in a height change of 1.2 m or more. Google's mask misses many buildings, so walls are the second test. Otherwise it is most likely a tree canopy and is refused.
- **Area** is the footprint divided by the cosine of the tilt, so a sloped surface reports its true area.
- **Floors** for a roof are its height divided by 3 m.

**Settings** (all in `site.py`).
| Setting | Value | Effect of raising it |
|---|---|---|
| `SURFACE_SLOPE_LIMIT` | 1.2 m per m | Surface spreads across bigger steps; more bleeding onto neighbours |
| `LEVEL_BAND_M` | 0.4 m | First patch tolerates rougher surfaces |
| `FIRST_PATCH_RADIUS_M` | 3 m | Better plane fit on big flat roofs; on a hipped roof the patch wraps onto other faces |
| `PLANE_BAND_M` | 0.5 m | Tolerates bumpier or curved roofs; more bleeding across ridges |
| `OUTLINE_PATCH_M` | 3 m | Candidate planes are steadier on noisy data; small roof faces get no patch of their own |
| `OUTLINE_TIGHT_BAND_M` | 0.3 m | More forgiving of rough surfaces; a ridge is more easily averaged away |
| `OUTLINE_BAND_M` | 0.75 m | Outlined ground keeps rougher patches; low objects on it stop being obstructions |
| `SLOPED_TILT_DEG` | 8° | Fewer surfaces called sloped |
| `ROOF_MIN_HEIGHT_M` | 1.5 m | More low structures called ground |
| `WALL_DROP_M`, `ROOF_WALL_SHARE` | 1.2 m, 0.7 | Stricter test for an unmarked building |
| `GROUND_SEARCH_M` | 12 m | Ground looked for further away |
| `MIN_SURFACE_M2` | 8 m² | Small roofs refused |
| `TAP_RADIUS_M`, `SURROUND_M`, `MAX_RADIUS_M` | 60, 45, 110 m | Area fetched; larger is slower |
| `FINE_RADIUS_M` | 65 m | Above this radius the data is fetched at 0.5 m per pixel instead of 0.25 m |

**Tested on.** Real data: flat roofs in Bengaluru by tap and by outline (the two agree: 224 m² and 225 m², five floors up); a tap on a street tree, refused; open land in rural Rajasthan by outline ("Open land", 987 m²); a pitched roof in Palo Alto, one face by tap ("Sloped roof, 12° facing west") and an outline drawn across its ridge ("Sloped roof, 12° facing north", the larger face; before the patch method this read as a flat roof). Earlier tuning of the wall rule used about fifteen real surfaces: roofs scored 0.74–0.92, tree canopies 0.27–0.49. Unit tests on synthetic height data cover flat roofs by tap and by outline, a gabled roof face, an outline across a ridge, open ground, a hillside and an unmarked shed.

**Limits.**
- **One plan covers one plane.** A pitched roof has two to four faces and only one is planned at a time: the tapped one, or the largest inside an outline. A house with terraces at two heights gets only one of them. Each further face is a separate survey; they are not added together.
- **Sloped surfaces were tuned on few real examples** (one pitched roof, synthetic hillsides). Curved roofs, domes and very steep faces are untested.
- **Joined roofs at the same height** with no parapet step between them come out as one roof.
- **A roof touching a tree at the same height** can bleed into the canopy when the building is not in Google's mask.
- **Mountain land is treated as one plane.** Terraced or folded slopes are averaged, and the 0.75 m band may drop parts of rough ground.
- **Largest area is about 150 m across** (radius 110 m). Bigger plots must be surveyed in pieces.
- Usually takes 5–10 seconds, nearly all of it waiting for Google. The geometry itself takes about 0.2 seconds. **Google is occasionally much slower**: answers of 27 to 38 seconds were seen several times in testing, for no reason visible from outside. After 10 seconds the screen says it is still working. Each downloaded area is kept in memory for 20 minutes (`TILE_CACHE_SECONDS`, `TILE_CACHE_SIZE` in `google_solar.py`), so reopening the same property is immediate and is not billed again.

**Troubleshooting.** The `/site` response says what happened: `found: false` with `kind` of `ground`, `not_building` or `too_small`, or `available: false` with a reason.
- *"Open ground" on a real roof:* everything within 12 m is also roof, so no ground was seen. Raise `GROUND_SEARCH_M`.
- *Tap refused as "not a building" on a real roof:* the building is missing from Google's mask and its wall share fell below 0.7, often because a neighbour at the same height shares an edge. Lower `ROOF_WALL_SHARE`, or outline by hand.
- *Outline covers two buildings:* lower `SURFACE_SLOPE_LIMIT`.
- *Only a strip of a pitched roof is found:* the roof is rougher than the plane band (tiles, dormers). Raise `PLANE_BAND_M`.
- *Wrong building selected:* the tap landed on Esri imagery instead of the Google photo; see section 2.

---

## 4. Finding obstructions

**What it does.** Finds everything that could cast a shadow on the surface, and measures each one: outline, height above the surface, footprint, distance and direction. This is geometry on the height data. No AI model looks at a picture, so the same place always gives the same answer. Code: `find_obstructions` in `site.py`.

**How it works.**
1. **Height above the surface.** For every pixel, subtract the surface's plane from the measured height. (The plane is held within the surface's own height range so a tilted plane is not extended far beyond it.)
2. **The surface's footprint.** The surface with notches up to 2.5 m wide closed and holes filled, so a stair room at the roof's edge and a tank in the middle both count as inside it.
3. **Things standing on the surface.** Pixels inside the footprint, not part of the surface, more than 0.5 m above it. Connected pixels form one object, which is then tested for being several (`_split_structures`): it is sliced at rising heights from 1 m, a quarter of a metre at a time, up to 80% of its height; if at some height it comes apart into several cores of at least 0.5 m² each, it is that many structures, and each core spreads back down to its own foot. So a tank and a stair room joined by a low wall are two, while a room with an uneven top stays one. Objects under 0.75 m² are dropped.
4. **Things beside the surface.** Pixels outside the footprint more than 1 m above the surface. They are split into separate objects wherever the height steps by more than 0.75 m between neighbours (on lightly smoothed heights), which separates joined buildings of different heights while keeping a spiky tree canopy in one piece. Objects under 6 m² are dropped, and so is anything that rises less than 6° above the surface's horizon as seen from its nearest edge, since it cannot shade it usefully.
5. **Edge structures.** A neighbour that is small (up to 60 m²), low (up to 5 m) and has at least 40% of its edge against the surface is reclassified as standing on the surface, and split the same way as in step 3. This catches a stair room on the corner of a roof.
6. **First name, from measurements alone.**
   - On the surface: under 1.2 m is a low wall or raised edge; under 6 m² a water tank or small structure; over 40 m² a higher part of the building; 1.8 m or taller a rooftop room; otherwise a rooftop structure.
   - Beside it: in Google's building mask, or with a flat top (within 0.5 m of a plane), a neighbouring building; bumpy and over 150 m², "taller buildings or trees"; otherwise a tree.
7. **Label raster.** Every pixel gets a label: 0 nothing, 1 the surface, 2 and up each obstruction. The height data blurs every edge into a ring of pixels part-way up; those pixels cast shadows too, so each raised unlabelled pixel within 1.5 m of an obstruction takes its label.
8. At most 40 obstructions are kept: everything on the surface, then neighbours by how high they rise above the horizon.

**Settings** (`site.py`).
| Setting | Value | Effect of raising it |
|---|---|---|
| `STRUCTURE_MIN_M` | 0.5 m | Low parapets and pipes ignored |
| `STRUCTURE_SPLIT_M`, `STRUCTURE_CORE_M2` | 1.0 m, 0.5 m² | Touching structures are less readily told apart |
| `NEIGHBOUR_MIN_M` | 1.0 m | Fewer low neighbours |
| `EDGE_NOTCH_M` | 2.5 m | Larger edge structures counted as on the surface; narrow lanes may be swallowed |
| `MIN_ELEVATION_DEG` | 6° | Fewer distant obstructions listed |
| `EDGE_STRUCTURE_MAX_M2`, `_MAX_HEIGHT_M`, `_TOUCH` | 60 m², 5 m, 0.4 | Which neighbours are treated as part of the same building |
| `FLAT_TOP_ROUGHNESS_M` | 0.5 m | More unmarked neighbours called buildings instead of trees |
| `EDGE_BLUR_MIN_M`, `EDGE_BLUR_REACH_M` | 0.3 m, 1.5 m | How much of the blurred edge is credited to each obstruction |
| `MAX_OBSTRUCTIONS` | 40 | Longer list |

**Tested on.** Two Bengaluru roofs. On one, a stair room and a tank on the roof and neighbours and trees around it, with the shade attributed 39% / 33% / 24% / 3% across four obstructions and almost nothing left unattributed. On the other, the tallest in its street, one 51 m² block 2.1 m high on the corner of the roof causing 94% of the shade, and six neighbours that cause almost none. Unit tests cover a tank on a roof, structures joined by a lower wall, a stepped room, a taller neighbour, a tree and an unmarked shed.

**Limits.**
- **Resolution.** At 0.25 m per pixel (0.5 m for large areas), things narrower than about half a metre are missed: poles, railings, antennas, thin pipes, cables.
- **The height data runs things together.** A row of joined buildings at similar heights, or buildings with trees between them, can come out as one obstruction. That is why "taller buildings or trees" exists as a name. The same happens on a roof: in satellite-grade (BASE) data a stair room with tanks beside it can be one unbroken slab with no dip to split it at, and is then reported as one structure.
- **Height data has a date.** Anything built, grown or cut down since Google's survey is wrong. The date is shown in the results.
- **Trees are solid.** A canopy that lets half the light through is treated as a wall.
- **Building or tree is a judgement** from the mask and the roughness of the top. A tree pruned flat or a building with a cluttered roof can be misnamed. Section 5 gives a second opinion from the photo.
- The naming thresholds were set on Indian flat roofs. A chimney on a pitched roof will be called a "water tank or small structure" until section 5 renames it.

**Troubleshooting.**
- *Something on the roof is missing:* it is under 0.5 m tall or under 0.75 m², or the outline flow's 0.75 m band absorbed it. Check `obstructions` in the `/site` response.
- *The stair room is listed as a neighbouring building:* it is larger than 60 m², taller than 5 m, or touches the surface along under 40% of its edge. Adjust the three `EDGE_STRUCTURE_*` settings.
- *One huge obstruction covers the whole neighbourhood:* the heights step gently between buildings. Lower the 0.75 m split step in `find_obstructions`.

---

## 5. Naming obstructions (AI vision)

**What it does.** Tells the household what each measured obstruction is in words they recognise ("Stair room", "Water tank", "Neighbour's house to the south"), with one sentence on what it means for the panels. Code: `web/src/lib/site/naming.ts`, `api/homesol/naming.py`, endpoint `/site/names`.

**How it works.**
1. The browser takes Google's photo from the site model and draws on it: the surface outlined in white, each obstruction outlined and numbered (red on the surface, cyan beside it). It crops to the outlines plus 6 m and enlarges up to four times.
2. Only obstructions worth naming are sent: everything on the surface, and neighbours causing at least 2% of the shade, twelve at most, biggest cause of shade first.
3. The picture goes to Claude with each item's measured facts: on the surface or how far and which way, height above the surface, footprint, and share of the shade.
4. The prompt gives the model one job: say what each numbered thing is. It states that the measurements are facts, that the photo and the heights can be from different dates, and that when they disagree the measurements win and the confidence is marked low. It must answer through a tool with a name (two to five words), an explanation (22 words at most) and a confidence for every item.
5. Names appear in the map tooltips and the "What shades it" list. If the call fails, the names from section 4 stay. The request is made once per property and remembered for as long as the page is open.

**The model cannot change a measurement.** Outlines, heights, distances and shade shares are never sent back from the model.

**Settings.** Model: `BEDROCK_VISION_MODEL_ID` (default Claude Opus 4.6, `us.anthropic.claude-opus-4-6-v1`). Prompt: `SYSTEM` in `naming.py`. Limits: `MAX_ITEMS` 12, `MIN_SHARE` 0.02 in `naming.ts`.

**Tested on.** The Bengaluru roof, where it returned "Stair room or upper room", "Water tank or small room" and "Neighbouring buildings and trees".

**Limits.**
- **Tested on one roof.** No accuracy has been measured.
- Google's photo is 0.25–0.5 m per pixel; small things are a few pixels and the model is going mainly on the measurements. The confidence field says so.
- Names are English only.
- One paid model call per property, taking a few seconds; names arrive after the rest of the results.
- No Google photo, no names.

---

## 6. The year's sun map

**What it does.** Shows how much of the year's sunlight each point of the surface gets, and produces the "share of full sun" figure. Code: `build` in `site.py`; drawn by `MapView.tsx`.

**How it works.**
1. Google's "annual flux" raster gives measured yearly sunlight at each point (kWh per kW per year), with shade from its 3D model already included.
2. Each pixel is divided by an open-sky reference: the 95th percentile of sunlight across the whole fetched area, or the surface's own 99th percentile if that is higher. The result, 0 to 1, is the pixel's **access**.
3. The browser colours the surface by access. A point is "good for panels" at 0.75 or more (`GOOD_ACCESS` in `panels.ts`), the line Google's Project Sunroof draws for a viable roof.

**Used for.** The sun map, the share-of-full-sun figure, each panel position's access (section 8), and, through the open-sky reference, the scale of the generation figures (section 11).

**Tested on.** Real data for Mumbai, Delhi, Bengaluru, rural Rajasthan and Palo Alto. Open ground in Rajasthan read about 98% of full sun.

**Limits.**
- **Not validated against a surveyed site.** Google publishes no accuracy figure. The quality tier (HIGH, MEDIUM or BASE) is shown in the results; much of the world outside the US, Europe and Japan is BASE.
- **The open-sky reference is relative to the neighbourhood.** In a tile where everything is shaded, percentages read too high.
- **On a sloped surface, access mixes shade with tilt.** A north-facing slope reads low because of the way it faces, not because something shades it. That is correct for choosing where panels go, but the label says "share of full sun".
- A building put up since the survey casts no shade in the result.

---

## 7. Shadow simulation

**What it does.** Shows where shadows fall at any month and time, works out which obstruction causes how much of the shade, and reports the hours each month when the panel positions are clear. Runs in the browser on the measured heights. Code: `web/src/lib/site/shadows.ts`.

**How it works.**
1. **Grid.** The site model's heights are resampled to about 0.5 m per pixel, keeping the tallest point of each block and its label.
2. **One moment** (`castShadows`). The sun's direction and height above the horizon come from the SunCalc library. From each pixel a ray climbs towards the sun, one pixel at a time. The pixel is in shadow if the ray passes under the top of anything on the way. The ray starts 0.15 m above the pixel so that measurement noise casts no shadows. The sun counts only when it is at least 5° up.
3. **The map's shadow layer** is that calculation for the month and time on the scrubber, in the property's own time zone.
4. **A year** (`analyseShade`). Sun positions are sampled every half hour on the 21st of each month. Each sample is weighted by the sine of the sun's elevation, so high sun counts for more. For each sample and each tested pixel in shadow, the label of whatever blocked the ray is recorded.
5. **Results.**
   - *Lost*: the weighted share of the year's direct sun that the tested area loses.
   - *Blame*: the share of that loss caused by each obstruction. This is the percentage beside each item in "What shades it".
   - *Clear hours*: for each month, the first and last sample at which no more than 10% of the tested area is in shadow.
6. It runs twice: over the whole surface, and over only the pixels under the good panel positions.

**How it relates to the sun map.** Two independent measurements. The sun map (section 6) is Google's own calculation at each point, set against the best open spot nearby; it counts shade from everything around and also the surface's own edges and tilt, and it sets each panel's access. The simulation is homesol's and counts shadows alone; it adds what Google's figure cannot: when, and caused by what. So the two loss figures need not match. On one Bengaluru roof they were 16.9% (simulated) and 18.3% (Google); on a taller one nearby with a slight tilt and blurred edges, 3% and 14%.

**Settings** (`shadows.ts`).
| Setting | Value | Meaning |
|---|---|---|
| `shadowGrid` target pixel | 0.5 m | Finer is sharper and slower |
| `CLEARANCE_M` | 0.15 m | How far something must stand above the ray to block it |
| `MIN_SUN_ELEVATION` | 5° | Sun lower than this is ignored |
| Samples | every 30 minutes, 21st of each month | In `yearOfSun` |
| Clear-of-shadow threshold | 10% | In `analyseShade` |

**Tested on.** Unit tests check shadow direction and length against hand-worked geometry, and that blame lands on the right obstruction. Checked against Google's own loss figure on one roof (above).

**Limits.**
- **Clear-sky geometry.** Clouds, haze and monsoon are not in the shadows. (They are in the generation figures, section 11.)
- **Direct sun only.** Light from the rest of the sky is not modelled, so real losses are a little lower than simulated.
- **Only what is inside the model casts a shadow.** A tower or hill more than about 45 m beyond the surface is missing. At low sun such things matter.
- **A panel is treated as lying on the surface.** Tilted panels on frames stand up to half a metre higher and so see slightly less shade than shown.
- **Trees are solid** and the same in every season.
- **Agreement with Google has been checked on one roof.**
- On a sloped surface the surface's own shape casts shade on itself early and late in the day; that share is listed as "Steps and edges of the roof itself" or, on land, "The lie of the land".

**Troubleshooting.**
- *Speckled shadows on a clear roof:* height noise larger than the clearance. Raise `CLEARANCE_M`.
- *A large share of shade has no name:* edge pixels not credited to any obstruction. Raise `EDGE_BLUR_REACH_M` (section 4).
- *Shadows point the wrong way:* check the time zone shown under the scrubber (section 18).

---

## 8. Panel layout

**What it does.** Draws every panel as a rectangle of its real size in the place it would be fitted, and chooses which positions the recommended system uses. Code: `web/src/lib/site/panels.ts`.

**How it works.**
1. **Panel.** 2.278 m × 1.134 m, 550 W, laid long side along the row.
2. **Tilt and facing.**
   - *Flat roof or flat land:* tilted rows. Tilt is the latitude, kept between 10° and 25°. Panels face the equator (south in the northern hemisphere, north in the southern). On a roof, rows line up with the building: the building's dominant edge direction is found, and of its four directions the one nearest the equator is used.
   - *Sloped roof or hillside:* panels lie flush on the slope, at its tilt and facing.
3. **Row spacing** (tilted rows only). The gap behind each row is the length of the shadow of its top edge two and a half hours before solar noon on the shortest day, capped at three times the row's rise. Flush panels are 2 cm apart.
4. **Usable area.** Pixels labelled as the surface, at least 0.5 m from anything that is not: the edge, a rooftop structure, missing data.
5. **Fitting.** A grid of positions is laid over the usable area. A panel is placed only where its whole footprint is usable. Nine offsets of the grid are tried and the one fitting the most panels is kept.
6. **Access.** Each position's access is the mean of the sun map under it. Positions at 0.75 or more are **good**. The line was 0.85 until an unshaded north-facing slope in California, which gets 84% of the best sun nearby, was refused outright; 0.75 is Project Sunroof's line. Because panels are taken sunniest first, the lower line only matters when room is short.
7. **Order.** Good positions are put in the order a system would grow: the sunniest first, then always a neighbour of what is already placed, treating differences in sun under 3% as equal. So a system of any size is one tidy block and not the sunniest spots scattered about.
8. The sizing step (section 11) takes as many positions from the front of that order as the household needs. Those are drawn solid; the rest of the good positions are drawn faint as "room for more".

**Settings** (`panels.ts`).
| Setting | Value | Effect of raising it |
|---|---|---|
| `PANEL_LONG_M`, `PANEL_SHORT_M`, `PANEL_WATTS` | 2.278 m, 1.134 m, 550 W | Fewer, larger panels |
| `EDGE_SETBACK_M` | 0.5 m | Fewer panels near edges and structures |
| `GOOD_ACCESS` | 0.75 | Fewer positions count as good |
| `flatSurfaceTilt` range | 10–25° | Steeper panels, wider row gaps |
| `rowGap` time | 2.5 h before solar noon | Wider gaps, fewer rows |

**Tested on.** Bengaluru flat roof (rows aligned with the building, placed around the stair room and tank), Rajasthan open land (a block of rows facing south), Palo Alto pitched roof (flush on the west face). Unit tests cover a flat roof, a structure in the middle, good-first ordering, block growth, the southern hemisphere, a slope and a rotated building.

**Limits.**
- **A sensible layout, not an installer's drawing.** Real designs follow local fire and wind codes, structural points, inverter string lengths and walkways. The 0.5 m setback stands in for all of these; some places require 0.9 m or more on pitched roofs.
- **One panel size, one orientation.** Turning panels the other way round, or mixing orientations to fill gaps, would sometimes fit more.
- **One facing per surface.** East-west layouts, which fit more panels on flat roofs near the equator, are not considered.
- **Ground mounting is laid out like a roof.** Real ground arrays need foundations, access tracks and fencing.
- **Rows on a tilted-row layout shade each other outside the design hour.** That loss is not subtracted from generation.
- **A slope facing away from the sun still gets panels drawn** if its measured sun is good enough. The results then say which way it faces, how much less sun it gets than the best-facing surfaces nearby, and suggest trying another slope. Nothing checks that a very steep slope is buildable.
- Layout for a large plot (thousands of positions) takes a second or two.

**Troubleshooting.**
- *No panels on a roof that looks open:* the usable area is narrower than a panel once the setback is taken off, or the sun map is under 0.75 everywhere. The sun map shows which.
- *Panels at an odd angle:* the building's edge direction was misread from a ragged outline. Rows fall back to facing the equator when no clear direction covers 45% of the outline.
- *Chosen panels in two groups:* the good positions are in two separate areas and the first could not hold the system.

---

## 9. Where there is no 3D survey: the estimate

**What it does.** Google's survey does not cover everywhere. Where `/site` reports no data, the app says shade is estimated and offers hand tools. Runs in the browser. Code: `web/src/lib/solar/shading.ts`, `sun.ts`, `shadowHeight.ts`, `horizon.ts`; converted to the same site model shape by `modelFromCells` in `lib/site/model.ts`.

**How it works.**
1. The user draws the outline and gives the number of floors. The surface is treated as flat.
2. **Obstructions are marked by hand**, or proposed by the older AI detector (below). Each is a vertical block: its outline, extruded to its height.
3. **Height from a satellite shadow.** For an obstruction's height the user can click the foot of a corner and the tip of its shadow on the Esri image. The image's capture date comes from Esri's metadata. The code scans that day for the moment the sun was opposite the drawn shadow, takes the sun's elevation at that moment, and gives height = shadow length × tan(elevation), with a range assuming each click is off by up to 0.75 m. It warns when the shadow direction is impossible for that date, when the solved time is outside 9:00–13:30 solar time, or when the shadow is under 3 m long.
4. **Phone skyline scan.** Standing on the roof, the user traces the tops of the surroundings with the phone camera. Orientation readings give a compass bearing and an angle above the horizon, stored in 5° compass slots. No AI is involved; the camera is only a viewfinder.
5. **Shade.** The surface is covered with up to 2,500 cells. For each cell and each half-hourly sun sample, a line towards the sun is tested against each obstruction's block, and the sun is tested against the scanned skyline. A cell's access is its lit weight ÷ total weight.
6. The cells are turned into a site model with no heights, so the sun map, the panel layout and the sizing all work the same way. The shadow layer shows each marked block's shadow.

**The older AI detector** (`api/homesol/detect.py`, `/detect`). Sends a satellite picture to the vision model and asks for obstructions as boxes. It was weak on Nova Pro (rough boxes, rooftop objects missed) and has been replaced by measurement wherever Google has data. It remains as a starting point in places without it, and each suggestion asks the user "yes, it's there" or "no, remove it". Those verdicts are stored (`feedback.py`, DynamoDB `homesol-feedback`, coordinates only, no pixels) and `GET /feedback/summary` reports precision and recall.

**Limits.**
- **Only as good as what is marked.** An unmarked neighbour casts no shade.
- **Flat surfaces only**, and no "what causes the shade" breakdown or clear-hours table.
- **The phone scan has never been run on a real phone**, only with simulated sensor readings. The shadow-height method has never been checked against a building of known height.
- **No model is trained** on the feedback. It only collects labels, and none have been collected from real users yet.
- **The AI detector has not been re-tested since the move to Claude.**

---

## 10. Electricity use and the bill reader

**What it does.** Gets the household's monthly units, bill amount, electricity company and sanctioned load, either typed or read from a photo of the bill. Code: `web/src/components/BillUpload.tsx`, `api/homesol/bill.py`, endpoint `/bill`.

**How the bill reader works.**
1. The browser shrinks the photo to at most 1,800 pixels on its long side and sends it as a JPEG.
2. Claude reads it with a system prompt explaining what each figure means on a bill, and must call a tool with: units consumed, bill amount (before arrears), billing days, distributor name, state, sanctioned load, and any printed monthly history. It is told to leave out anything it cannot read and not to report personal details.
3. Code then turns that into monthly figures (`to_monthly`):
   - If the bill prints at least three earlier months, units are the average of those and this bill.
   - Otherwise this bill's units, scaled to 30 days if the billing period is 20–100 days (some distributors bill every two months).
   - The bill amount is scaled to match, so the price per unit stays the bill's own.
4. The distributor is matched by words in its name (for example "mahavitaran", "bses", "bescom", "dgvcl"), falling back to the state only when no name was read.
5. The fields are filled in, and the user is asked to check them.

**Nothing is stored.** The photo is read once.

**Settings.** Model: `BEDROCK_VISION_MODEL_ID` (default Claude Opus 4.6). Prompt: `SYSTEM` in `bill.py`.

**Tested on.** Two mock bills generated for the purpose (one bilingual and tilted), both read correctly on Nova Pro; the first re-read correctly on Claude Opus 4.6 (349 units, ₹3,100, MSEDCL). The monthly-figure logic has unit tests.

**Limits.**
- **Not tested on a real bill photo.** Real bills are creased, lit unevenly and vary widely by distributor.
- **Not tested on a bill from outside India.** The prompt allows for one, but the field names were designed around Indian bills.
- Only four distributor families are recognised by name.
- A bill with a non-typical month (summer peak) and no printed history gives a non-typical figure.
- The model can still misread a number; the app shows what it read for that reason.

---

## 11. System sizing

**What it does.** Chooses how many panels the household needs, and works out how much they will generate each month. Runs in the browser. Code: `web/src/lib/solar/sizing.ts`, `web/src/lib/solar/yield.ts`, `web/src/lib/useSizing.ts`.

**How it works.**
1. **Climate record.** Fetch long-term average sunlight for the location for each month from NASA POWER (satellite climatology, kWh per m² per day on a flat surface). This includes clouds and rainy seasons, anywhere in the world.
2. **Tilt gain** (`tiltGain`). Panels standing in tilted rows on a flat surface collect more than the flat surface does, mostly in winter. For each month the sunlight is split into direct and scattered light from how clear the sky is on average (Erbs' correlation); direct light is scaled by the panel's angle to the sun over the day (Klein's ratio), scattered light by the share of sky the panel still sees, and a little reflected light is added (Liu and Jordan's model, 20% ground reflectance). Rows turned away from the equator to line up with the building count only the part of their tilt that leans towards it. Panels lying flush on a slope get no tilt gain here, because their sunlight was measured on the slope itself.
3. **From sunlight to units at the meter** (`yieldBasis`).
   - *Measured site.* Each panel position's access is a share of Google's open-sky figure for the spot (kWh per kW of panel per year), which already allows for local weather and for the way a sloped surface faces. Google's own factor of 0.85 turns that into units at the meter. NASA's months only share the year out.
   - *Estimated site.* NASA's sunlight × 0.75.
   - If Google's figure and NASA's disagree wildly about the place (a factor outside 0.5–1.1), the estimated method is used.
4. **Choosing the panels** (`sizeSystem`). Take the good panel positions in plan order (section 8). Add panels one at a time, each counted at its own access, until a year's generation covers a year's use, or the positions run out.
5. The result says which limit applied: the household's use, or the room available.

**Settings.**
| Setting | Where | Value | Meaning |
|---|---|---|---|
| `PERFORMANCE_RATIO` | `sizing.ts` | 0.75 | Estimated sites: share of sunlight reaching the meter after heat, dust, wiring and inverter losses |
| `GOOGLE_DC_TO_AC` | `yield.ts` | 0.85 | Measured sites: Google's factor from its sunlight figure to units at the meter |
| `PANEL_KW` | `sizing.ts` | 0.55 | Rated output of one panel |
| `GROUND_REFLECTANCE` | `yield.ts` | 0.2 | Share of sunlight the ground reflects onto a tilted panel |

**Tested on.** The beam ratio matches the worked example in Duffie and Beckman's textbook (latitude 43°, tilt 60°, January: 2.79). Yearly tilt gains come out at about 2% in Bengaluru, 8% in Delhi, 11% in Palo Alto, 12% in London and 9% in Sydney, in line with standard design tools. On a flat surface in Mumbai the measured and estimated methods agree to within 2%; on the Bengaluru test roof the measured method gives about 4% more. Unit tests cover both methods, the hemispheres and the fallback.

**Limits.**
- **Google does not publish exactly what its sunlight figure includes.** The 0.85 factor is the one Google's own documentation applies to it; the close agreement with NASA × 0.75 on flat surfaces is the evidence it is being used correctly.
- **The tilt model is the simple textbook one.** It treats scattered light as even across the sky, which slightly understates the gain. Row-to-row shading outside the design hour (section 8) is not subtracted.
- **Monthly shape on a slope is the flat-surface shape.** A steep equator-facing roof makes relatively more in winter than shown, and less in summer; the yearly total is right.
- **One loss factor for the whole world.** Hot, dusty sites do worse; cool ones do better.
- **Sized to yearly use.** Where surplus is paid little, a slightly smaller system pays back faster; the app does not optimise for that.
- NASA's grid is coarse (roughly 50–100 km), so local haze, fog or mountain weather is not seen. On measured sites this affects only how the year is shared across months.

---

## 12. Cost and savings

**What it does.** Price, subsidy, bill before and after, first-year savings, payback and 25-year savings. Code: `api/homesol/finance.py`, endpoint `/finance`. The same code serves the dashboard and the advisor.

**How it works in India.**
1. **Price.** The vendor's quote if given; otherwise system size × the typical price per kW in `policies.json`, with a low–high range.
2. **Subsidy.** PM Surya Ghar: ₹30,000 per kW for the first 2 kW, ₹18,000 for the third, capped at ₹78,000, and never more than the price.
3. **Pricing a month's bill.**
   - If the household gave their bill amount: units × their own average rate.
   - Otherwise the distributor's tariff: each slab's units at that slab's rate, plus the fixed charge (flat, per kW of sanctioned load, or by load band), then any percentage surcharge.
4. **Net metering, month by month.**
   - *Annual settlement* (Maharashtra, Delhi): solar units offset that month's use; extra units carry forward as credit; what is left at year end is paid at the surplus rate.
   - *Monthly settlement* (Karnataka, Gujarat): each month's extra units are paid at the surplus rate and nothing carries forward.
5. **Savings** = bill before − bill after + surplus payments.
6. **Payback and 25 years.** Each year's savings shrink 0.5% (panel ageing) and grow 2% (assumed tariff rise). Payback is when cumulative savings reach the net cost.

**How it works elsewhere.** homesol has subsidy, tariff and price data for India only, and does not invent it for other countries.
- The household's bill amount is required; every unit is priced at their own average rate.
- No subsidy is assumed. Local incentives (tax credits, feed-in tariffs, rebates) are not included, and the result says so.
- There is no price unless the household enters a vendor's quote. Without one, the results show bill savings but no cost, payback or lifetime figure.
- Surplus units are assumed to carry forward within the year and be worth nothing at year end.
- Amounts are shown in the country's currency (section 18).

**Settings** (`finance.py`).
| Setting | Value |
|---|---|
| `SYSTEM_LIFE_YEARS` | 25 |
| `PANEL_DEGRADATION` | 0.5% a year |
| `TARIFF_ESCALATION` | 2% a year (an assumption, not a forecast) |
| `DEFAULT_LOAD_KW` | 3 kW, used when the sanctioned load is unknown |

**Limits.**
- **Outside India the money side is thin by design**: savings from the household's own rate, nothing else. Countries without net metering (where exported units earn little) will see savings overstated, because carry-forward is assumed.
- **Left out of savings in India:** fuel adjustment charges (except Gujarat's, which are included), electricity duty, Delhi's monthly power-purchase surcharge and its low-usage subsidy. Real savings are usually somewhat higher.
- **Left out of costs:** maintenance, a replacement inverter, loan interest, net-meter fees.
- **Using the household's own bill amount** prices every unit at their average rate. Solar removes the most expensive units first, so this understates savings.
- **The price per kW is a market range from installer guides**, not an official benchmark.
- State top-up subsidies are not included.
- Runs the year from January, not from the distributor's settlement month, which shifts carry-forward slightly.

---

## 13. Policy data

**What it is.** One file, `api/data/policies.json`, holding the central subsidy, the price range, and for each distributor its tariff and net-metering terms. Every entry has a `source` link and a `verified` flag. Loaded by `api/homesol/policy.py`. India only.

**Coverage and confidence.**
| Distributor | Tariff | Net metering |
|---|---|---|
| MSEDCL (Maharashtra) | From the MERC order of 25 March 2026 | Carry-forward rule from MERC's 2019 regulations; the ₹2.82 surplus rate is from trade press only |
| Delhi (BSES, Tata Power-DDL) | DERC schedule of 2021, still in force | Rule from the distributor's FAQ; surplus rate unknown, so surplus counts as zero |
| BESCOM (Karnataka) | KERC order of March 2025 for 2026-27 | From KERC's August 2026 regulations and tariff order |
| Gujarat state DISCOMs | GERC schedule from 1 April 2026, with fuel surcharge | ₹2.25 from summaries of the 2021 policy; not confirmed for 2026 |

**How a property is matched.** The property's location is reverse-geocoded to a country and state (Photon). In India the state maps to a distributor (`STATE_TO_DISCOM` in `policy.py`). The user can change it.

**Limits.**
- **Four distributor families only.** Everyone else must enter their bill amount.
- **One distributor per state.** Mumbai's Adani, Tata and BEST customers, and Gujarat's Torrent customers, are mapped to the state distributor.
- **Hand-maintained.** Tariffs change yearly and some surcharges monthly. The file's `as_of` date shows when it was last checked.
- MSEDCL's top slab (above 500 units) came from a table that extracted poorly and should be re-read from the order.

**To add or update a distributor:** edit `policies.json` (copy an existing entry's shape), add the state to `STATE_TO_DISCOM`, add name keywords to `DISTRIBUTOR_NAMES` in `bill.py`, run the tests, redeploy.

---

## 14. Advisor (AI chat)

**What it does.** Answers the household's questions about their own plan, in the language they ask in. Code: `api/homesol/agents.py`, endpoint `/advise`. Built with the Strands Agents SDK on Claude through Amazon Bedrock.

**How it works.**
1. The browser sends the question, the conversation so far, and a "survey" (`web/src/lib/advisor.ts`): location and currency, the surface, sun and clear-of-shadow hours, each obstruction with its share of the shade, the panel layout, the household's inputs and the recommended system.
2. The server writes a **fact sheet** (`fact_sheet`): every figure as a labelled sentence with its period. It says in plain words what the surface is, whether it was measured (with the imagery date) or estimated, what shades it and by how much, how the panels are placed, and the money figures from the section 12 code in the survey's own currency. Anything missing is named as missing. Caveats are listed at the end.
3. **The advisor** (Claude Opus 4.6) talks to the household. Its prompt holds the fact sheet first and the rules after it, each rule with its reason. Most questions (58 of 81 in the test set) are answered straight from the facts.
4. For the rest it consults one of two **specialists** (Claude Sonnet 4.6), each a tool that runs a fresh agent:
   - *Site analyst*: roof, shade and placement. Has the fact sheet.
   - *Policy and finance analyst*: has `lookup_policy` (policy entries with their sources, by state name; nothing outside India) and `estimate_finances` (re-runs section 12 for a different system size or a vendor quote). Every calculator result is appended to its reply word for word, so the advisor quotes the calculator and not a paraphrase.
5. **The tools are bound to the survey.** The model cannot supply usage, generation or the distributor; it can only ask for a different system size or quote. This is what stops wrong figures.
6. A line worked out in code tells the advisor which script the latest message is in (Devanagari, Hinglish by a word list, or other), because models drift into the wrong script.
7. The answer is cleaned in code (`clean_answer`): reasoning tags, markdown symbols and any web link not on a site the policy data cites are removed. An empty reply is retried once.

**Settings.**
| Setting | Default | Purpose |
|---|---|---|
| `BEDROCK_AGENT_MODEL_ID` | `us.anthropic.claude-opus-4-6-v1` | The advisor |
| `BEDROCK_SPECIALIST_MODEL_ID` | `us.anthropic.claude-sonnet-4-6` | Both specialists |
| `BEDROCK_AGENT_EFFORT`, `BEDROCK_SPECIALIST_EFFORT` | `low` | Thinking effort, sent only to Claude 4.6 and later. Medium added about a second and no accuracy |

Prompts: `ADVISOR_INTRO`, `ADVISOR_PROMPT`, `SITE_PROMPT`, `FINANCE_PROMPT` in `agents.py`. Throttled calls are retried three times, then fail; Strands' default would wait up to two minutes.

**Test set.** `api/evals/` holds 81 cases across 11 households (India and abroad, roofs and land, measured and estimated), in English, Hindi, Hinglish and one German case, some with two turns. Automatic checks cover language and script, currency, every figure traceable to the facts, what-if recalculation, tool arguments, length, markdown, internal names and leaked reasoning. A second model grades four more (first sentence answers the question, plain language, careful handling of what is unknown, unverified figures flagged); the grader is never the advisor's own model. Run with `api/.venv/bin/python api/evals/run.py`; each full run makes about 80 paid conversations. Offline tests of the checks and the fact sheet: `api/.venv/bin/python -m pytest api/evals` (101 tests, no model calls).

Final run, 11 October 2026, Opus advisor with Sonnet specialists (`api/evals/runs/20261011-final-opus-sonnet`):

| | Result |
|---|---|
| Cases passing every automatic check | 80 of 81 |
| Automatic checks | 789 of 790 |
| Graded checks | 198 of 204 |
| Seconds per answer | median 7.4, 90% under 13.5, worst 18.8 |
| Cost | about $0.04 an answer |

**Why these models.** On a 26-case subset, Nova Pro, Sonnet and Opus as advisor all scored within noise of each other on the checks (98–99% automatic). The choice rests on what the failures were: Nova answered a Hindi question in English and worked out a payback itself that disagreed with the calculator; Sonnet's Hindi replies were about a third English and it named bodies from memory; Opus did neither. Opus specialists added about two seconds for no gain; Haiku specialists were a second faster but looser with the site facts.

**Known remaining faults.**
- Replies after a specialist run long: 20 of 81 exceed the 120 words the prompt asks for, and one exceeded the 150-word limit.
- "Net metering" is sometimes used without explaining it.
- Asked for a detailed breakdown, it opens with a lead-in sentence and lists fields.
- Hedged general remarks with no figure slip through no check: "Your state may also offer tax credits or rebates".
- It sometimes consults a specialist on a question the facts already mark as having no data, adding about five seconds.
- What-if sizes scale generation in proportion to size; the website fills the sunniest positions first, so larger what-if sizes are slightly overstated. The calculator's output says "approximate".

**Limits.**
- **One sample per case, and no held-out set.** Prompts and checks were tuned on these same cases, so the figures above are optimistic; two or three cases either way is noise.
- **Figure tracing is pooled.** A number passes if it equals any fact for that household, so a real number attached to the wrong thing passes. One such slip was seen by reading.
- The graded checks did not separate the models, and the plain-language check rests on a fixed word list.
- Languages other than English, Hindi and Hinglish are barely tested (one German case).
- Speed was measured from one laptop with four conversations at once and no throttling.
- No memory between sessions; the conversation is lost on reload.
- Anyone with the API address can call it; there is no login or rate limit, only a cap of 10 simultaneous requests.

**Troubleshooting.**
- *Wrong figure in an answer:* print the fact sheet for that survey first (`agents.fact_sheet(survey)`); if the figure is right there, it is a model slip, and the eval's traceability checks are the place to look.
- *"The advisor's model is unavailable" or a 502:* a Bedrock error; the message carries Bedrock's reason. Check the model variables above and that the account can call both models.
- *Wrong language or script:* `_language_note` and the language rule in `ADVISOR_PROMPT`.
- *Slow answers:* a specialist was consulted (about 13 seconds against 6.5). Switching the advisor to Sonnet gives a median of about 5 seconds.

---

## 15. Voice questions

**What it does.** Turns a spoken question into text in the question box. Code: `web/src/lib/audio.ts`, `api/homesol/speech.py`, endpoint `/transcribe`.

**How it works.**
1. The browser records from the microphone, then decodes the clip and resamples it to 16 kHz, 16-bit, mono.
2. The server streams it to Amazon Transcribe in the language the user picked (Indian English or Hindi) and returns the final text.
3. The text is put in the question box for the user to check and send.

**Limits.**
- **Tested only with computer-generated speech**, not a real microphone or real accents.
- **Two languages.** The language must be picked; automatic detection returned nothing on clips under about three seconds, so it is not used. No Hinglish mode.
- Clips are limited to 60 seconds. Answers are not read aloud.
- Needs HTTPS and microphone permission.

---

## 16. Save and share

**What it does.** Saves the survey and gives a link and QR code that open it on another device. Code: `api/homesol/surveys.py`.

**How it works.** The survey (outline, floors, hand-marked obstructions, skyline scan, electricity inputs) is stored in DynamoDB under an 8-character code and expires after 90 days. Opening `?s=CODE` loads it. Each device also keeps its last survey in the browser's own storage.

**Limits.**
- **Anyone with the link can open it.** There are no accounts.
- **A saved link is a snapshot.** Changes made after saving need "Save again".
- The site model, obstruction names and advisor conversation are not saved. The site model is fetched again from the outline when the link opens, so a roof found by tap is rebuilt from its outline.

---

## 17. Screen layout

Three areas, following Material Design 3 (`web/src/app/globals.css` holds the colour roles, type scale, shapes and component styles):

- **Left, tools** (`ToolsPanel.tsx`): everything the user does. Your property, your electricity, cost details, shade around the roof (only when shade is estimated), ask a question, save or share. Each is a card with an icon, a title and a line saying what it is for.
- **Middle, map** (`MapView.tsx`, `MapControls.tsx`): the property, with the view switch (year's sun, shadows, photo) and the panel and obstruction toggles at the top, and the shadow time scrubber at the bottom.
- **Right, results** (`ResultsPanel.tsx`): every number and how it was worked out. The plan, the property, sun and shade (with what shades it and when the panels are clear), where the panels go, what it generates, cost and savings, the advisor's answers, the saved link. Nothing on this side is an input.

On screens narrower than 1,024 pixels the three stack: map, then tools, then results.

Tools appear as they become relevant: electricity after a property is chosen, cost details after electricity use is known.

**Limits.** The styling follows Material Design 3's roles and shapes but is hand-built, not Google's component library, so details such as ripple effects and floating labels are absent. There is a light theme only. Text is English only (the advisor answers in other languages).

---

## 18. Working anywhere in the world

| What | How | Limit |
|---|---|---|
| Address search | Photon, worldwide | Community service |
| 3D survey | Google Solar API | Coverage is uneven: dense in the US, Europe, Japan and large cities elsewhere; patchy in rural areas and much of Africa. Without it, section 9 |
| Sun position | SunCalc, any latitude | Polar day and night are untested |
| Time | `web/src/lib/time.ts`: the property's time zone from its coordinates (`tz-lookup`), daylight saving included | The scrubber and clear-hours table are in the property's local time, not the viewer's |
| Hemisphere | Panels face south in the north, north in the south; the shortest day is December or June accordingly | Within about 10° of the equator the best facing barely matters and the building's direction decides |
| Sunlight for generation | NASA POWER, worldwide | Coarse grid |
| Country and currency | Reverse geocoding gives the country code; a table in `web/src/lib/api.ts` maps about 60 countries to a currency | **A country not in the table is shown in US dollars.** Add it to `CURRENCIES` |
| Subsidy, tariff, price | India only (section 13) | Elsewhere, section 12 "How it works elsewhere" |
| Bill reader | Prompt allows for any country | Untested outside India |
| Advisor | Answers in the language of the question | See section 14 |

**Tested on.** Bengaluru (measured, rupees), rural Rajasthan (measured, open land), Nairobi (no survey, estimated, Kenyan shillings), Palo Alto (measured, sloped roof, dollars, no price without a quote). Unit tests cover time zones and a southern-hemisphere layout.

---

## 19. Deployment and configuration

| Piece | Where |
|---|---|
| Website | AWS Amplify Hosting, a static export of `web/` |
| API | AWS Lambda `homesol-api` (Python 3.13, arm64) behind a function URL, running the FastAPI app through Mangum |
| Saved surveys | DynamoDB `homesol-surveys` |
| Detection feedback | DynamoDB `homesol-feedback` |
| Deploy package | S3 `homesol-deploy-<account>` |

**To deploy:** `scripts/deploy.sh` from the repository root, with the AWS CLI logged in. It packages the API, updates the Lambda, brings the Lambda's settings in line with `api/.env` (the Google key and the three model variables; a model variable missing from `api/.env` is removed from the Lambda so the default in the code applies), builds the website against the API's address, and publishes it.

**Settings.**
| Setting | Where | Purpose |
|---|---|---|
| `GOOGLE_MAPS_API_KEY` | `api/.env`, Lambda environment | Google Solar API |
| `BEDROCK_VISION_MODEL_ID` | Lambda environment, `api/.env` | Bill reader, obstruction naming, older detector. Default Claude Opus 4.6 |
| `BEDROCK_AGENT_MODEL_ID`, `BEDROCK_SPECIALIST_MODEL_ID` | Lambda environment, `api/.env` | Advisor and its specialists (section 14) |
| `BEDROCK_AGENT_EFFORT`, `BEDROCK_SPECIALIST_EFFORT` | Optional, same places | Thinking effort for each; default `low` |
| `ALLOWED_ORIGINS` | Lambda environment | Which websites may call the API |
| `AWS_BEARER_TOKEN_BEDROCK` | `api/.env` only | Bedrock access when running locally; the Lambda uses its role |
| `NEXT_PUBLIC_API_URL` | Set by the deploy script at build time | API address the website calls |

**Models on this account.** Claude Opus 4.6, Sonnet 4.6, Opus 4.5, Sonnet 4.5 and Haiku 4.5 respond through Bedrock in `us-east-1`. The Claude 5 family returns "not available for this account". `models.py` already handles models that refuse a forced tool call, so switching is a change of environment variable once access is granted.

**Limits and risks.**
- The API is public: no login and no rate limit, capped at 10 simultaneous requests. A budget alert on the AWS account is the backstop.
- Each property costs one or two Google Solar requests, one naming call and the advisor's calls.
- The Lambda package is close to the 250 MB limit, which is why no image-codec library is included.
- A first request after idle time is slower while the Lambda starts.
- Region is `us-east-1`. Property locations and bill photos are processed there.

**Tests.** `api/.venv/bin/python -m pytest api/tests` (42), `api/.venv/bin/python -m pytest api/evals` (101) and `pnpm test` in `web/` (50). None calls a paid service. Running the advisor's test set itself (`api/evals/run.py`, section 14) does.
