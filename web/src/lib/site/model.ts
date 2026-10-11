import { centroid, localFrame, type LngLat } from "../geo/local";

export interface SiteObstruction {
  id: number;
  /** tank, room, structure, wall, upper_level, building, tree or surroundings. */
  kind: string;
  name: string;
  on_surface: boolean;
  outline: LngLat[];
  /** Height above the surface panels would sit on. */
  height_above_m: number;
  area_m2: number;
  /** Gap between it and the surface; zero when it stands on the surface. */
  distance_m: number;
  bearing_deg: number;
  direction: string;
  elevation_deg: number;
}

export interface SiteSurface {
  kind: "roof" | "sloped_roof" | "ground" | "sloped_ground";
  area_m2: number;
  height_m: number;
  floors: number;
  tilt_deg: number;
  /** Compass bearing the surface faces, meaningful when it is sloped. */
  faces_deg: number;
  faces: string;
  found_by: "tap" | "outline";
  /** Share of a hand-drawn outline the surface takes up; low when the outline spans several roof faces. */
  covers?: number | null;
  cut_off: boolean;
}

/** One property on one pixel grid: heights, sunlight, what is where. */
export interface SiteModel {
  rows: number;
  cols: number;
  pixelM: number;
  /** Top-left, top-right, bottom-right, bottom-left of the grid. */
  corners: [LngLat, LngLat, LngLat, LngLat];
  /** Compass bearing of the grid's "up" direction; within a few degrees of north. */
  northDeg: number;
  /** Surface height in metres above the lowest point of the grid; NaN where unknown. Null when not measured. */
  heights: Float32Array | null;
  /** Share of open-sky sunlight reaching each pixel over a year, 0–1; NaN where unknown. */
  access: Float32Array;
  /** 0 nothing, 1 the surface, 2.. obstruction ids. */
  labels: Uint8Array;
  photo: string | null;
  outline: LngLat[];
  surface: SiteSurface;
  obstructions: SiteObstruction[];
  /** Whether this came from Google's 3D survey, or was estimated from what the user marked. */
  measured: boolean;
  /** Google's measured yearly sunlight for an open spot here, kWh per kW of panel; the scale `access` is a share of. */
  openSkyKwhPerKw: number | null;
  imageryDate: string | null;
  imageryQuality: string | null;
}

/** What the `/site` endpoint returns when it has a model. */
export interface SiteResponse {
  grid: { rows: number; cols: number; pixel_m: number; corners: [LngLat, LngLat, LngLat, LngLat] };
  heights_cm: string;
  height_floor_m: number;
  access: string;
  labels: string;
  photo: string | null;
  outline: LngLat[];
  surface: SiteSurface;
  obstructions: SiteObstruction[];
  sunlight?: { surface: number; open_sky: number; share: number };
  imagery_date: string | null;
  imagery_quality: string | null;
}

async function inflate(base64: string): Promise<ArrayBuffer> {
  const bytes = Uint8Array.from(atob(base64), (c) => c.charCodeAt(0));
  const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream("deflate"));
  return new Response(stream).arrayBuffer();
}

function northOf(corners: SiteModel["corners"]): number {
  const frame = localFrame(corners[3]);
  const [x, y] = frame.toXY(corners[0]);
  return (Math.atan2(x, y) * 180) / Math.PI;
}

/** Unpack the server's site model into arrays the simulations can use. */
export async function decodeSite(res: SiteResponse): Promise<SiteModel> {
  const [heightBytes, accessBytes, labelBytes] = await Promise.all([
    inflate(res.heights_cm),
    inflate(res.access),
    inflate(res.labels),
  ]);
  const cm = new Uint16Array(heightBytes);
  const heights = new Float32Array(cm.length);
  for (let i = 0; i < cm.length; i++) heights[i] = cm[i] === 65535 ? NaN : cm[i] / 100;
  const raw = new Uint8Array(accessBytes);
  const access = new Float32Array(raw.length);
  for (let i = 0; i < raw.length; i++) access[i] = raw[i] === 255 ? NaN : raw[i] / 250;

  return {
    rows: res.grid.rows,
    cols: res.grid.cols,
    pixelM: res.grid.pixel_m,
    corners: res.grid.corners,
    northDeg: northOf(res.grid.corners),
    heights,
    access,
    labels: new Uint8Array(labelBytes),
    photo: res.photo,
    outline: res.outline,
    surface: res.surface,
    obstructions: res.obstructions,
    measured: true,
    openSkyKwhPerKw: res.sunlight?.open_sky ?? null,
    imageryDate: res.imagery_date,
    imageryQuality: res.imagery_quality,
  };
}

