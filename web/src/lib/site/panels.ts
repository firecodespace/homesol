import type { LngLat } from "../geo/local";
import { sunAt } from "../solar/sun";
import { solarNoon } from "../time";
import { gridToLngLat, lngLatToGrid, surfaceCentre, type SiteModel } from "./model";

const DEG = Math.PI / 180;
/** A typical 550 W residential panel, long and short side in metres. */
export const PANEL_LONG_M = 2.278;
export const PANEL_SHORT_M = 1.134;
export const PANEL_WATTS = 550;
/** Clear strip kept along every edge of the surface, for safety, wind and access. */
const EDGE_SETBACK_M = 0.5;
/** Gap between neighbouring panels in a row. */
const PANEL_GAP_M = 0.02;
/** A panel position is worth using when it gets at least this share of open-sky sun. */
export const GOOD_ACCESS = 0.85;

export interface Panel {
  /** Corners of the panel's footprint on the map. */
  corners: LngLat[];
  /** Share of open-sky sunlight this position gets over a year, 0–1. */
  access: number;
  /** Row number, counted from the edge the panels face. */
  row: number;
}

export interface PanelLayout {
  /**
   * Every position a panel physically fits. The good ones come first, in the order a system
   * would grow: starting from the sunniest and spreading to its neighbours.
   */
  panels: Panel[];
  /** How many of them get good sun. */
  good: number;
  /** Tilt of each panel from horizontal. */
  tiltDeg: number;
  /** Compass bearing the panels face. */
  facingDeg: number;
  /** Distance from the front of one row to the front of the next. */
  rowPitchM: number;
  /** Tilted rows on a flat surface, or flat against a slope. */
  mounting: "tilted rows" | "flush on the slope";
}

/** Tilt for panels on a flat surface: roughly the latitude, kept within what mounting frames allow. */
export function flatSurfaceTilt(lat: number): number {
  return Math.round(Math.min(25, Math.max(10, Math.abs(lat))));
}

/**
 * Space to leave behind a tilted row so it does not shade the row behind it
 * on a winter morning: the shadow of the row's top edge two and a half hours
 * before solar noon on the shortest day.
 */
export function rowGap(at: LngLat, riseM: number, facingDeg: number): number {
  const winterMonth = at[1] >= 0 ? 12 : 6;
  const morning = new Date(solarNoon(2026, winterMonth, 21, at[0]).getTime() - 2.5 * 3_600_000);
  const sun = sunAt(morning, at);
  if (sun.elevation < 8) return riseM * 3;
  const along = Math.abs(Math.cos((sun.azimuth - facingDeg) * DEG));
  return Math.min(riseM * 3, Math.max(0.3, (riseM * along) / Math.tan(sun.elevation * DEG)));
}

/**
 * Direction the building's edges run, as a compass bearing between 0 and 90.
 * Null when the outline has no clear grid to it.
 */
function edgeDirection(model: SiteModel): number | null {
  const points = model.outline.map((p) => lngLatToGrid(model, p));
  const edges: { bearing: number; length: number }[] = [];
  const bins = new Float64Array(30);
  let total = 0;
  for (let i = 0; i < points.length; i++) {
    const [x1, y1] = points[i];
    const [x2, y2] = points[(i + 1) % points.length];
    const length = Math.hypot(x2 - x1, y2 - y1);
    // Rows run south, so north is -y. Fold every edge into one quarter turn.
    const bearing = ((Math.atan2(x2 - x1, -(y2 - y1)) / DEG + model.northDeg) % 90 + 90) % 90;
    edges.push({ bearing, length });
    bins[Math.floor(bearing / 3) % 30] += length;
    total += length;
  }
  if (!total) return null;
  // Edges at 89° and 1° are the same direction, so the busiest stretch may wrap around.
  let best = 0;
  const around = (i: number) => bins[(i + 29) % 30] + bins[i] + bins[(i + 1) % 30];
  for (let i = 1; i < 30; i++) if (around(i) > around(best)) best = i;
  if (around(best) < 0.45 * total) return null;
  // Average the edges near that direction. Multiplying angles by four makes the quarter turn a full circle.
  const centre = best * 3 + 1.5;
  let sin = 0;
  let cos = 0;
  for (const { bearing, length } of edges) {
    const off = Math.abs(((bearing - centre + 135) % 90) - 45);
    if (off > 6) continue;
    sin += length * Math.sin(4 * bearing * DEG);
    cos += length * Math.cos(4 * bearing * DEG);
  }
  return ((Math.atan2(sin, cos) / DEG / 4) % 90 + 90) % 90;
}

