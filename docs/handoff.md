# homesol: status and hand-off

Written 11 October 2026 for whoever picks this up next, including a Claude session with no access to the earlier conversation. Read this first, then [how-it-works.md](how-it-works.md), which explains every system, its settings and its limits.

## What it is

An AWS hackathon entry. A household taps their roof (or outlines any piece of land) on a map and gets, on one screen: where each panel would go, what shades it and when, how much it would generate, and what it would cost and save. It is meant to replace a round of installer quotes. Prize eligibility needs an AWS open source tool or an AWS deployment; it uses the Strands Agents SDK and runs on AWS.

The owner's bar is "a winning project": every system precise, on real data, in an organised screen. Their standing preferences:

- Tools on the left, map in the middle, numbers and explanations on the right, in Material Design 3. No numbered steps.
- As little manual input as possible. Measured things shown concretely: real panel rectangles, each obstruction with a short explanation.
- Any surface (roof, flat land, hillside) in any country.
- Claude models, not Nova. Models read and explain; code does every calculation.
- Status reports that say plainly what is verified and what is not.
- They commit and push themselves. Do not commit unless asked.

## Where things are

| | |
|---|---|
| Live site | https://main.d37cbq8cojkdix.amplifyapp.com |
| Live API | AWS Lambda `homesol-api`, function URL `https://bo2upqcl6beeqtjtyhrsvnn7tu0hyqee.lambda-url.us-east-1.on.aws` (public, no login, rate-limited per visitor and per day, 10 at once, 120 s timeout) |
| Storage | DynamoDB `homesol-surveys`, `homesol-feedback`, `homesol-limits` (made by the next deploy), region `us-east-1` |
| Repository | GitHub `firecodespace/homesol`, branch `main` |
| Website code | `web/` (Next.js 16 static export, React 19, MapLibre, Tailwind 4, zustand) |
| API code | `api/homesol/` (FastAPI, Strands Agents, numpy) |
| Deploy | `scripts/deploy.sh` (needs the AWS CLI logged in and `api/.env`) |
| Demo video | https://www.youtube.com/watch?v=QwJxYxqNJF4. `demo/` holds its script, shot list and the tools that recorded and assembled it; the video files are not in git |

**Everything described here is committed on `main`.** The live site and API were last deployed on 11 October 2026, before the rate limits (section 20 of the reference). Until `scripts/deploy.sh` is run again, the live API has no rate limits and the website has no limit banner; the script also creates the `homesol-limits` table and the permission to use it.

**A cloud session will not have** `api/.env` (Bedrock key, Google Maps key) or AWS credentials. Without them it can read, edit and run every unit test, but it cannot call Google's Solar API, call Bedrock, run the advisor test set, or deploy. `web/AGENTS.md` warns that this Next.js version differs from older ones; read the guides it points to before changing framework code.

## How it works, in one paragraph

The server builds a "site model" from Google's Solar API 3D survey (`api/homesol/site.py`, `/site`): the surface under a tap or inside an outline, classified as roof, sloped roof, ground or sloped ground, plus everything on and around it that could cast a shadow, all measured from height data with no AI. The browser simulates shadows on those heights, attributes the shade to each obstruction, and lays out real-size panels (`web/src/lib/site/`). Claude on Bedrock names the measured obstructions from an annotated photo, reads electricity bills, and runs the advisor chat. Where Google has no survey, the app says so and estimates from obstructions the user marks by hand. Money figures use Indian subsidy and tariff data in India, and the household's own bill in its own currency elsewhere.

## Verified, and how

Checked on real data in a browser unless stated otherwise.

| System | Evidence |
|---|---|
| Surface from a tap or an outline | Bengaluru flat roofs by both routes (224 and 225 m² for the same roof); a tap on a tree refused; open land in Rajasthan; Palo Alto pitched roof by tap, and by an outline across its ridge (picks the larger face) |
| Obstructions from height data | Two Bengaluru roofs: rooftop block, neighbours and trees found, shade attributed with almost nothing left unexplained |
| Obstruction names (Claude Opus 4.6) | Bengaluru roofs, locally and on the live API ("Stair room", "Trees to the south-east", ...) |
| Shadow simulation | Geometry unit-tested against hand-worked cases; yearly loss within 1.5 points of Google's own on one roof |
| Panel layout | Flat roof (rows aligned to the building, around structures), open land, slope (flush), southern hemisphere |
| Generation | Tilt gain matches a textbook worked example; Google-based and NASA-based figures agree within 2% on a flat surface in Mumbai |
| Cost and savings | India with subsidy and tariffs; USA and Kenya from the bill, no invented price |
| Bill reader (Claude Opus 4.6) | One mock bill, locally and on the live API |
| Advisor (Opus 4.6 + Sonnet 4.6 specialists) | 81-case test set: 80 pass every automatic check; live API answered in English and Hindi; asked through the live website |
| Layout | No overflow or wrapped buttons at 375, 1024, 1280 and 1440 px |
| Live deployment | `/site`, `/site/names`, `/bill`, `/finance`, `/advise` answered correctly from Lambda; the site loaded and ran end to end |
| Rate limits | Unit tests on both sides; in a browser against a local API with allowances turned down: banner, countdown, paused measuring and "Try again" |