/** Map position of a grid coordinate; (0, 0) is the top-left corner of the top-left pixel. */
export function gridToLngLat(m: Pick<SiteModel, "rows" | "cols" | "corners">, col: number, row: number): LngLat {
  const u = col / m.cols;
  const v = row / m.rows;
  const [tl, tr, br, bl] = m.corners;
  return [
    tl[0] * (1 - u) * (1 - v) + tr[0] * u * (1 - v) + br[0] * u * v + bl[0] * (1 - u) * v,
    tl[1] * (1 - u) * (1 - v) + tr[1] * u * (1 - v) + br[1] * u * v + bl[1] * (1 - u) * v,
  ];
}

/** Grid coordinate (column, row) of a map position. */
export function lngLatToGrid(m: Pick<SiteModel, "rows" | "cols" | "corners">, [lng, lat]: LngLat): [number, number] {
  const [tl, tr, , bl] = m.corners;
  const ax = tr[0] - tl[0];
  const ay = tr[1] - tl[1];
  const bx = bl[0] - tl[0];
  const by = bl[1] - tl[1];
  const det = ax * by - ay * bx;
  const dx = lng - tl[0];
  const dy = lat - tl[1];
  return [((dx * by - dy * bx) / det) * m.cols, ((ax * dy - ay * dx) / det) * m.rows];
}

export function surfaceCentre(m: SiteModel): LngLat {
  return m.outline.length ? centroid(m.outline) : gridToLngLat(m, m.cols / 2, m.rows / 2);
}

/**
 * A site model for a place Google has not surveyed, built from the shade
 * estimate on a hand-drawn roof. It has no heights, so shadows come from the
 * marked obstructions instead, but panels can still be laid out on it.
 */
export function modelFromCells(
  roof: LngLat[],
  cells: { polygon: LngLat[]; access: number }[],
  cellSizeM: number,
  heightM: number,
): SiteModel {
  const frame = localFrame(centroid(roof));
  const xy = roof.map(frame.toXY);
  const pad = cellSizeM;
  const minX = Math.min(...xy.map((p) => p[0])) - pad;
  const maxX = Math.max(...xy.map((p) => p[0])) + pad;
  const minY = Math.min(...xy.map((p) => p[1])) - pad;
  const maxY = Math.max(...xy.map((p) => p[1])) + pad;
  const cols = Math.max(1, Math.ceil((maxX - minX) / cellSizeM));
  const rows = Math.max(1, Math.ceil((maxY - minY) / cellSizeM));

  const access = new Float32Array(rows * cols).fill(NaN);
  const labels = new Uint8Array(rows * cols);
  for (const cell of cells) {
    const [x, y] = frame.toXY(cell.polygon[0]);
    const col = Math.floor((x + cellSizeM / 2 - minX) / cellSizeM);
    const row = Math.floor((maxY - (y + cellSizeM / 2)) / cellSizeM);
    if (col < 0 || col >= cols || row < 0 || row >= rows) continue;
    access[row * cols + col] = cell.access;
    labels[row * cols + col] = 1;
  }

  const right = minX + cols * cellSizeM;
  const bottom = maxY - rows * cellSizeM;
  const corners: SiteModel["corners"] = [
    frame.toLngLat([minX, maxY]),
    frame.toLngLat([right, maxY]),
    frame.toLngLat([right, bottom]),
    frame.toLngLat([minX, bottom]),
  ];
  return {
    rows,
    cols,
    pixelM: cellSizeM,
    corners,
    northDeg: 0,
    heights: null,
    access,
    labels,
    photo: null,
    outline: roof,
    surface: {
      kind: "roof",
      area_m2: cells.length * cellSizeM * cellSizeM,
      height_m: heightM,
      floors: Math.max(1, Math.round(heightM / 3)),
      tilt_deg: 0,
      faces_deg: 180,
      faces: "south",
      found_by: "outline",
      cut_off: false,
    },
    obstructions: [],
    measured: false,
    openSkyKwhPerKw: null,
    imageryDate: null,
    imageryQuality: null,
  };
}
