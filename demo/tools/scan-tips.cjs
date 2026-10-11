// Finds where on screen each map tooltip appears at the chosen property, in the exact recording
// setup, so the takes can point at real features instead of guessed positions.
//   NODE_PATH=$(npm root -g) node demo/tools/scan-tips.cjs > demo/demo_assets/tips.json
const { Recorder, sleep } = require("./rec.cjs");
const { atPoint, tapCentre } = require("./rehearse.cjs");

const { lng, lat } = JSON.parse(require("node:fs").readFileSync(require("node:path").join(__dirname, "..", "demo_assets", "property.json"), "utf8"));
const POINT = [lng, lat];

async function scan(page, box, step) {
  const found = {};
  for (let y = box.y + step / 2; y < box.y + box.height; y += step) {
    for (let x = box.x + step / 2; x < box.x + box.width; x += step) {
      await page.mouse.move(x, y);
      await sleep(35);
      const tip = page.locator(".maplibregl-popup .tip-title");
      if (await tip.count()) {
        const title = await tip.first().innerText();
        (found[title] ??= []).push([Math.round(x), Math.round(y)]);
      }
    }
  }
  // For each tooltip, the hit nearest the middle of its hits: well inside the feature.
  return Object.fromEntries(
    Object.entries(found).map(([title, pts]) => {
      const mx = pts.reduce((s, p) => s + p[0], 0) / pts.length;
      const my = pts.reduce((s, p) => s + p[1], 0) / pts.length;
      const best = pts.reduce((a, p) => (Math.hypot(p[0] - mx, p[1] - my) < Math.hypot(a[0] - mx, a[1] - my) ? p : a));
      return [title, { at: best, hits: pts.length }];
    }),
  );
}

(async () => {
  const rec = new Recorder("demo/demo_assets/rehearsal/scan");
  const page = await atPoint(rec, POINT);
  await page.locator(".maplibregl-ctrl-zoom-in").click();
  await sleep(1800);
  await tapCentre(rec, page);
  await page.waitForResponse((r) => r.url().endsWith("/site/names"), { timeout: 90000 }).catch(() => {});
  await sleep(1500);
  const map = await page.locator("main").boundingBox();
  const before = await scan(page, map, 22);
  await page.getByLabel("Units in a typical month").fill("350");
  await page.getByLabel("Typical monthly bill").fill("1900");
  await page.getByText("YOUR SOLAR PLAN").waitFor({ timeout: 60000 });
  await sleep(1500);
  const roofBox = { x: map.x + map.width * 0.25, y: map.y + map.height * 0.2, width: map.width * 0.5, height: map.height * 0.6 };
  const after = await scan(page, roofBox, 9);
  console.log(JSON.stringify({ before, after }, null, 1));
  await rec.close();
  process.exit(0);
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
