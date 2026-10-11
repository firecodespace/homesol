// Screenshots of framing options at the chosen property: app zoom levels and the map-only layout.
//   NODE_PATH=$(npm root -g) node demo/tools/framing.cjs <lng> <lat>
const { Recorder, sleep } = require("./rec.cjs");
const { atPoint, tapCentre } = require("./rehearse.cjs");

const OUT = "demo/demo_assets/rehearsal/framing";
const MAP_ONLY = `aside, header { display: none !important; }
  main .absolute.left-3.top-3, .maplibregl-ctrl-bottom-right .maplibregl-ctrl-group { display: none !important; }`;

(async () => {
  const rec = new Recorder(OUT);
  const page = await atPoint(rec, process.argv.slice(2, 4).map(Number));
  await page.locator(".maplibregl-ctrl-zoom-in").click();
  await sleep(1500);
  await tapCentre(rec, page);
  await sleep(12000);
  await page.screenshot({ path: `${OUT}/app-z20.png` });
  await page.addStyleTag({ content: MAP_ONLY });
  await page.evaluate(() => window.dispatchEvent(new Event("resize")));
  await sleep(2000);
  await page.screenshot({ path: `${OUT}/maponly-z20.png` });
  await page.locator(".maplibregl-ctrl-zoom-out").click({ force: true }).catch(() => {});
  await page.mouse.wheel(0, 120);
  await sleep(2000);
  await page.screenshot({ path: `${OUT}/maponly-zoomed-out.png` });
  await rec.close();
  process.exit(0);
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
