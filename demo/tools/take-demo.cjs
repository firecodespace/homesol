// Records the demo's takes (T1-T9 in demo_shot_list.md) at one property, each as its own clip.
//
//   NODE_PATH=$(npm root -g) node demo/tools/take-demo.cjs <property.json> [take ...]
//
// property.json, filled in during rehearsal (screen positions are CSS pixels in the 1536x864 page):
//   {"search": "Sector 21 Chandigarh", "outline": [[lng, lat], ...], "tapScreen": [x, y],
//    "obstructionsScreen": [[x, y], [x, y]], "panelScreen": [x, y],
//    "units": 350, "bill": 2500, "question": "What if I install 3 kW instead?"}
// Untested against real data: rehearse each take once and adjust positions and waits.
// With no take names given, every take is recorded. Needs the app on :3000 and the API on :8000
// with real keys; see PLAN.md.

const fs = require("node:fs");
const { Recorder, sleep, VW, VH } = require("./rec.cjs");

const prop = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const wanted = process.argv.slice(3);
const OUT = "demo/demo_assets/raw";
const APP = "http://localhost:3000/";

/** A saved survey that opens the app straight at the property, measured again from its outline. */
const saved = (extra = {}) => ({
  "homesol-survey": JSON.stringify({
    state: { roof: prop.outline, floors: 2, obstructions: [], horizon: null, monthlyUnits: null, monthlyBill: null, quotedCost: null, discomId: null, sanctionedLoadKw: null, lastDetectionId: null, ...extra },
    version: 0,
  }),
});

/** Hides the side panels so the real map fills the frame, for the two map-only shots. */
const MAP_ONLY = "aside { display: none !important; } header { display: none !important; }";

/** Waits until the measured model is in: the results show the survey note. */
const measured = (page) => page.getByText("Measured from Google").first().waitFor({ timeout: 90000 });

async function stepShadows(rec, page, from, to, every = 200) {
  const slider = page.getByLabel("Time of day");
  await slider.focus();
  await slider.evaluate((el, v) => {
    const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
    set.call(el, String(v));
    el.dispatchEvent(new Event("input", { bubbles: true }));
  }, from);
  for (let m = from; m < to; m += 10) {
    await page.keyboard.press("ArrowRight");
    await sleep(every);
  }
}

