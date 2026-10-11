// Screen-recording harness for the homesol demo.
//
// A real, headed Chromium window fills a virtual 1920x1080 X display; ffmpeg captures that
// display at 30 fps. Playwright drives the page, but its input does not move the X pointer, so
// a cursor is drawn inside the page instead: an arrow that follows every mousemove, with a
// ripple on each press. Every action is logged with its time from the start of the capture,
// so the edit can cut to the exact frame where something happens.
//
// Run scripts with:  NODE_PATH=$(npm root -g) node demo/tools/<take>.cjs

const { spawn, execSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");

const W = 1920;
const H = 1080;
const DISPLAY = process.env.DEMO_DISPLAY || ":99";
const SCALE = Number(process.env.DEMO_SCALE || 1.25);
/** The page's own size in CSS pixels; cursor positions are in these units. */
const VW = Math.round(W / SCALE);
const VH = Math.round(H / SCALE);

/** The in-page cursor: an arrow with a soft shadow, and a ripple where it clicks. */
const CURSOR_SCRIPT = `
(() => {
  if (window.__demoCursor) return;
  window.__demoCursor = true;
  const install = () => {
    const style = document.createElement("style");
    style.textContent = \`
      #demo-cursor { position: fixed; left: 0; top: 0; width: 28px; height: 28px; z-index: 2147483647;
        pointer-events: none; transform: translate(-100px, -100px); will-change: transform;
        filter: drop-shadow(0 2px 3px rgba(0,0,0,.35)); }
      .demo-ripple { position: fixed; z-index: 2147483646; pointer-events: none; width: 44px; height: 44px;
        margin: -22px 0 0 -22px; border-radius: 50%; border: 3px solid rgba(250, 204, 21, .95);
        background: rgba(250, 204, 21, .22); animation: demo-ripple .55s ease-out forwards; }
      @keyframes demo-ripple { from { transform: scale(.35); opacity: 1 } to { transform: scale(1.25); opacity: 0 } }
      * { cursor: none !important; }
    \`;
    document.head.appendChild(style);
    const cursor = document.createElement("div");
    cursor.id = "demo-cursor";
    cursor.innerHTML = '<svg viewBox="0 0 28 28" width="28" height="28"><path d="M5 3 L5 22 L10 17.5 L13.5 25 L17 23.5 L13.6 16.2 L20 16.2 Z" fill="#fff" stroke="#211a13" stroke-width="1.6" stroke-linejoin="round"/></svg>';
    document.body.appendChild(cursor);
    const at = (x, y) => (cursor.style.transform = "translate(" + (x - 5) + "px," + (y - 3) + "px)");
    window.addEventListener("mousemove", (e) => at(e.clientX, e.clientY), true);
    window.addEventListener("mousedown", (e) => {
      const r = document.createElement("div");
      r.className = "demo-ripple";
      r.style.left = e.clientX + "px";
      r.style.top = e.clientY + "px";
      document.body.appendChild(r);
      setTimeout(() => r.remove(), 600);
    }, true);
    if (window.__demoLast) at(window.__demoLast[0], window.__demoLast[1]);
  };
  if (document.body) install();
  else document.addEventListener("DOMContentLoaded", install);
})();
`;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const ease = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);

function startDisplay() {
  const socket = `/tmp/.X11-unix/X${DISPLAY.slice(1)}`;
  if (fs.existsSync(socket)) return null;
  const xvfb = spawn("Xvfb", [DISPLAY, "-screen", "0", `${W}x${H}x24`, "-ac", "-nolisten", "tcp"], {
    stdio: "ignore",
    detached: true,
  });
  for (let i = 0; i < 100 && !fs.existsSync(socket); i++) execSync("sleep 0.05");
  return xvfb;
}

class Recorder {
  constructor(outDir) {
    this.outDir = outDir;
    fs.mkdirSync(outDir, { recursive: true });
    this.pos = [VW / 2, VH / 2];
    this.marks = [];
    this.ffmpeg = null;
    this.t0 = null;
  }

