import type { LngLat } from "../geo/local";
import { surfaceCentre, type SiteModel } from "./model";
import { GOOD_ACCESS, layoutPanels, PANEL_WATTS, type PanelLayout } from "./panels";
import { analyseShade, shadowGrid, type ShadeReport, type ShadowGrid } from "./shadows";

/** Everything worked out about one property's sun, shade and room for panels. */
export interface Analysis {
  model: SiteModel;
  at: LngLat;
  layout: PanelLayout;
  /** Area of the surface in m². */
  areaM2: number;
  /** Average share of open-sky sun across the surface, 0–1. */
  meanAccess: number;
  /** Area of the surface getting good sun, in m². */
  sunnyAreaM2: number;
  /** Output of every good panel position together, in kW. */
  capacityKw: number;
  /** Heights resampled for shadow casting; null when the site was not measured. */
  grid: ShadowGrid | null;
  /** A year of simulated shadows on the surface; null when the site was not measured. */
  shade: ShadeReport | null;
}

export function analyse(model: SiteModel): Analysis {
  const at = surfaceCentre(model);
  let count = 0;
  let sum = 0;
  let sunny = 0;
  for (let i = 0; i < model.labels.length; i++) {
    const access = model.access[i];
    if (model.labels[i] !== 1 || !Number.isFinite(access)) continue;
    count++;
    sum += access;
    if (access >= GOOD_ACCESS) sunny++;
  }
  const pixelArea = model.pixelM * model.pixelM;
  // A tilted surface is larger than its footprint on the map.
  const stretch = 1 / Math.cos((model.surface.tilt_deg * Math.PI) / 180);
  const layout = layoutPanels(model);
  const grid = shadowGrid(model);
  const tested = grid ? Uint8Array.from(grid.labels, (label) => (label === 1 ? 1 : 0)) : null;

  return {
    model,
    at,
    layout,
    areaM2: count * pixelArea * stretch,
    meanAccess: count ? sum / count : 0,
    sunnyAreaM2: sunny * pixelArea * stretch,
    capacityKw: (layout.good * PANEL_WATTS) / 1000,
    grid,
    shade: grid && tested ? analyseShade(model, grid, tested, at) : null,
  };
}