Tests, none of which calls a paid service: `api/.venv/bin/python -m pytest api/tests` (50), `api/.venv/bin/python -m pytest api/evals` (101), `pnpm test` in `web/` (62). `npx tsc --noEmit` and `pnpm lint` in `web/` are clean.

## Not verified

- **Nothing has been tried on a real phone.** The skyline scan (camera, compass, tilt) and the microphone have only been driven with simulated input.
- **No real bill photo**, and no bill from outside India. Only mock bills.
- **The shadow-height method** has never been checked against a building of known height.
- **Google's data itself** has no published accuracy, and most of India is its lowest quality tier.
- **Sloped surfaces** rest on one real pitched roof and synthetic tests. Hillsides have only synthetic tests.
- **Obstruction naming** has been looked at on two roofs; no accuracy measured.
- **The tap flow on the live site** was exercised through the API, not by clicking the live map.
- **Languages** beyond English, Hindi and Hinglish: one German advisor case.
- **No model is trained** from the yes/no feedback; it is only stored, and no real verdicts exist yet.
- **Rate limits on Lambda with DynamoDB.** Only run locally with in-memory counters; the table is created on the next deploy. After deploying, ask the advisor 31 questions within an hour from one address to see the banner.

## Known faults and open work

In rough order of value.

1. **Deploy** (owner): `git pull && scripts/deploy.sh` on a machine with the AWS CLI logged in. It brings the live site up to date and turns the rate limits on.
2. **Rotate the Bedrock key after the hackathon** and delete `bedrock-long-term-api-key.csv` from the Desktop. The key appeared in an earlier assistant conversation. `web/.env.local` also holds a copy the website no longer uses; delete it.
3. **One plan covers one roof face.** A pitched roof's faces are surveyed one at a time and not added together. A whole-roof plan across several faces is the biggest missing feature for countries with pitched roofs.
4. **Google sometimes takes about 30 s** instead of 5–10 (seen several times). The screen says so after 10 s and results are cached for 20 minutes, but a first visit can still be slow.
5. **Unknown country defaults to India.** If the place lookup fails, `web/src/lib/useMoney.ts` and `web/src/lib/advisor.ts` assume India and rupees. A country missing from the currency table in `web/src/lib/api.ts` shows US dollars.
6. **Advisor faults** (section 14 of the reference): replies after a specialist run long; "net metering" sometimes unexplained; hedged general remarks such as "your state may offer rebates"; what-if sizes are approximate.
7. **Subsidy on ground-mounted panels** is shown with a note that it is unconfirmed; the figure still includes it.
8. **Policy data** covers four Indian distributor families; some surplus rates are unconfirmed and flagged in `api/data/policies.json`.
9. **Rate limits are per address, with no login.** People sharing an address (an office, a college, a mobile carrier's shared address) share an allowance, and one person with many addresses gets many; the daily cap for everyone bounds the cost but, once reached, closes the paid features for everyone until midnight UTC. Each property costs one or two Google requests, one Opus naming call, and about $0.04 per advisor answer. A budget alert on the AWS account is the last backstop.
10. **Claude 5 models** returned "not available for this account" on Bedrock. `api/homesol/models.py` already handles their tool-call rules, so switching is a change of environment variable.

## Commands

Run from the repository root unless stated.

| To | Run |
|---|---|
| Start the API locally | `cd api && .venv/bin/uvicorn homesol.main:app --port 8000 --reload` |
| Start the website locally | `cd web && pnpm dev` |
| API tests | `api/.venv/bin/python -m pytest api/tests` |
| Advisor check tests (offline) | `api/.venv/bin/python -m pytest api/evals` |
| Website tests | `cd web && pnpm test` |
| Advisor test set (paid, about 80 conversations) | `api/.venv/bin/python api/evals/run.py` |
| Deploy both | `scripts/deploy.sh` |
| Redraw the README's model chart | `python3 demo/tools/readme_charts.py` (standard library only) |

`api/.env` needs `AWS_BEARER_TOKEN_BEDROCK`, `AWS_REGION=us-east-1`, `GOOGLE_MAPS_API_KEY`, and optionally the three `BEDROCK_*_MODEL_ID` variables. The deploy script copies the Google key and those model variables to the Lambda.