  async open(url, { storage } = {}) {
    this.xvfb = startDisplay();
    if (this.xvfb) process.once("exit", () => process.kill(-this.xvfb.pid));
    // A persistent context opens Chromium's own first window, which honours kiosk mode: no tabs,
    // no address bar, just the page.
    this.profile = fs.mkdtempSync("/tmp/demo-profile-");
    this.context = await chromium.launchPersistentContext(this.profile, {
      headless: false,
      viewport: null,
      locale: "en-IN",
      env: { ...process.env, DISPLAY },
      // Without this flag Chromium shows a "controlled by automated test software" bar.
      ignoreDefaultArgs: ["--enable-automation"],
      args: [
        // Chromium sizes windows in scaled pixels, so this fills the 1920x1080 screen exactly.
        `--window-size=${VW},${VH}`,
        "--window-position=0,0",
        "--kiosk",
        // UI text is drawn 1.25x larger, so it reads clearly in a 1080p video.
        `--force-device-scale-factor=${SCALE}`,
        "--enable-unsafe-swiftshader",
        "--ignore-gpu-blocklist",
        "--hide-scrollbars",
        "--disable-infobars",
        "--noerrdialogs",
        "--disable-features=Translate,MediaRouter",
        "--autoplay-policy=no-user-gesture-required",
      ],
    });
    await this.context.addInitScript(CURSOR_SCRIPT);
    if (storage) {
      // Seed the browser's saved survey before the app reads it.
      await this.context.addInitScript((s) => {
        if (!sessionStorage.getItem("demo-seeded")) {
          for (const [k, v] of Object.entries(s)) localStorage.setItem(k, v);
          sessionStorage.setItem("demo-seeded", "1");
        }
      }, storage);
    }
    this.page = this.context.pages()[0] ?? (await this.context.newPage());
    this.page.on("pageerror", (e) => this.log("PAGE ERROR " + e.message));
    this.page.on("console", (m) => m.type() === "error" && this.log("console.error " + m.text().slice(0, 160)));
    if (url) await this.page.goto(url, { waitUntil: "domcontentloaded" });
    await this.page.mouse.move(this.pos[0], this.pos[1]);
    return this.page;
  }

  log(text) {
    const t = this.t0 ? ((Date.now() - this.t0) / 1000).toFixed(2) : "-";
    console.log(`[${t}] ${text}`);
  }

  /** Begin capturing the display to `<name>.mkv`: lossless RGB, so the edit starts from clean pixels. */
  startCapture(name) {
    this.name = name;
    this.file = path.join(this.outDir, `${name}.mkv`);
    this.ffmpeg = spawn(
      "ffmpeg",
      [
        "-y", "-loglevel", "error", "-thread_queue_size", "1024",
        "-f", "x11grab", "-draw_mouse", "0", "-framerate", "30", "-video_size", `${W}x${H}`, "-i", `${DISPLAY}.0`,
        "-c:v", "libx264rgb", "-preset", "ultrafast", "-crf", "0", "-g", "30",
        this.file,
      ],
      { stdio: ["pipe", "ignore", fs.openSync(path.join(this.outDir, `${name}.ffmpeg.log`), "w")] },
    );
    // A take that dies must not leave ffmpeg capturing forever.
    const ffmpeg = this.ffmpeg;
    process.once("exit", () => ffmpeg.exitCode === null && ffmpeg.kill("SIGINT"));
    this.t0 = Date.now();
    this.marks = [];
    this.mark("capture-start");
  }

  mark(label, extra = {}) {
    const t = this.t0 ? (Date.now() - this.t0) / 1000 : 0;
    this.marks.push({ t: Number(t.toFixed(3)), label, ...extra });
    this.log(label);
  }

