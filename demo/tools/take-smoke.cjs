// Smoke test of the recording harness on the local app (no keys needed): a saved property is
// restored, then the cursor types usage and switches map views.
const { Recorder, sleep } = require("./rec.cjs");

const OUT = process.argv[2] || "demo/demo_assets/raw/smoke";
const ROOF = [[76.7790, 30.7330], [76.7794, 30.7330], [76.7794, 30.7333], [76.7790, 30.7333]];
const SAVED = { state: { roof: ROOF, floors: 2, obstructions: [], horizon: null, monthlyUnits: null, monthlyBill: null, quotedCost: null, discomId: null, sanctionedLoadKw: null, lastDetectionId: null }, version: 0 };

(async () => {
  const rec = new Recorder(OUT);
  const page = await rec.open("http://localhost:3000/", { storage: { "homesol-survey": JSON.stringify(SAVED) } });
  const units = page.getByLabel("Units in a typical month");
  await units.waitFor({ timeout: 60000 });
  await sleep(1500);
  rec.startCapture("smoke");
  await sleep(800);
  await rec.type(units, "320", { label: "type-units" });
  await sleep(800);
  await rec.clickOn(page.getByRole("button", { name: "Shadows" }), { label: "shadows" });
  await sleep(1500);
  await rec.clickOn(page.getByRole("button", { name: "Year's sun" }), { label: "sun" });
  await sleep(800);
  const map = await page.locator("main").boundingBox();
  await rec.moveTo(map.x + map.width * 0.3, map.y + map.height * 0.7);
  await rec.moveTo(map.x + map.width * 0.7, map.y + map.height * 0.3);
  await sleep(800);
  await rec.stopCapture();
  await rec.close();
  process.exit(0);
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
