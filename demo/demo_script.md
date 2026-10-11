# homesol: 3-minute demo, narration and on-screen text

Draft 1, 11 October 2026. Every `{FIELD}` is filled in from the live recording, never estimated. Lines are timed to the brief's beats; narration runs at about 150 words a minute (Kokoro voice `af_heart`), leaving room to breathe between ideas.

Rule for every line: it must be true of the code in this repository and visible on screen when it is said.

| Time | Picture | Narration | On-screen text |
|---|---|---|---|
| **0:00–0:15** Hook | Real shadow sweep over the chosen roof (Shadows view, 21 December, the time slider stepped from morning to evening), map only, with a scrim on the left | Every roof loses sun to something. A stair room. A water tank. The floor next door. A tree. And how much it loses decides whether solar is worth it. | "Every roof loses sun to *something.*" / "A stair room. A water tank. The floor next door. A tree." / "How much it loses decides *whether solar pays.*" Stamp: "21 December · {CITY}" |
| **0:15–0:40** Problem | Graphics: the four questions arrive one by one, then the "today" line | Before buying, a household needs four answers. Where can panels actually fit? What shades them, and when? How much will they make? And what will it really cost, after subsidy and tariffs? Today those answers come from a site visit and a round of quotes, and there's no way to check any of them. | Kicker "Before going solar"; four question cards; "Today the answers come from a site visit and a round of quotes, *and the household can't check any of them.*" |
| **0:40–0:47** Reveal | Graphics: homesol wordmark, sun bar, "Measured · Simulated · Laid out · Priced" | homesol answers all four from one tap on a map. | "A solar plan for your home, from one tap." |
| **0:47–1:00** Reveal | The real app, empty; search for the area; the map flies in; Google's photo of the street loads | It measures the property from Google's 3D survey, simulates a year of shadows, lays out real panels and prices the result. AI models read and explain. Code does every calculation. | Lower third: "Models read and explain. *Code does every calculation.*" |
| **1:00–1:05** Demo | Cursor taps the roof; "Measuring your property…" (the wait is cut, and the cut is visible as a dissolve) | Here's a home in {CITY}. One tap on the roof. | |
| **1:05–1:16** Demo | Roof outlined in white; obstructions outlined red, blue and green; results panel fills | From height data alone, homesol finds the roof: {AREA} square metres, {FLOORS} floors up, and everything around it that can cast a shadow. | Lower third: "Measured, not guessed: *found in Google's 3D height data.*" Callout on Area and Height |
| **1:16–1:28** Demo | Cursor points at obstructions; tooltips show the names Claude gave them | Claude, on Amazon Bedrock, looks at the photo and names what was measured: {NAME_1}, {NAME_2}. It can name things. It can't change a measurement. | Lower third: "Claude names what the code measured. *It can't change a measurement.*" |
| **1:28–1:44** Demo | Shadows view stepping through the day; results scrolled to "What shades it" and "When the panel positions are clear" | Then it runs the sun across the year, every half hour, over those heights, and charges each hour of lost sunlight to whatever blocked it. {TOP_CAUSE} takes {TOP_SHARE} percent. | Callout on "What shades it": "Shade, traced to its cause" |
| **1:44–1:53** Demo | Year's sun view with panels; pointer on one panel shows its share of sun | Real-size panels go only where the sun is good, in rows spaced so they don't shade each other in winter. (Flat roof only; on a sloped roof: "lying flush on the slope, facing {FACING}.") | |
| **1:53–2:08** Demo | Units {and bill} typed in; "Your solar plan" appears; cost and savings card | Now the household's electricity: {UNITS} units a month. The plan: {PANELS} panels, {KW} kilowatts, covering {COVER} percent of the year's use. With the PM Surya Ghar subsidy it costs {NET}, and pays for itself in {PAYBACK} years. | Callout on the plan card |
| **2:08–2:15** Demo | Results notes: survey date and quality, subsidy source, tariff basis | Every figure says where it came from: the survey date, the subsidy rule, the tariff. | |
| **2:15–2:30** Proof | A what-if question typed into "Ask a question"; the answer appears (the agent's wait is cut); the same figure highlighted in the answer and in the dashboard | Ask a question, in English or Hindi. A Strands agent answers from this exact plan, and for a what-if it calls the same finance code the dashboard uses, so its numbers match the screen. | Callout pair: answer figure and dashboard figure |
| **2:30–2:40** Proof | Evidence card: the test run's own summary file | Across 81 test questions, 789 of 790 automatic checks passed, and in every answer with money in it, each amount traced back to the plan's own figures. | "789 / 790", "57 / 57", "81 / 81", the summary lines verbatim, and the caveat: "One run per question, on the same questions the prompts were tuned on: a check of behaviour, not a held-out benchmark." |
| **2:40–2:52** Close | Map only: the finished plan, panels on the roof, year's sun | One tap. A measured roof, a year of shadows, a panel plan and an honest price, before the first site visit. | |
| **2:52–3:00** Close | End card, fades out at 3:00 with the music | That's homesol. | "A measured roof, a year of shadows, a panel plan and *an honest price.* From one tap." homesol. "Built with Strands Agents · Claude on Amazon Bedrock · AWS Lambda · Google Solar API" |

## What each claim rests on

| Claim | Where it is true |
|---|---|
| Surface and obstructions from height data, no AI | `api/homesol/site.py` (`grow_surface`, `find_obstructions`); docs section 3–4 |
| Claude names what was measured and cannot change measurements | `api/homesol/naming.py`, `web/src/lib/site/naming.ts`; only names and notes come back |
| Sun every half hour across the year, shade charged to its cause | `web/src/lib/site/shadows.ts` `analyseShade` (21st of each month, 30-minute samples, blame by label) |
| Rows spaced so they don't shade each other in winter | `panels.ts` row gap: shadow 2.5 h before solar noon on the shortest day; the results panel says so |
| PM Surya Ghar subsidy, tariff, payback | `api/homesol/finance.py`, `api/data/policies.json` |
| Advisor answers from the plan; what-ifs call the same finance code | `api/homesol/agents.py` (`estimate_finances` bound to the survey, calculator output appended verbatim) |
| 789/790, 57/57, 81/81 | `api/evals/runs/20261011-final-opus-sonnet/summary.txt` |