  async stopCapture() {
    this.mark("capture-end");
    const done = new Promise((r) => this.ffmpeg.on("close", r));
    this.ffmpeg.stdin.write("q");
    await done;
    // The capture's timestamps are wall-clock; its first frame's time against `t0` gives the exact
    // offset of every mark within the file.
    let offset = 0;
    try {
      const first = Number(execSync(`ffprobe -v error -show_entries format=start_time -of csv=p=0 "${this.file}"`).toString());
      offset = Number((this.t0 / 1000 - first).toFixed(3));
    } catch {}
    const marks = this.marks.map((m) => ({ ...m, t: Number((m.t + offset).toFixed(3)) }));
    fs.writeFileSync(path.join(this.outDir, `${this.name}.marks.json`), JSON.stringify({ offset, marks }, null, 2));
    this.ffmpeg = null;
  }

  /** Glide the cursor to (x, y) along an eased path, the way a person moves a mouse. */
  async moveTo(x, y, ms) {
    const [x0, y0] = this.pos;
    const distance = Math.hypot(x - x0, y - y0);
    const duration = ms ?? Math.min(1100, 350 + distance * 0.55);
    const steps = Math.max(2, Math.round(duration / 16));
    // A slight arc reads as a hand, not a robot.
    const bend = Math.min(60, distance * 0.08);
    const nx = -(y - y0) / (distance || 1);
    const ny = (x - x0) / (distance || 1);
    for (let i = 1; i <= steps; i++) {
      const k = ease(i / steps);
      const arc = Math.sin(Math.PI * k) * bend;
      await this.page.mouse.move(x0 + (x - x0) * k + nx * arc, y0 + (y - y0) * k + ny * arc);
      await sleep(duration / steps);
    }
    this.pos = [x, y];
    await this.page.evaluate(([px, py]) => (window.__demoLast = [px, py]), [x, y]).catch(() => {});
  }

  async click(x, y, { label, hold = 90 } = {}) {
    await this.moveTo(x, y);
    await sleep(140);
    if (label) this.mark(label);
    await this.page.mouse.down();
    await sleep(hold);
    await this.page.mouse.up();
  }

  /** Move to the middle of an element and click it. */
  async clickOn(locator, opts = {}) {
    await locator.waitFor({ state: "visible", timeout: opts.timeout ?? 30000 });
    await locator.scrollIntoViewIfNeeded();
    const box = await locator.boundingBox();
    await this.click(box.x + box.width / 2 + (opts.dx ?? 0), box.y + box.height / 2 + (opts.dy ?? 0), opts);
  }

  async hover(locator, opts = {}) {
    const box = await locator.boundingBox();
    await this.moveTo(box.x + box.width / 2 + (opts.dx ?? 0), box.y + box.height / 2 + (opts.dy ?? 0), opts.ms);
  }

  /** Type into a field at a human pace. */
  async type(locator, text, { delay = 55, label } = {}) {
    await this.clickOn(locator);
    if (label) this.mark(label);
    await locator.press("Control+a");
    await locator.press("Backspace");
    for (const ch of text) {
      await this.page.keyboard.type(ch);
      await sleep(delay + Math.random() * delay * 0.6);
    }
  }

  /** Scroll an element's box by `dy` pixels smoothly, as a trackpad would. */
  async scroll(locator, dy, ms = 900) {
    const box = await locator.boundingBox();
    await this.moveTo(box.x + box.width / 2, Math.min(box.y + box.height / 2, VH - 100));
    const steps = Math.round(ms / 16);
    let done = 0;
    for (let i = 1; i <= steps; i++) {
      const target = Math.round(dy * ease(i / steps));
      await this.page.mouse.wheel(0, target - done);
      done = target;
      await sleep(16);
    }
  }

  async close() {
    if (this.ffmpeg) await this.stopCapture();
    // A headed persistent context can hang on close; the process ends either way.
    await Promise.race([this.context?.close(), sleep(4000)]);
  }
}

module.exports = { Recorder, sleep, W, H, VW, VH };
