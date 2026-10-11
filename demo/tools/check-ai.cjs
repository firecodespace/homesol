// Checks the two Claude features at a point: obstruction names, and an advisor what-if answer.
//   NODE_PATH=$(npm root -g) node demo/tools/check-ai.cjs <lng> <lat> "<question>" [units] [bill]
const { Recorder, sleep } = require("./rec.cjs");
const { atPoint, tapCentre } = require("./rehearse.cjs");

(async () => {
  const [lng, lat] = process.argv.slice(2, 4).map(Number);
  const question = process.argv[4];
  const rec = new Recorder("demo/demo_assets/rehearsal/ai");
  const page = await atPoint(rec, [lng, lat]);
  const names = page.waitForResponse((r) => r.url().endsWith("/site/names"), { timeout: 120000 });
  const t0 = Date.now();
  await tapCentre(rec, page);
  const res = await names;
  console.log(`names: HTTP ${res.status()} after ${((Date.now() - t0) / 1000).toFixed(1)} s`);
  console.log(JSON.stringify(await res.json(), null, 1).slice(0, 2500));
  await page.getByLabel("Units in a typical month").fill(process.argv[5] ?? "350");
  await page.getByLabel("Typical monthly bill").fill(process.argv[6] ?? "1900");
  await page.getByText("YOUR SOLAR PLAN").waitFor({ timeout: 60000 });
  await sleep(2000);
  await page.getByLabel("Your question").fill(question);
  const t1 = Date.now();
  const advise = page.waitForResponse((r) => r.url().endsWith("/advise"), { timeout: 180000 });
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  const a = await advise;
  console.log(`\nadvisor: HTTP ${a.status()} after ${((Date.now() - t1) / 1000).toFixed(1)} s`);
  console.log((await a.json()).answer ?? JSON.stringify(await a.json()));
  console.log("\n--- plan card ---\n" + (await page.getByText("YOUR SOLAR PLAN").locator("..").innerText()));
  await rec.close();
  process.exit(0);
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
