import { localFrame, centroid, type LngLat } from "../geo/local";
import { SATELLITE_TILES } from "../imagery";

const TILE = 256;
const ZOOM = 19;
const WORLD = TILE * 2 ** ZOOM;
const MARGIN_M = 25;
export const CAPTURE_SIZE = 768;

const toWorld = ([lng, lat]: LngLat): [number, number] => {
  const s = Math.sin((lat * Math.PI) / 180);
  return [((lng + 180) / 360) * WORLD, (0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI)) * WORLD];
};
const fromWorld = (x: number, y: number): LngLat => [
  (x / WORLD) * 360 - 180,
  (Math.atan(Math.sinh(Math.PI * (1 - (2 * y) / WORLD))) * 180) / Math.PI,
];

function loadTile(x: number, y: number): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error("Couldn't load the satellite image for this roof."));
    img.src = SATELLITE_TILES.replace("{z}", String(ZOOM)).replace("{x}", String(x)).replace("{y}", String(y));
  });
}

export interface RoofCapture {
  /** Base64 JPEG without the data-URL prefix. */
  image: string;
  size: number;
  metresPerPixel: number;
  toLngLat(p: { x: number; y: number }): LngLat;
}

/**
 * A square, north-up satellite picture of the roof and its surroundings with
 * the roof outlined in yellow, plus the mapping from its pixels back to the map.
 */
export async function captureRoof(roof: LngLat[]): Promise<RoofCapture> {
  const frame = localFrame(centroid(roof));
  const xy = roof.map(frame.toXY);
  const reach = Math.max(...xy.map(([x, y]) => Math.max(Math.abs(x), Math.abs(y)))) + MARGIN_M;
  const [left, top] = toWorld(frame.toLngLat([-reach, reach]));
  const [right] = toWorld(frame.toLngLat([reach, -reach]));
  const span = right - left;
  const scale = CAPTURE_SIZE / span;

  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = CAPTURE_SIZE;
  const ctx = canvas.getContext("2d")!;
  ctx.imageSmoothingQuality = "high";

  const jobs: Promise<void>[] = [];
  for (let tx = Math.floor(left / TILE); tx <= Math.floor((left + span) / TILE); tx++) {
    for (let ty = Math.floor(top / TILE); ty <= Math.floor((top + span) / TILE); ty++) {
      jobs.push(
        loadTile(tx, ty).then((img) => {
          ctx.drawImage(img, (tx * TILE - left) * scale, (ty * TILE - top) * scale, TILE * scale, TILE * scale);
        }),
      );
    }
  }
  await Promise.all(jobs);

  ctx.strokeStyle = "#ffe600";
  ctx.lineWidth = 2;
  ctx.beginPath();
  roof.forEach((p, i) => {
    const [wx, wy] = toWorld(p);
    ctx[i === 0 ? "moveTo" : "lineTo"]((wx - left) * scale, (wy - top) * scale);
  });
  ctx.closePath();
  ctx.stroke();

  return {
    image: canvas.toDataURL("image/jpeg", 0.92).split(",")[1],
    size: CAPTURE_SIZE,
    metresPerPixel: (2 * reach) / CAPTURE_SIZE,
    toLngLat: ({ x, y }) => fromWorld(left + x / scale, top + y / scale),
  };
}
