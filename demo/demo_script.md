# homesol: 3-minute demo, script as produced

Final, 11 October 2026. Matches `project_demo_final.mp4` (180.000 s). Times are in the finished film. Narration is Kokoro-82M (voice `af_heart`), generated locally; the spoken text below is as written, and `demo_assets/audio/lines.json` holds the respellings the voice was given ("Chundeegarh", "home sol", "laakh"). Captions: `demo_assets/captions/project_demo_final.srt`.

Every figure quoted was read off the recording of the real app; nothing on screen was edited.

## Hook (0:00–0:15)

**Picture:** the real Shadows view of the property, map only, stepping through 21 December from 07:00 (before sunrise) to the afternoon; slow push-in. The app's own time slider shows the hour.

| Time | Narration | On screen |
|---|---|---|
| 0:00.9 | Every roof loses sun to something. | "Every roof loses sun to *something.*" |
| 0:03.5 | A stair room. A water tank. The floor next door. A tree. | "A stair room. A water tank. The floor next door. A tree." |
| 0:07.6 | And how much it loses decides whether solar is worth it. | "How much it loses decides *whether solar pays.*" |

## Problem (0:15–0:40)

**Picture:** graphics. Kicker "Before going solar"; the four questions arrive one by one as they are asked.

| Time | Narration | On screen |
|---|---|---|
| 0:15.8 | Before going solar, a household needs four answers. | "Every household needs four answers." |
| 0:19.2 | Where can panels actually fit? | Card: "Where can panels actually fit? Edges, tanks and stair rooms take their share of the roof." |
| 0:21.6 | What shades them, and when? | Card: "What shades them, and when? The floor next door or a tree can take hours of sun." |
| 0:23.6 | How much will they make? | Card: "How much will they make? Sun, tilt, season and shade all change it." |
| 0:25.5 | And what will it really cost, after the subsidy? | Card: "What will it really cost? Subsidy, tariff slabs and net-metering rules." |
| 0:29.4 | Today, those answers come from a site visit and a round of quotes, and the household can't check any of them. | "Today the answers come from a site visit and a round of quotes, *and the household can't check any of them.*" |

## Reveal (0:40–1:00)

| Time | Narration | Picture and on screen |
|---|---|---|
| 0:40.7 | homesol answers all four, from one tap on a map. | Wordmark, sun-ramp bar, "A solar plan for your home, from one tap." Measured · Simulated · Laid out · Priced |
| 0:46.3 | Here's a home in Chandigarh, in Google's own photo of the street. One tap, on its roof. | The real app, empty, Google's photo of the street loaded; the cursor taps the roof at 0:51.8 |
| 0:53.8 | It measures the roof from Google's 3D survey: flat, two hundred and twenty-five square metres, about two floors up, and it finds everything around that could cast a shadow. That's geometry, not guesswork. | "Measuring the roof you tapped…", then the outline, obstructions and results (Flat roof, 225 m², 5 m, about 2 floors up). Caption 0:59.6: "Measured, not guessed. The roof and everything that can shade it, *from Google's 3D height data.*" |

## Live demonstration (1:00–2:15)

| Time | Narration | Picture and on screen |
|---|---|---|
| 1:07.3 | Then Claude, on Amazon Bedrock, names what was measured: a large cluster of trees to the south-west, a stair room. It can name things. It can't change a measurement. | Claude's names replace the code's labels in the results. Tooltips: "Large tree cluster to south-west: 6 m away, stands 18.5 m above it; causes about 56% of the shade", then "Stair room: on your roof, stands 2 m above it; causes about 8%". Caption 1:07.6: "Claude on Amazon Bedrock. Names what the code measured. *It can't change a measurement.*" |
| 1:19.7 | Next, it runs the sun across the year, every half hour, over those heights, and charges each hour of lost sunlight to whatever blocked it. | Shadows view, 21 December, stepped 08:00 to 16:30 |
| 1:35.2 | The trees take fifty-six percent. On the shortest day, the panel spots are clear of shadow only from about ten until noon. | "What shades it": Large tree cluster to south-west 56%, Water tank 11%, Stair room 8%, Trees to the north-west 7%; "Winter (21 Dec) 09:52 – 11:52". Callout: "56% of the lost sun: one tree cluster" |
| 1:44.2 | Panels go only where the sun is good. There's room for twenty-eight, in rows spaced so they don't shade each other in winter. | Year's sun view; "Room for 28 panels, 15.4 kW in good sun"; "Panels stand in rows tilted 25° … 2 m from one row to the next" |
| 1:51.4 | Say this household uses three hundred and fifty units a month, about nineteen hundred rupees. | 350 typed into units, 1900 into the bill (example household figures) |
| 1:58.9 | The plan: six panels, three point three kilowatts, covering all of it. After the seventy-eight thousand rupee PM Surya Ghar subsidy, it costs one lakh twenty thousand, and pays back in about five years. | "YOUR SOLAR PLAN 3.3 kW · 6 panels. Covers 100% … about 393 units a month. ₹1,20,000 you pay, after ₹78,000 subsidy · ₹22,453 saved in the first year · 5.2 yrs". Callout: "Sized to this household's use". Tooltip: "Panel in your plan: gets 93% of full sun over a year" |
| 2:13.0 | And every figure says where it came from: the survey's date, the subsidy rules, the household's own rate. | "Cost and savings" (Likely price ₹1,98,000, usual range ₹1,55,100–₹2,40,900; You pay ₹1,20,000; 5.2 years; Yearly bill ₹347, down from ₹22,800; ₹5,54,156 in 25 years) and its notes ("Priced at your own average of 5.43 INR a unit", "Subsidy rules as checked on 2026-10-10"). Callout: "Where each figure came from" |

