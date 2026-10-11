import type { LngLat } from "../geo/local";
import { sunAt } from "../solar/sun";
import { solarNoon } from "../time";
import type { SiteModel } from "./model";

const DEG = Math.PI / 180;
/** Below this the sun is too low to count: its light is weak and every shadow is very long. */
export const MIN_SUN_ELEVATION = 5;
/** A blocker must stand this far above the ray to count, so measurement noise casts no shadows. */
const CLEARANCE_M = 0.15;

/** Heights on a grid coarse enough to simulate shadows on at interactive speed. */
export interface ShadowGrid {
  rows: number;
  cols: number;
  pixelM: number;
  /** How many model pixels one grid pixel spans, each way. */
  scale: number;
  heights: Float32Array;
  labels: Uint8Array;
  maxHeight: number;
}

/** Resample a site model for shadow casting, keeping the tallest point in each block. */
export function shadowGrid(model: SiteModel, targetPixelM = 0.5): ShadowGrid | null {
  if (!model.heights) return null;
  const scale = Math.max(1, Math.round(targetPixelM / model.pixelM));
  const rows = Math.floor(model.rows / scale);
  const cols = Math.floor(model.cols / scale);
  const heights = new Float32Array(rows * cols);
  const labels = new Uint8Array(rows * cols);
  let maxHeight = 0;
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      let top = -Infinity;
      let label = 0;
      let onSurface = false;
      for (let dr = 0; dr < scale; dr++) {
        for (let dc = 0; dc < scale; dc++) {
          const i = (r * scale + dr) * model.cols + c * scale + dc;
          const h = model.heights[i];
          if (h > top) {
            top = h;
            label = model.labels[i];
          }
          if (model.labels[i] === 1) onSurface = true;
        }
      }
      heights[r * cols + c] = Number.isFinite(top) ? top : -Infinity;
      // The block takes the label of its tallest point; an unlabelled block touching the surface is surface.
      labels[r * cols + c] = label === 0 && onSurface ? 1 : label;
      if (top > maxHeight) maxHeight = top;
    }
  }
  return { rows, cols, pixelM: model.pixelM * scale, scale, heights, labels, maxHeight };
}

/**
 * Which pixels are in shadow for one sun position.
 *
 * From each pixel a ray climbs towards the sun; the pixel is shaded when the
 * ray passes under the top of something on the way. `azimuthDeg` is relative
 * to the grid's own up direction.
 *
 * `out[i]` becomes 1 where shaded. With `only`, just those pixels are tested.
 * With `blockers`, the grid index of what cast each shadow is recorded.
 */
export function castShadows(
  grid: ShadowGrid,
  azimuthDeg: number,
  elevationDeg: number,
  out: Uint8Array,
  only?: Uint8Array,
  blockers?: Int32Array,
): void {
  const { rows, cols, heights, maxHeight } = grid;
  out.fill(0);
  if (elevationDeg < MIN_SUN_ELEVATION) {
    if (!only) out.fill(1);
    return;
  }
  const dx = Math.sin(azimuthDeg * DEG);
  const dy = -Math.cos(azimuthDeg * DEG);
  const rise = grid.pixelM * Math.tan(elevationDeg * DEG);

  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      const i = r * cols + c;
      if (only && !only[i]) continue;
      let ray = heights[i] + CLEARANCE_M;
      if (!(ray > -Infinity)) continue;
      let x = c + 0.5;
      let y = r + 0.5;
      for (;;) {
        x += dx;
        y += dy;
        ray += rise;
        if (ray > maxHeight || x < 0 || y < 0 || x >= cols || y >= rows) break;
        const j = (y | 0) * cols + (x | 0);
        if (heights[j] > ray) {
          out[i] = 1;
          if (blockers) blockers[i] = j;
          break;
        }
      }
    }
  }
}

export interface SunSample {
  date: Date;
  month: number;
  /** Relative to true north. */
  azimuth: number;
  elevation: number;
  /** Strength of direct sun on a flat surface at this moment, 0–1. */
  weight: number;
}

/** Sun positions every half hour of daylight on the 21st of each month. */
export function yearOfSun(at: LngLat): SunSample[] {
  const samples: SunSample[] = [];
  for (let month = 1; month <= 12; month++) {
    const noon = solarNoon(2026, month, 21, at[0]).getTime();
    for (let k = -18; k <= 18; k++) {
      const date = new Date(noon + k * 30 * 60_000);
      const sun = sunAt(date, at);
      if (sun.elevation < MIN_SUN_ELEVATION) continue;
      samples.push({ date, month, ...sun, weight: Math.sin(sun.elevation * DEG) });
    }
  }
  return samples;
}

export interface ShadeReport {
  /** Share of the year's direct sun the tested area loses to shadows, 0–1. */
  lost: number;
  /** Share of that loss caused by each label: 1 is the surface's own shape, 0 is anything unlabelled. */
  blame: Map<number, number>;
  /** For each month 1–12, the stretch of the day when at least 90% of the tested area is in sun. */
  fullSun: { month: number; from: Date | null; to: Date | null }[];
}

/**
 * A year of shadows over part of the grid: how much sun is lost, what causes
 * the loss, and when in the day the area is clear.
 */
export function analyseShade(model: SiteModel, grid: ShadowGrid, tested: Uint8Array, at: LngLat): ShadeReport {
  const shaded = new Uint8Array(grid.rows * grid.cols);
  const blockers = new Int32Array(grid.rows * grid.cols);
  let count = 0;
  for (let i = 0; i < tested.length; i++) if (tested[i]) count++;

  let possible = 0;
  let lost = 0;
  const blame = new Map<number, number>();
  const fullSun = Array.from({ length: 12 }, (_, i) => ({ month: i + 1, from: null as Date | null, to: null as Date | null }));

  for (const sample of yearOfSun(at)) {
    castShadows(grid, sample.azimuth - model.northDeg, sample.elevation, shaded, tested, blockers);
    let dark = 0;
    for (let i = 0; i < tested.length; i++) {
      if (!tested[i] || !shaded[i]) continue;
      dark++;
      const label = grid.labels[blockers[i]];
      blame.set(label, (blame.get(label) ?? 0) + sample.weight);
    }
    possible += sample.weight * count;
    lost += sample.weight * dark;
    if (count && dark / count <= 0.1) {
      const day = fullSun[sample.month - 1];
      day.from ??= sample.date;
      day.to = sample.date;
    }
  }
  for (const [label, weight] of blame) blame.set(label, lost ? weight / lost : 0);
  return { lost: possible ? lost / possible : 0, blame, fullSun };
}