/** The bearing panels on a flat surface should face: the building's own direction nearest the equator. */
function flatFacing(model: SiteModel, lat: number): number {
  const equator = lat >= 0 ? 180 : 0;
  const edge = model.surface.kind === "roof" ? edgeDirection(model) : null;
  if (edge === null) return equator;
  let best = edge;
  for (let k = 0; k < 4; k++) {
    const candidate = (edge + k * 90) % 360;
    const off = Math.abs(((candidate - equator + 540) % 360) - 180);
    if (off < Math.abs(((best - equator + 540) % 360) - 180)) best = candidate;
  }
  return best;
}

/**
 * Lay panels out on the surface.
 *
 * On a flat roof or open ground the panels stand in tilted rows facing the
 * equator, lined up with the building, with enough room between rows that one
 * does not shade the next in winter. On a slope they lie flat against it. A
 * panel is placed only where its whole footprint is on the surface and clear
 * of the edge; rooftop structures are not surface, so panels go around them.
 */
export function layoutPanels(model: SiteModel): PanelLayout {
  const { rows, cols, pixelM, labels, access } = model;
  const at = surfaceCentre(model);
  const sloped = model.surface.kind.startsWith("sloped");
  const tiltDeg = sloped ? model.surface.tilt_deg : flatSurfaceTilt(at[1]);
  const facingDeg = sloped ? model.surface.faces_deg : flatFacing(model, at[1]);
  const depth = PANEL_SHORT_M * Math.cos(tiltDeg * DEG);
  const gap = sloped ? PANEL_GAP_M : rowGap(at, PANEL_SHORT_M * Math.sin(tiltDeg * DEG), facingDeg);
  const rowPitchM = depth + gap;
  const colPitchM = PANEL_LONG_M + PANEL_GAP_M;

  // Usable pixels: on the surface, with data, and at least the setback from anything that is not.
  const usable = new Uint8Array(rows * cols);
  const setback = Math.max(1, Math.round(EDGE_SETBACK_M / pixelM));
  for (let i = 0; i < usable.length; i++) usable[i] = labels[i] === 1 && Number.isFinite(access[i]) ? 1 : 0;
  for (let pass = 0; pass < setback; pass++) {
    const before = usable.slice();
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        const i = r * cols + c;
        if (!before[i]) continue;
        const inside = r > 0 && c > 0 && r < rows - 1 && c < cols - 1;
        if (!inside || !before[i - 1] || !before[i + 1] || !before[i - cols] || !before[i + cols]) usable[i] = 0;
      }
    }
  }

  // Work in metres, east and north of the grid's top-left corner, turned to the grid's own up.
  const turn = (facingDeg - model.northDeg) * DEG;
  const facing: [number, number] = [Math.sin(turn), Math.cos(turn)];
  const along: [number, number] = [Math.cos(turn), -Math.sin(turn)];
  let minU = Infinity;
  let maxU = -Infinity;
  let minV = Infinity;
  let maxV = -Infinity;
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      if (!usable[r * cols + c]) continue;
      const x = (c + 0.5) * pixelM;
      const y = -(r + 0.5) * pixelM;
      const u = x * along[0] + y * along[1];
      const v = x * facing[0] + y * facing[1];
      if (u < minU) minU = u;
      if (u > maxU) maxU = u;
      if (v < minV) minV = v;
      if (v > maxV) maxV = v;
    }
  }
  const empty: PanelLayout = { panels: [], good: 0, tiltDeg, facingDeg, rowPitchM, mounting: sloped ? "flush on the slope" : "tilted rows" };
  if (!Number.isFinite(minU)) return empty;

  const step = Math.min(pixelM, 0.25);
  const samplesU = Math.max(2, Math.ceil(PANEL_LONG_M / step));
  const samplesV = Math.max(2, Math.ceil(depth / step));
  const toGrid = (u: number, v: number): [number, number] => {
    const x = u * along[0] + v * facing[0];
    const y = u * along[1] + v * facing[1];
    return [x / pixelM, -y / pixelM];
  };

  /** Mean access under a panel centred at (u, v), or -1 if any part of it is off the usable area. */
  const fit = (u: number, v: number): number => {
    let sum = 0;
    for (let a = 0; a <= samplesU; a++) {
      for (let b = 0; b <= samplesV; b++) {
        const [col, row] = toGrid(u + (a / samplesU - 0.5) * PANEL_LONG_M, v + (b / samplesV - 0.5) * depth);
        const c = Math.floor(col);
        const r = Math.floor(row);
        if (c < 0 || r < 0 || c >= cols || r >= rows || !usable[r * cols + c]) return -1;
        sum += access[r * cols + c];
      }
    }
    return sum / ((samplesU + 1) * (samplesV + 1));
  };

  // Try the grid at a few offsets and keep the one that fits most panels.
  let best: { u: number; v: number; access: number; row: number }[] = [];
  for (let shiftV = 0; shiftV < 3; shiftV++) {
    for (let shiftU = 0; shiftU < 3; shiftU++) {
      const placed: typeof best = [];
      // Rows are counted from the front: the edge the panels face.
      let rowNumber = 0;
      for (let v = maxV - depth / 2 - (shiftV / 3) * rowPitchM; v >= minV + depth / 2; v -= rowPitchM) {
        rowNumber++;
        for (let u = minU + PANEL_LONG_M / 2 + (shiftU / 3) * colPitchM; u <= maxU - PANEL_LONG_M / 2; u += colPitchM) {
          const mean = fit(u, v);
          if (mean >= 0) placed.push({ u, v, access: mean, row: rowNumber });
        }
      }
      if (placed.length > best.length) best = placed;
    }
  }

  const good = planOrder(
    best.filter((p) => p.access >= GOOD_ACCESS),
    Math.max(colPitchM, rowPitchM) * 1.15,
  );
  const rest = best.filter((p) => p.access < GOOD_ACCESS).sort((p, q) => q.access - p.access);
  const panels = [...good, ...rest].map(({ u, v, access: mean, row }): Panel => ({
    corners: (
      [
        [-0.5, -0.5],
        [0.5, -0.5],
        [0.5, 0.5],
        [-0.5, 0.5],
      ] as const
    ).map(([a, b]) => {
      const [col, r] = toGrid(u + a * PANEL_LONG_M, v + b * depth);
      return gridToLngLat(model, col, r);
    }),
    access: mean,
    row,
  }));
  return { ...empty, panels, good: good.length };
}