## Proof (2:15–2:46)

| Time | Narration | Picture and on screen |
|---|---|---|
| 2:19.6 | Now, a what-if: what about five kilowatts? A Strands agent on Claude answers from this plan, using the same finance code as the dashboard. | "What if I install 5 kW instead?" typed and asked; "Answering…". Caption 2:20.4: "Strands Agents on Claude. An advisor whose tools are *bound to this plan.*" 8.7 s of the agent's 14-second wait is cut with a dissolve. |
| 2:28.6 | The bigger system would take about nine years to pay back, not five, because the extra units would earn nothing. | The answer, as given: "A 5 kW system would cost about ₹2.22 lakh after subsidy and take about 9.2 years to pay for itself — quite a bit longer than the recommended 3.3 kW system's 5.2 years. … sending roughly 2,945 surplus units a year to the grid … counted as worth nothing." |
| 2:36.0 | Across eighty-one test questions, seven hundred and eighty-nine of seven hundred and ninety automatic checks passed, and every money figure traced back to the plan's own numbers. | Evidence card: "Checked, not assumed. The advisor answered 81 test questions about 11 different households." 789 / 790, 57 / 57, 81 / 81, and the summary file's own lines, verbatim. Footnote: "One run per question, on the same questions the prompts were tuned on: a check of behaviour, not a held-out benchmark." |

## Close (2:46–3:00)

| Time | Narration | Picture and on screen |
|---|---|---|
| 2:46.8 | One tap. A measured roof, a year of shadows, a panel plan and an honest price, before the first site visit. | The finished plan on the roof, map only, slow push-in |
| 2:54.6 | That's homesol. | "A measured roof, a year of shadows, a panel plan and *an honest price.* From one tap." homesol. "Built with Strands Agents · Claude on Amazon Bedrock · AWS Lambda · Google Solar API · NASA POWER". Fades to black and silence at 3:00.0 |

## What each claim rests on

| Claim | Where it is true |
|---|---|
| Surface and obstructions from height data, no AI | `api/homesol/site.py` (`grow_surface`, `find_obstructions`); shown on screen as "found from your tap", "Measured from Google's 3D survey, imagery dated 2025-04-08 (satellite survey, its least detailed)" |
| Claude names what was measured and cannot change measurements | `api/homesol/naming.py`, `web/src/lib/site/naming.ts`: only a name, an explanation and a confidence come back |
| Sun every half hour across the year, shade charged to its cause | `web/src/lib/site/shadows.ts` `analyseShade`; the results note says the same |
| Rows spaced so they don't shade each other in winter | `web/src/lib/site/panels.ts`; on screen: "2 m from one row to the next so a row does not shade the one behind it in winter" |
| Subsidy, price, payback; the household's own rate | `api/homesol/finance.py`, `api/data/policies.json`; on screen: "Priced at your own average of 5.43 INR a unit", "Subsidy rules as checked on 2026-10-10" |
| The advisor answers from the plan, using the same finance code | `api/homesol/agents.py`: a Strands agent on Claude whose `estimate_finances` tool re-runs `finance.py` for a different size and is bound to the survey; the answer's 3.3 kW figures (5.2 years, ₹5.54 lakh) match the dashboard's |
| 789/790, 57/57, 81/81 | `api/evals/runs/20261011-final-opus-sonnet/summary.txt`, quoted verbatim by `tools/evidence_params.py` |
| 350 units, ₹1,900 a month | Example household figures typed for the demo, introduced with "Say" |
