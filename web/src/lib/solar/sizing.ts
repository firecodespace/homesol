const DAYS_IN_MONTH = [31, 28.25, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
/** Share of sunlight on the panels that reaches the meter after heat, dust, wiring and inverter losses. */
export const PERFORMANCE_RATIO = 0.75;
/** Rated output of one typical residential panel today. */
export const PANEL_KW = 0.55;

export interface SizingInput {
  /** Average daily sunlight on a flat surface per month, kWh/m²/day, Jan–Dec. */
  monthlyIrradiance: number[];
  /** Units (kWh) on a typical monthly electricity bill. */
  monthlyUsageKwh: number;
  /** Largest system the unshaded part of the roof can hold. */
  roofCapacityKw: number;
  /** Share of yearly direct sun reaching the panel area, 0–1. */
  solarAccess: number;
}

export interface Sizing {
  panels: number;
  systemKw: number;
  /** Expected generation per month, kWh, Jan–Dec. */
  monthlyKwh: number[];
  annualKwh: number;
  /** Share of yearly usage the system generates, capped at 1. */
  coverage: number;
  /** What stopped the system from being larger. */
  limitedBy: "usage" | "roof";
}

/** Units one kW of panels generates in each month. 1 kW under 1 kWh/m²/day yields 1 kWh/day before losses. */
function monthlyYieldPerKw(irradiance: number[], solarAccess: number): number[] {
  return irradiance.map((sun, i) => sun * DAYS_IN_MONTH[i] * PERFORMANCE_RATIO * solarAccess);
}

/** Smallest whole-panel system that covers the year's usage, or the most the roof holds. */
export function sizeSystem({ monthlyIrradiance, monthlyUsageKwh, roofCapacityKw, solarAccess }: SizingInput): Sizing {
  const perKw = monthlyYieldPerKw(monthlyIrradiance, solarAccess);
  const annualPerKw = perKw.reduce((a, b) => a + b, 0);
  const annualUsage = monthlyUsageKwh * 12;

  const panelsWanted = annualPerKw > 0 ? Math.ceil(annualUsage / annualPerKw / PANEL_KW) : 0;
  const panelsThatFit = Math.floor(roofCapacityKw / PANEL_KW);
  const panels = Math.min(panelsWanted, panelsThatFit);
  const systemKw = panels * PANEL_KW;

  const monthlyKwh = perKw.map((kwh) => kwh * systemKw);
  const annualKwh = monthlyKwh.reduce((a, b) => a + b, 0);
  return {
    panels,
    systemKw,
    monthlyKwh,
    annualKwh,
    coverage: annualUsage > 0 ? Math.min(1, annualKwh / annualUsage) : 0,
    limitedBy: panelsWanted > panelsThatFit ? "roof" : "usage",
  };
}
