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
  /**
   * Share of open-sky sun each good panel position gets, best first. The system
   * uses as many of these as it needs, starting with the sunniest.
   */
  panelAccess: number[];
}

export interface Sizing {
  /** How many panels, taken from the front of `panelAccess`. */
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

/** Units one panel in full sun generates in each month. 1 kW under 1 kWh/m²/day yields 1 kWh/day before losses. */
function monthlyYieldPerPanel(irradiance: number[]): number[] {
  return irradiance.map((sun, i) => sun * DAYS_IN_MONTH[i] * PERFORMANCE_RATIO * PANEL_KW);
}

/** The fewest panels, sunniest positions first, that cover the year's usage; or every good position. */
export function sizeSystem({ monthlyIrradiance, monthlyUsageKwh, panelAccess }: SizingInput): Sizing {
  const perPanel = monthlyYieldPerPanel(monthlyIrradiance);
  const annualPerPanel = perPanel.reduce((a, b) => a + b, 0);
  const annualUsage = monthlyUsageKwh * 12;

  let panels = 0;
  let accessUsed = 0;
  while (panels < panelAccess.length && accessUsed * annualPerPanel < annualUsage) {
    accessUsed += panelAccess[panels];
    panels++;
  }

  const monthlyKwh = perPanel.map((kwh) => kwh * accessUsed);
  const annualKwh = annualPerPanel * accessUsed;
  return {
    panels,
    systemKw: panels * PANEL_KW,
    monthlyKwh,
    annualKwh,
    coverage: annualUsage > 0 ? Math.min(1, annualKwh / annualUsage) : 0,
    limitedBy: annualKwh < annualUsage ? "roof" : "usage",
  };
}
