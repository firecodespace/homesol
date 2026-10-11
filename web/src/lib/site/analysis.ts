import { pointInPolygon, type LngLat } from "../geo/local";
import { lngLatToGrid, surfaceCentre, type SiteModel } from "./model";
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
  /** The same, over just the places panels would go. */
  panelShade: ShadeReport | null;
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

  // Mark the grid pixels under the good panel positions.
  let underPanels: Uint8Array | null = null;
  if (grid && layout.good) {
    underPanels = new Uint8Array(grid.rows * grid.cols);
    for (const panel of layout.panels.slice(0, layout.good)) {
      const corners = panel.corners.map((p) => lngLatToGrid(model, p).map((v) => v / grid.scale) as [number, number]);
      const cols = corners.map((c) => c[0]);
      const rows = corners.map((c) => c[1]);
      for (let r = Math.floor(Math.min(...rows)); r <= Math.ceil(Math.max(...rows)); r++) {
        for (let c = Math.floor(Math.min(...cols)); c <= Math.ceil(Math.max(...cols)); c++) {
          if (r < 0 || c < 0 || r >= grid.rows || c >= grid.cols) continue;
          if (pointInPolygon([c + 0.5, r + 0.5], corners)) underPanels[r * grid.cols + c] = 1;
        }
      }
    }
  }

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
    panelShade: grid && underPanels ? analyseShade(model, grid, underPanels, at) : null,
  };
}
