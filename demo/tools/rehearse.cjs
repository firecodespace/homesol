// Rehearses the demo workflow at a point without recording: tap, measure, names, shade, panels,
// plan and money. Prints what the app shows and saves screenshots, to choose a property and to
// collect the figures the narration will quote.
//
//   NODE_PATH=$(npm root -g) node demo/tools/rehearse.cjs <lng> <lat> <name> [units] [bill]

const fs = require("node:fs");
const { Recorder, sleep, VW, VH } = require("./rec.cjs");

const [lng, lat] = process.argv.slice(2, 4).map(Number);
const name = process.argv[4] ?? "candidate";
const units = process.argv[5] ?? "350";
const bill = process.argv[6] ?? "1900";
const OUT = `demo/demo_assets/rehearsal/${name}`;

/** A tiny saved outline at the point, so the app opens centred on it at street zoom. */
function seed([lng, lat]) {
  const d = 0.00001;
  const roof = [[lng - d, lat - d], [lng + d, lat - d], [lng + d, lat + d], [lng - d, lat + d]];
  return { "homesol-survey": JSON.stringify({ state: { roof, floors: 2, obstructions: [], horizon: null, monthlyUnits: null, monthlyBill: null, quotedCost: null, discomId: null, sanctionedLoadKw: null, lastDetectionId: null }, version: 0 }) };
}

/** Opens the app at the point, ready to tap: map centred and Google's photo of the area loaded. */
async function atPoint(rec, point) {
  const page = await rec.open("http://localhost:3000/", { storage: seed(point) });
  await page.getByRole("button", { name: "Change property" }).waitFor({ timeout: 60000 });
  await sleep(2500); // the fly-in
  await page.getByRole("button", { name: "Change property" }).click();
  await page.waitForResponse((r) => r.url().endsWith("/picture"), { timeout: 60000 }).catch(() => {});
  await sleep(1500);
  return page;
}

async function tapCentre(rec, page) {
  const map = await page.locator("main").boundingBox();
  await rec.click(map.x + map.width / 2, map.y + map.height / 2, { label: "tap" });
  await page.getByText("Measured from Google").first().waitFor({ timeout: 120000 });
}

module.exports = { seed, atPoint, tapCentre };

if (require.main === module) {
  (async () => {
    fs.mkdirSync(OUT, { recursive: true });
    const rec = new Recorder(OUT);
    const page = await atPoint(rec, [lng, lat]);
    await page.screenshot({ path: `${OUT}/1-before-tap.png` });
    const t0 = Date.now();
    await tapCentre(rec, page);
    console.log(`measured in ${((Date.now() - t0) / 1000).toFixed(1)} s`);
    await sleep(9000); // Claude's names
    const results = page.locator("aside").last();
    console.log("\n--- results ---\n" + (await results.innerText()).slice(0, 2600));
    await page.screenshot({ path: `${OUT}/2-measured.png` });
    await page.getByRole("button", { name: "Shadows" }).click();
    await sleep(1500);
    await page.screenshot({ path: `${OUT}/3-shadows.png` });
    await page.getByRole("button", { name: "Year's sun" }).click();
    await page.getByLabel("Units in a typical month").fill(units);
    await page.getByLabel("Typical monthly bill").waitFor({ timeout: 20000 });
    await page.getByLabel("Typical monthly bill").fill(bill);
    await page.getByText("YOUR SOLAR PLAN").waitFor({ timeout: 60000 });
    await sleep(4000);
    console.log("\n--- with electricity ---\n" + (await results.innerText()).slice(0, 4200));
    await page.screenshot({ path: `${OUT}/4-plan.png` });
    await rec.close();
    process.exit(0);
  })().catch((e) => {
    console.error(e);
    process.exit(1);
  });
}
