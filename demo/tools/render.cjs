// Renders a graphics scene (demo/graphics/<scene>.html) frame by frame at 1920x1080, 30 fps.
//
//   NODE_PATH=$(npm root -g) node demo/tools/render.cjs <scene> <seconds> <out> [--alpha] [--p '<json>'] [--stills t1,t2]
//
// Opaque scenes are written as lossless RGB H.264 (.mkv); --alpha scenes keep transparency as
// PNG-in-MOV, for laying over the app footage in the edit.

const http = require("node:http");
const fs = require("node:fs");
const path = require("node:path");
const { spawn } = require("node:child_process");
const { chromium } = require("playwright");

const FPS = 30;
const ROOT = path.join(__dirname, "..", "graphics");
const TYPES = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg" };

function serve() {
  const server = http.createServer((req, res) => {
    const file = path.join(ROOT, decodeURIComponent(new URL(req.url, "http://x").pathname));
    if (!file.startsWith(ROOT) || !fs.existsSync(file)) return res.writeHead(404).end();
    res.writeHead(200, { "Content-Type": TYPES[path.extname(file)] ?? "application/octet-stream" });
    fs.createReadStream(file).pipe(res);
  });
  return new Promise((r) => server.listen(0, "127.0.0.1", () => r(server)));
}

(async () => {
  const [scene, seconds, out, ...rest] = process.argv.slice(2);
  const alpha = rest.includes("--alpha");
  const p = rest.includes("--p") ? rest[rest.indexOf("--p") + 1] : "{}";
  const frames = Math.round(Number(seconds) * FPS);
  const server = await serve();
  const browser = await chromium.launch({ args: ["--force-color-profile=srgb", "--font-render-hinting=none"] });
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
  page.on("pageerror", (e) => console.error("PAGE ERROR", e.message));
  await page.goto(`http://127.0.0.1:${server.address().port}/${scene}.html?p=${encodeURIComponent(p)}`);
  await page.waitForFunction(() => window.READY === true, null, { timeout: 30000 });

  fs.mkdirSync(path.dirname(out), { recursive: true });
  if (rest.includes("--stills")) {
    // Single frames for checking a layout: <out>_<t>.png for each time given.
    for (const t of rest[rest.indexOf("--stills") + 1].split(",").map(Number)) {
      await page.evaluate((tt) => window.seek(tt), t);
      await page.screenshot({ path: `${out}_${t}.png`, omitBackground: alpha });
    }
    await browser.close();
    server.close();
    return;
  }
  const codec = alpha
    ? ["-c:v", "png", "-pix_fmt", "rgba"]
    : ["-c:v", "libx264rgb", "-preset", "veryfast", "-crf", "0", "-pix_fmt", "rgb24"];
  const ffmpeg = spawn("ffmpeg", ["-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", String(FPS), "-c:v", "png", "-i", "-", ...codec, out], {
    stdio: ["pipe", "inherit", "inherit"],
  });
  const started = Date.now();
  for (let i = 0; i < frames; i++) {
    await page.evaluate((t) => window.seek(t), i / FPS);
    const png = await page.screenshot({ type: "png", omitBackground: alpha });
    if (!ffmpeg.stdin.write(png)) await new Promise((r) => ffmpeg.stdin.once("drain", r));
  }
  ffmpeg.stdin.end();
  await new Promise((r) => ffmpeg.on("close", r));
  await browser.close();
  server.close();
  console.log(`${out}: ${frames} frames in ${((Date.now() - started) / 1000).toFixed(1)} s`);
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
