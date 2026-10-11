import { post } from "../api";
import { lngLatToGrid, type SiteModel, type SiteObstruction } from "./model";

/** What an obstruction is, as recognised in the photo. */
export interface ObstructionName {
  name: string;
  /** One sentence on what it is and what it means for the panels. */
  what: string;
  confidence: "high" | "medium" | "low";
}

const MAX_ITEMS = 12;
/** Obstructions causing less than this share of the shade are not worth naming. */
const MIN_SHARE = 0.02;
const MARGIN_M = 6;

function loadImage(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error("The property photo could not be loaded."));
    img.src = url;
  });
}

/**
 * The property photo with the surface outlined in white and each obstruction
 * outlined and numbered, cropped to what matters. Returned as base64 JPEG.
 */
async function annotate(model: SiteModel, items: SiteObstruction[]): Promise<string> {
  const photo = await loadImage(model.photo!);
  const outlines = [model.outline, ...items.map((o) => o.outline)].map((ring) => ring.map((p) => lngLatToGrid(model, p)));
  const margin = MARGIN_M / model.pixelM;
  const all = outlines.flat();
  const left = Math.max(0, Math.min(...all.map((p) => p[0])) - margin);
  const top = Math.max(0, Math.min(...all.map((p) => p[1])) - margin);
  const right = Math.min(model.cols, Math.max(...all.map((p) => p[0])) + margin);
  const bottom = Math.min(model.rows, Math.max(...all.map((p) => p[1])) + margin);

  // Enlarge so numbers and thin outlines stay legible, without making the upload large.
  const scale = Math.min(4, 1100 / Math.max(right - left, bottom - top));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round((right - left) * scale);
  canvas.height = Math.round((bottom - top) * scale);
  const ctx = canvas.getContext("2d")!;
  ctx.imageSmoothingQuality = "high";
  ctx.drawImage(photo, left, top, right - left, bottom - top, 0, 0, canvas.width, canvas.height);

  const trace = (ring: [number, number][]) => {
    ctx.beginPath();
    ring.forEach(([x, y], i) => ctx[i === 0 ? "moveTo" : "lineTo"]((x - left) * scale, (y - top) * scale));
    ctx.closePath();
    ctx.stroke();
  };
  ctx.lineJoin = "round";
  ctx.strokeStyle = "#ffffff";
  ctx.lineWidth = 3;
  trace(outlines[0]);

  items.forEach((item, i) => {
    const ring = outlines[i + 1];
    ctx.strokeStyle = item.on_surface ? "#ff3b30" : "#00e5ff";
    ctx.lineWidth = 2.5;
    trace(ring);
    const cx = (ring.reduce((s, p) => s + p[0], 0) / ring.length - left) * scale;
    const cy = (ring.reduce((s, p) => s + p[1], 0) / ring.length - top) * scale;
    ctx.fillStyle = item.on_surface ? "#ff3b30" : "#00838f";
    ctx.beginPath();
    ctx.arc(cx, cy, 13, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "#ffffff";
    ctx.font = "bold 15px sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(String(i + 1), cx, cy + 1);
  });
  return canvas.toDataURL("image/jpeg", 0.9).split(",")[1];
}

/**
 * Ask the vision model what each measured obstruction is. Returns names keyed
 * by obstruction id; empty when there is nothing worth naming or the model is
 * unavailable, in which case the names from the height data stand.
 */
export function nameObstructions(
  model: SiteModel,
  blame: Map<number, number> | null,
): Promise<Record<number, ObstructionName>> {
  // One paid request per property, however many times the screen asks.
  let request = requests.get(model);
  if (!request) {
    request = requestNames(model, blame);
    request.catch(() => requests.delete(model));
    requests.set(model, request);
  }
  return request;
}

const requests = new WeakMap<SiteModel, Promise<Record<number, ObstructionName>>>();

async function requestNames(model: SiteModel, blame: Map<number, number> | null): Promise<Record<number, ObstructionName>> {
  if (!model.photo) return {};
  const share = (o: SiteObstruction) => blame?.get(o.id) ?? 0;
  const items = model.obstructions
    .filter((o) => o.on_surface || share(o) >= MIN_SHARE)
    .sort((a, b) => share(b) - share(a))
    .slice(0, MAX_ITEMS);
  if (!items.length) return {};

  const land = model.surface.kind.includes("ground");
  const res = await post<{ items: { number: number; name: string; explanation: string; confidence: ObstructionName["confidence"] }[] }>(
    "/site/names",
    {
      image: await annotate(model, items),
      surface: land ? "land" : "roof",
      items: items.map((o, i) => ({
        number: i + 1,
        on_surface: o.on_surface,
        height_above_m: o.height_above_m,
        area_m2: o.area_m2,
        distance_m: o.distance_m,
        direction: o.direction,
        share_of_shade: blame ? Number(share(o).toFixed(2)) : null,
      })),
    },
  );
  const names: Record<number, ObstructionName> = {};
  for (const named of res.items) {
    const item = items[named.number - 1];
    const name = named.name.trim();
    if (item) names[item.id] = { name: name[0].toUpperCase() + name.slice(1), what: named.explanation, confidence: named.confidence };
  }
  return names;
}