const TAKES = {
  // T1: the hook. The day's shadows sweep across the roof, map only.
  async "hook-shadows"(rec) {
    const page = await rec.open(APP, { storage: saved() });
    await measured(page);
    await page.addStyleTag({ content: MAP_ONLY });
    await page.getByRole("button", { name: "Shadows" }).click();
    await page.getByLabel("Month").selectOption("12");
    await sleep(1500);
    rec.startCapture("hook-shadows");
    await sleep(600);
    rec.mark("sweep-start");
    await stepShadows(rec, page, 7 * 60, 17 * 60 + 30);
    rec.mark("sweep-end");
    await sleep(800);
    await rec.stopCapture();
  },

  // T2: the empty app, a search, the map flying in and Google's photo loading.
  async "reveal-search"(rec) {
    const page = await rec.open(APP);
    await page.getByPlaceholder("Search your area, street or landmark").waitFor();
    await sleep(1200);
    rec.startCapture("reveal-search");
    await sleep(1200);
    await rec.type(page.getByPlaceholder("Search your area, street or landmark"), prop.search, { label: "type-search" });
    const first = page.locator("ul li button").first();
    await first.waitFor({ timeout: 20000 });
    await sleep(500);
    await rec.clickOn(first, { label: "pick-result" });
    await sleep(2600);
    // Zoom from the search result to the street, as a person would.
    const map = await page.locator("main").boundingBox();
    await rec.moveTo(map.x + map.width / 2, map.y + map.height / 2);
    rec.mark("photo-wait");
    await sleep(4000);
    await rec.stopCapture();
  },

  // T3: one tap on the roof, the wait, and the measured result.
  async "tap-measure"(rec) {
    const page = await rec.open(APP);
    await page.getByPlaceholder("Search your area, street or landmark").waitFor();
    await rec.type(page.getByPlaceholder("Search your area, street or landmark"), prop.search);
    await rec.clickOn(page.locator("ul li button").first());
    await sleep(6000); // the photo of the area loads
    rec.startCapture("tap-measure");
    await sleep(1000);
    const [x, y] = prop.tapScreen;
    await rec.click(x, y, { label: "tap-roof" });
    await measured(page);
    rec.mark("measured");
    await sleep(3500);
    await rec.stopCapture();
  },

  // T4: Claude's names, read from the tooltips of two obstructions.
  async names(rec) {
    const page = await rec.open(APP, { storage: saved() });
    await measured(page);
    await sleep(8000); // names arrive a few seconds after the measurement
    rec.startCapture("names");
    await sleep(800);
    for (const [i, [x, y]] of (prop.obstructionsScreen ?? []).entries()) {
      await rec.moveTo(x, y);
      rec.mark(`tooltip-${i + 1}`);
      await sleep(3200);
    }
    await sleep(600);
    await rec.stopCapture();
  },

  // T5: shadows through the day, then what causes the shade and when the panels are clear.
  async shade(rec) {
    const page = await rec.open(APP, { storage: saved() });
    await measured(page);
    await sleep(1500);
    rec.startCapture("shade");
    await sleep(700);
    await rec.clickOn(page.getByRole("button", { name: "Shadows" }), { label: "shadows" });
    await sleep(500);
    await stepShadows(rec, page, 8 * 60, 16 * 60, 120);
    rec.mark("scroll-to-causes");
    const results = page.locator("aside").last();
    await rec.scroll(results, 520);
    await sleep(3800);
    await rec.stopCapture();
  },

  // T6: the panels in good sun, with one panel's tooltip.
  async panels(rec) {
    const page = await rec.open(APP, { storage: saved() });
    await measured(page);
    await sleep(1500);
    rec.startCapture("panels");
    await sleep(800);
    const [x, y] = prop.panelScreen ?? [VW / 2, VH / 2];
    await rec.moveTo(x, y);
    rec.mark("panel-tooltip");
    await sleep(3000);
    await rec.scroll(page.locator("aside").last(), 980);
    await sleep(2500);
    await rec.stopCapture();
  },

  // T7: the household's electricity, the plan, and the money.
  async plan(rec) {
    const page = await rec.open(APP, { storage: saved() });
    await measured(page);
    await sleep(1500);
    rec.startCapture("plan");
    await sleep(700);
    await rec.type(page.getByLabel("Units in a typical month"), String(prop.units), { label: "type-units" });
    await sleep(900);
    if (prop.bill) {
      const bill = page.getByLabel("Typical monthly bill");
      await bill.waitFor();
      await rec.type(bill, String(prop.bill), { label: "type-bill" });
    }
    await page.getByText("YOUR SOLAR PLAN").waitFor({ timeout: 30000 });
    rec.mark("plan-shown");
    await sleep(3500);
    const results = page.locator("aside").last();
    await rec.scroll(results, 1500, 1400);
    rec.mark("money");
    await sleep(4000);
    await rec.stopCapture();
  },

  // T8: a what-if question to the advisor, and its answer.
  async advisor(rec) {
    const page = await rec.open(APP, { storage: saved({ monthlyUnits: prop.units, monthlyBill: prop.bill ?? null }) });
    await measured(page);
    await page.getByText("YOUR SOLAR PLAN").waitFor({ timeout: 30000 });
    await sleep(1500);
    rec.startCapture("advisor");
    await sleep(700);
    await rec.type(page.getByLabel("Your question"), prop.question, { label: "type-question", delay: 45 });
    await sleep(400);
    await rec.clickOn(page.getByRole("button", { name: "Ask", exact: true }), { label: "ask" });
    await page.getByText("Checking your figures").waitFor({ timeout: 10000 }).catch(() => {});
    await page.getByText("Checking your figures").waitFor({ state: "detached", timeout: 120000 });
    rec.mark("answered");
    await sleep(6000);
    await rec.stopCapture();
  },

  // T9: the finished plan on the roof, map only.
  async "close-hero"(rec) {
    const page = await rec.open(APP, { storage: saved({ monthlyUnits: prop.units, monthlyBill: prop.bill ?? null }) });
    await measured(page);
    await page.getByText("YOUR SOLAR PLAN").waitFor({ timeout: 30000 });
    await page.addStyleTag({ content: MAP_ONLY });
    await sleep(2500);
    rec.startCapture("close-hero");
    await sleep(14000);
    await rec.stopCapture();
  },
};

(async () => {
  for (const [name, take] of Object.entries(TAKES)) {
    if (wanted.length && !wanted.includes(name)) continue;
    const rec = new Recorder(`${OUT}/${name}`);
    try {
      await take(rec);
    } catch (e) {
      console.error(`${name} failed:`, e.message);
    }
    await rec.close();
  }
  process.exit(0);
})();