/**
 * The order in which positions join a growing system: the sunniest first, then
 * always a neighbour of what is already placed, so a system of any size is one
 * tidy block of panels and not the sunniest spots scattered across the surface.
 */
function planOrder<T extends { u: number; v: number; access: number }>(positions: T[], reach: number): T[] {
  const n = positions.length;
  if (n < 2) return positions;
  const centreU = positions.reduce((s, p) => s + p.u, 0) / n;
  const centreV = positions.reduce((s, p) => s + p.v, 0) / n;
  // Sun differences of a couple of percent are within the data's noise; do not let them break up the block.
  const band = positions.map((p) => Math.round(p.access / 0.03));

  // Which positions sit next to which.
  const neighbours: number[][] = positions.map(() => []);
  for (let i = 0; i < n; i++) {
    for (let j = i + 1; j < n; j++) {
      if (Math.abs(positions[i].u - positions[j].u) <= reach && Math.abs(positions[i].v - positions[j].v) <= reach) {
        neighbours[i].push(j);
        neighbours[j].push(i);
      }
    }
  }

  const placed = new Uint8Array(n);
  const frontier = new Set<number>();
  const order: number[] = [];
  let sumU = 0;
  let sumV = 0;
  const better = (i: number, j: number, toU: number, toV: number) =>
    j < 0 ||
    band[i] > band[j] ||
    (band[i] === band[j] &&
      Math.hypot(positions[i].u - toU, positions[i].v - toV) < Math.hypot(positions[j].u - toU, positions[j].v - toV));

  while (order.length < n) {
    const cu = order.length ? sumU / order.length : centreU;
    const cv = order.length ? sumV / order.length : centreV;
    let next = -1;
    for (const i of frontier) if (better(i, next, cu, cv)) next = i;
    // Nothing touches the block: start, or start again, from the best position not yet placed.
    if (next < 0) for (let i = 0; i < n; i++) if (!placed[i] && better(i, next, cu, cv)) next = i;
    placed[next] = 1;
    frontier.delete(next);
    order.push(next);
    sumU += positions[next].u;
    sumV += positions[next].v;
    for (const j of neighbours[next]) if (!placed[j]) frontier.add(j);
  }
  return order.map((i) => positions[i]);
}
