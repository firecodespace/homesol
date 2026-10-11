import {
  centroid,
  localFrame,
  pointInPolygon,
  polygonArea,
  segmentHitsPolygon,
  type LngLat,
  type XY,
} from "../geo/local";
import { sunBlockedByHorizon, type HorizonProfile } from "./horizon";
import { solarNoon } from "../time";
import { sunAt, type SunPosition } from "./sun";

const DEG = Math.PI / 180;
const MIN_SUN_ELEVATION = 5;
const MAX_CELLS = 2500;
const MIN_CELL_M = 0.5;
/** A cell is worth a panel if it keeps at least this share of its yearly sun. */
export const USABLE_ACCESS = 0.85;
/** Roof area one kW of panels needs, including walkways and row spacing. */
export const AREA_PER_KW_M2 = 10;

export interface ShadingObstruction {
  footprint: LngLat[];
  heightM: number;
  /** Whether `heightM` is measured from the ground or from the roof surface. */
  reference: "ground" | "roof";
}

export interface ShadingCell {
  polygon: LngLat[];
  /** Share of the year's direct sun this cell receives, 0–1. */
  access: number;
}

export interface ShadingResult {
  cells: ShadingCell[];
  cellSizeM: number;
  roofAreaM2: number;
  usableAreaM2: number;
  meanAccess: number;
  /** Mean access over just the cells good enough for panels. */
  usableAccess: number;
  capacityKw: number;
}

/** Roll per-cell solar access up into the roof-level figures. */
export function summariseCells(cells: ShadingCell[], cellSizeM: number, roofAreaM2: number): ShadingResult {
  const cellArea = cellSizeM * cellSizeM;
  const usable = cells.filter((c) => c.access >= USABLE_ACCESS);
  const usableAreaM2 = Math.min(roofAreaM2, usable.length * cellArea);
  return {
    cells,
    cellSizeM,
    roofAreaM2,
    usableAreaM2,
    meanAccess: cells.length ? cells.reduce((s, c) => s + c.access, 0) / cells.length : 0,
    usableAccess: usable.length ? usable.reduce((s, c) => s + c.access, 0) / usable.length : 0,
    capacityKw: usableAreaM2 / AREA_PER_KW_M2,
  };
}

function heightAboveRoof(o: ShadingObstruction, roofHeightM: number): number {
  return o.reference === "ground" ? o.heightM - roofHeightM : o.heightM;
}

/** Unit vector pointing horizontally towards the sun, in east/north metres. */
function sunDirection(sun: SunPosition): XY {
  return [Math.sin(sun.azimuth * DEG), Math.cos(sun.azimuth * DEG)];
}

/** Half-hourly daytime sun positions on the 21st of every month, wherever in the world `at` is. */
function yearlySunSamples(at: LngLat): SunPosition[] {
  const samples: SunPosition[] = [];
  for (let month = 1; month <= 12; month++) {
    const noon = solarNoon(2026, month, 21, at[0]).getTime();
    for (let k = -18; k <= 18; k++) {
      const sun = sunAt(new Date(noon + k * 30 * 60_000), at);
      if (sun.elevation >= MIN_SUN_ELEVATION) samples.push(sun);
    }
  }
  return samples;
}

/**
 * Yearly solar access across a flat roof.
 *
 * Each obstruction is a vertical prism. A roof point is shaded when the ray
 * towards the sun passes over the prism's footprint while still below its top,
 * i.e. within a horizontal reach of height / tan(elevation). Samples are
 * weighted by sin(elevation), which tracks direct irradiance on a flat surface.
 *
 * A scanned `horizon` shades the whole roof whenever the sun is below the
 * skyline, on top of whatever the prisms block.
 */
export function analyseShading(
  roof: LngLat[],
  roofHeightM: number,
  obstructions: ShadingObstruction[],
  horizon: HorizonProfile | null = null,
): ShadingResult {
  const origin = centroid(roof);
  const frame = localFrame(origin);
  const roofXY = roof.map(frame.toXY);
  const roofAreaM2 = polygonArea(roofXY);
  const cellSizeM = Math.max(MIN_CELL_M, Math.sqrt(roofAreaM2 / MAX_CELLS));

  const prisms = obstructions
    .map((o) => ({ footprint: o.footprint.map(frame.toXY), height: heightAboveRoof(o, roofHeightM) }))
    .filter((p) => p.height > 0 && p.footprint.length >= 3);

  const samples = yearlySunSamples(origin).map((sun) => ({
    belowSkyline: sunBlockedByHorizon(horizon, sun),
    dir: sunDirection(sun),
    reachPerMetre: 1 / Math.tan(sun.elevation * DEG),
    weight: Math.sin(sun.elevation * DEG),
  }));
  const totalWeight = samples.reduce((s, x) => s + x.weight, 0);

  const xs = roofXY.map((p) => p[0]);
  const ys = roofXY.map((p) => p[1]);
  const [minX, maxX, minY, maxY] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];

  const cells: ShadingCell[] = [];
  const half = cellSizeM / 2;
  for (let x = minX + half; x < maxX; x += cellSizeM) {
    for (let y = minY + half; y < maxY; y += cellSizeM) {
      const p: XY = [x, y];
      if (!pointInPolygon(p, roofXY)) continue;

      let lit = 0;
      for (const s of samples) {
        if (s.belowSkyline) continue;
        const shaded = prisms.some((prism) => {
          const reach = prism.height * s.reachPerMetre;
          return segmentHitsPolygon(p, [x + s.dir[0] * reach, y + s.dir[1] * reach], prism.footprint);
        });
        if (!shaded) lit += s.weight;
      }

      const corners: XY[] = [
        [x - half, y - half],
        [x + half, y - half],
        [x + half, y + half],
        [x - half, y + half],
      ];
      cells.push({ polygon: corners.map(frame.toLngLat), access: totalWeight ? lit / totalWeight : 0 });
    }
  }

  return summariseCells(cells, cellSizeM, roofAreaM2);
}

function convexHull(points: XY[]): XY[] {
  const pts = [...points].sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  const cross = (o: XY, a: XY, b: XY) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
  const build = (input: XY[]) => {
    const hull: XY[] = [];
    for (const p of input) {
      while (hull.length >= 2 && cross(hull[hull.length - 2], hull[hull.length - 1], p) <= 0) hull.pop();
      hull.push(p);
    }
    hull.pop();
    return hull;
  };
  return [...build(pts), ...build(pts.reverse())];
}

/**
 * Outline of each obstruction's shadow on the roof plane at one instant, for
 * display. Uses a convex outline, so it is exact for convex footprints.
 */
export function shadowOutlines(
  obstructions: ShadingObstruction[],
  roofHeightM: number,
  sun: SunPosition,
): LngLat[][] {
  if (sun.elevation < MIN_SUN_ELEVATION) return [];
  const dir = sunDirection(sun);
  const outlines: LngLat[][] = [];
  for (const o of obstructions) {
    const height = heightAboveRoof(o, roofHeightM);
    if (height <= 0 || o.footprint.length < 3) continue;
    const frame = localFrame(o.footprint[0]);
    const reach = height / Math.tan(sun.elevation * DEG);
    const base = o.footprint.map(frame.toXY);
    const cast = base.map(([x, y]): XY => [x - dir[0] * reach, y - dir[1] * reach]);
    outlines.push(convexHull([...base, ...cast]).map(frame.toLngLat));
  }
  return outlines;
}
