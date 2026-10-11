# homesol

Solar planning for any property, anywhere: tap your roof or outline a piece of land, and see where each panel would go, what shades it and when, how much it would generate, and what it would cost and save. One screen instead of a round of installer quotes.

How each part works, its settings and its limits: [docs/how-it-works.md](docs/how-it-works.md).

## Run

Two processes: the web app and the API (site model, finance, policy and the Strands advisor agents).

```bash
cd web
pnpm install
pnpm dev
```

```bash
cd api
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn homesol.main:app --port 8000 --reload
```

`api/.env` (git-ignored) holds the keys:

```
AWS_BEARER_TOKEN_BEDROCK=...
AWS_REGION=us-east-1
GOOGLE_MAPS_API_KEY=...
```

`api/.venv/bin/python -m pytest api/tests` runs the site-model, finance, policy and bill tests.

## Deployed

- Site: https://main.d37cbq8cojkdix.amplifyapp.com (Amplify Hosting, static export of `web/`)
- API: AWS Lambda `homesol-api` behind a function URL, running the same FastAPI app through Mangum. It reaches Bedrock, Transcribe and DynamoDB through its IAM role, so no key is stored in it.
- Saved surveys: DynamoDB table `homesol-surveys`, items expire after 90 days.

`scripts/deploy.sh` ships new code to both. It needs the AWS CLI logged in to the account that owns these resources.

`pnpm test` in `web/` runs the shadow, panel-layout, time-zone, sun-position, skyline and sizing unit tests.

The rooftop skyline scan reads the phone's compass and tilt sensors, which browsers only expose over HTTPS. To try it on a phone on the same Wi-Fi, run `pnpm dev:https` and open `https://<your-computer's-ip>:3000` (accept the self-signed certificate warning).

## What is in it

- **Site model** (`api/homesol/site.py`): from a tap or an outline, finds the surface panels would sit on (flat roof, sloped roof, open land or hillside) in Google's 3D survey, measures it, and finds everything on and around it that could cast a shadow. Geometry on height data; no model looks at a picture.
- **Shadow simulation** (`web/src/lib/site/shadows.ts`): casts shadows from the measured heights for any month and time, and over a year works out how much sun is lost, which obstruction causes how much of it, and when the panels are clear.
- **Panel layout** (`web/src/lib/site/panels.ts`): places real-size panels on the surface, tilted in rows on flat surfaces and flush on slopes, facing the equator in either hemisphere, clear of edges and rooftop structures.
- **Obstruction names** (`api/homesol/naming.py`): Claude on Amazon Bedrock looks at the photo with each measured obstruction numbered and says what it is. It names things; it never changes a measurement.
- **System sizing** (`web/src/lib/solar/sizing.ts`, `yield.ts`): each panel position's measured yearly sunlight, the gain from tilting the panels, and NASA POWER's monthly climate record; panels are added, sunniest first, until the year's use is covered.
- **Cost, subsidy and savings** (`api/homesol/finance.py`): in India, PM Surya Ghar subsidy tiers, distributor tariffs and net-metering rules from `api/data/policies.json`, each with a source link and a `verified` flag. Elsewhere, savings from the household's own bill, in the local currency, with no invented subsidy or price.
- **Advisor** (`api/homesol/agents.py`): a Strands Agents advisor on Claude that delegates to a site analyst and a policy-and-finance analyst. The agents get every figure from the survey or from tools over the same finance code.
- **Bill reading** (`api/homesol/bill.py`): a photo of the electricity bill fills in units, bill amount, distributor and sanctioned load. Personal details are not extracted or stored.
- **Voice questions** (`api/homesol/speech.py`): Amazon Transcribe turns Indian English or Hindi speech into text.
- **Save and share** (`api/homesol/surveys.py`): a survey is stored under a short code and opened from a link or QR code.
- **Where Google has no survey**: the app falls back to an estimate from hand-marked obstructions (`web/src/lib/solar/shading.ts`), with height from a satellite shadow (`shadowHeight.ts`) and a rooftop skyline scan with the phone's compass and tilt sensors (`horizon.ts`).
- **Advisor test set** (`api/evals/`): questions across households and languages with automatic checks on language, figures and length. Run with `api/.venv/bin/python api/evals/run.py`; each run makes paid model calls.
