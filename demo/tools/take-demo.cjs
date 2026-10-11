// Records the demo's real-app footage at the chosen property (roof B in Chandigarh).
//
//   NODE_PATH=$(npm root -g) node demo/tools/take-demo.cjs [workflow|hook|close] [suffix]
//
// "workflow" is one continuous take of the whole flow, so every figure on screen stays consistent
// from shot to shot; the edit cuts it into segments using its marks. "hook" and "close" are the
// map-only shots. Needs the app on :3000 and the API on :8000 with keys (see PLAN.md).

const { Recorder, sleep } = require("./rec.cjs");
const { atPoint, tapCentre } = require("./rehearse.cjs");

// The property's point, kept out of git (a private home): {"lng", "lat", "units", "bill", "question"}.
const PROPERTY = JSON.parse(require("node:fs").readFileSync(require("node:path").join(__dirname, "..", "demo_assets", "property.json"), "utf8"));
const OUT = "demo/demo_assets/raw";
/** Where each tooltip opens, in page pixels, from scan-tips.cjs at this property and framing. */
const TIPS = { trees: [503, 727], stair: [703, 618], panel: [820, 420] };

/** Side panels, header, the controls row and the zoom buttons hidden: the real map fills the frame. */
const MAP_ONLY = `aside, header { display: none !important; }
  main .absolute.left-3.top-3, .maplibregl-ctrl-bottom-right .maplibregl-ctrl-group { display: none !important; }`;

async function ready(rec) {
  const page = await atPoint(rec, [PROPERTY.lng, PROPERTY.lat]);
  await page.locator(".maplibregl-ctrl-zoom-in").click();
  await sleep(1800);
  return page;
}

async function mapOnly(page) {
  await page.addStyleTag({ content: MAP_ONLY });
  await page.evaluate(() => window.dispatchEvent(new Event("resize")));
  await sleep(1500);
}

/** Steps the shadow time slider with the keyboard, as a person would with arrow keys. */
async function stepDay(rec, page, from, to, every) {
  const slider = page.getByLabel("Time of day");
  await slider.focus();
  await slider.evaluate((el, v) => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(el, String(v));
    el.dispatchEvent(new Event("input", { bubbles: true }));
  }, from);
  await sleep(300);
  for (let m = from; m < to; m += 10) {
    await page.keyboard.press("ArrowRight");
    await sleep(every);
  }
}

/** The tooltip of whatever is drawn at a map point, found by moving onto the outline's fill. */
async function pointAt(rec, page, x, y, label, hold = 3400) {
  await rec.moveTo(x, y, 900);
  rec.mark(label);
  await sleep(hold);
}

const TAKES = {
  async workflow(rec, name) {
    const page = await ready(rec);
    const results = page.locator("aside").last();
    const map = await page.locator("main").boundingBox();
    const cx = map.x + map.width / 2;
    const cy = map.y + map.height / 2;
    rec.startCapture(name);
    await sleep(1500);
    rec.mark("app-ready");
    await rec.moveTo(cx - 140, cy + 60, 1400);
    await sleep(700);
    await rec.moveTo(cx, cy, 900);
    await sleep(500);
    rec.mark("tap");
    await tapCentre(rec, page);
    rec.mark("measured");
    const names = page.waitForResponse((r) => r.url().endsWith("/site/names"), { timeout: 90000 });
    await rec.moveTo(cx + 120, cy - 150, 1200);
    await names;
    rec.mark("names-arrived");
    await sleep(1200);
    // Claude's name for the trees, then for something on the roof. Positions come from
    // scan-tips.cjs, run in this same setup (demo_assets/tips.json).
    await pointAt(rec, page, TIPS.trees[0], TIPS.trees[1], "tooltip-trees", 4200);
    await pointAt(rec, page, TIPS.stair[0], TIPS.stair[1], "tooltip-stair-room", 3600);
    await rec.moveTo(cx + 260, cy - 240, 900);
    await sleep(400);
    await rec.clickOn(page.getByRole("button", { name: "Shadows" }), { label: "shadows-view" });
    await sleep(900);
    rec.mark("day-start");
    await stepDay(rec, page, 8 * 60, 16 * 60 + 30, 140);
    rec.mark("day-end");
    await sleep(600);
    await rec.scroll(results, 700, 1300);
    rec.mark("what-shades-it");
    await sleep(4500);
    await rec.scroll(results, 420, 900);
    rec.mark("clear-hours");
    await sleep(3500);
    await rec.clickOn(page.getByRole("button", { name: "Year's sun" }), { label: "sun-view" });
    await sleep(800);
    await rec.scroll(results, 520, 1000);
    rec.mark("panels-card");
    await sleep(2500);
    await rec.type(page.getByLabel("Units in a typical month"), PROPERTY.units, { label: "type-units" });
    await sleep(900);
    const bill = page.getByLabel("Typical monthly bill");
    await bill.waitFor({ timeout: 20000 });
    await rec.type(bill, PROPERTY.bill, { label: "type-bill" });
    await page.getByText("YOUR SOLAR PLAN").waitFor({ timeout: 60000 });
    await sleep(700);
    await rec.scroll(results, -4000, 1100);
    rec.mark("plan");
    await sleep(2500);
    await pointAt(rec, page, TIPS.panel[0], TIPS.panel[1], "tooltip-panel-in-plan", 3800);
    await rec.scroll(results, 1900, 1600);
    rec.mark("generation-and-money");
    await sleep(5000);
    await rec.scroll(results, 900, 1100);
    rec.mark("money-notes");
    await sleep(4000);
    await rec.type(page.getByLabel("Your question"), PROPERTY.question, { label: "type-question", delay: 45 });
    await sleep(400);
    await rec.clickOn(page.getByRole("button", { name: "Ask", exact: true }), { label: "ask" });
    await sleep(600);
    await rec.scroll(results, 4000, 1000);
    rec.mark("waiting-for-answer");
    await page.getByText("Checking your figures").waitFor({ state: "detached", timeout: 180000 });
    rec.mark("answered");
    await sleep(600);
    await rec.scroll(results, 4000, 900);
    await sleep(9000);
    rec.mark("end");
    await rec.stopCapture();
  },

  async hook(rec, name) {
    const page = await ready(rec);
    await tapCentre(rec, page);
    await page.waitForResponse((r) => r.url().endsWith("/site/names"), { timeout: 90000 }).catch(() => {});
    await page.getByRole("button", { name: "Shadows" }).click();
    await page.getByLabel("Month", { exact: true }).selectOption("12");
    await mapOnly(page);
    await page.evaluate(() => (document.getElementById("demo-cursor").style.opacity = "0"));
    // Drag the map so the roof sits right of centre, clear of the hook's words on the left.
    await page.mouse.move(700, 430);
    await page.mouse.down();
    await page.mouse.move(855, 450, { steps: 25 });
    await page.mouse.up();
    await sleep(1500);
    rec.startCapture(name);
    await sleep(1000);
    rec.mark("sweep-start");
    await stepDay(rec, page, 7 * 60, 17 * 60 + 30, 125);
    rec.mark("sweep-end");
    await sleep(1500);
    await rec.stopCapture();
  },

  async close(rec, name) {
    const page = await ready(rec);
    await tapCentre(rec, page);
    await page.getByLabel("Units in a typical month").fill(PROPERTY.units);
    await page.getByLabel("Typical monthly bill").fill(PROPERTY.bill);
    await page.getByText("YOUR SOLAR PLAN").waitFor({ timeout: 60000 });
    await mapOnly(page);
    await page.evaluate(() => (document.getElementById("demo-cursor").style.opacity = "0"));
    await sleep(1500);
    rec.startCapture(name);
    rec.mark("hero");
    await sleep(15000);
    await rec.stopCapture();
  },
};

(async () => {
  const [which, suffix = ""] = process.argv.slice(2);
  for (const [take, run] of Object.entries(TAKES)) {
    if (which && which !== take) continue;
    const rec = new Recorder(`${OUT}/${take}`);
    try {
      await run(rec, `${take}${suffix}`);
    } catch (e) {
      console.error(`${take} failed:`, e.message);
    }
    await rec.close();
  }
  process.exit(0);
})();
