import { DAYS_IN_MONTH, PERFORMANCE_RATIO } from "./sizing";

const DEG = Math.PI / 180;
/** Sunlight above the atmosphere, kW/m². */
const SOLAR_CONSTANT = 1.367;
/** Share of sunlight the ground reflects onto a tilted panel. */
const GROUND_REFLECTANCE = 0.2;
/** The day of the year that best represents each month's sun (Klein's average days). */
const MONTH_DAYS = [17, 47, 75, 105, 135, 162, 198, 228, 258, 288, 318, 344];
/** Google's own factor for turning its yearly sunlight figure (kWh per kW of panel) into units at the meter. */
export const GOOGLE_DC_TO_AC = 0.85;

/** The sun's declination on a day of the year, degrees. */
function declination(day: number): number {
  return 23.45 * Math.sin(((360 * (284 + day)) / 365) * DEG);
}

/** Half the length of the day as an angle, radians. Zero in polar night, π in polar day. */
function sunsetAngle(latDeg: number, declDeg: number): number {
  return Math.acos(Math.min(1, Math.max(-1, -Math.tan(latDeg * DEG) * Math.tan(declDeg * DEG))));
}

/**
 * How much more direct sun a day gives a surface tilted towards the equator
 * than a flat one, for a latitude and solar declination (Klein's ratio).
 * Latitudes south of the equator are mirrored.
 */
export function beamRatio(latDeg: number, tiltDeg: number, declDeg: number): number {
  const lat = Math.abs(latDeg);
  const decl = latDeg >= 0 ? declDeg : -declDeg;
  const flatSunset = sunsetAngle(lat, decl);
  const tiltedSunset = Math.min(flatSunset, sunsetAngle(lat - tiltDeg, decl));
  const flat =
    Math.cos(lat * DEG) * Math.cos(decl * DEG) * Math.sin(flatSunset) + flatSunset * Math.sin(lat * DEG) * Math.sin(decl * DEG);
  if (flat <= 1e-6) return 1;
  const tilted =
    Math.cos((lat - tiltDeg) * DEG) * Math.cos(decl * DEG) * Math.sin(tiltedSunset) +
    tiltedSunset * Math.sin((lat - tiltDeg) * DEG) * Math.sin(decl * DEG);
  return Math.max(0, tilted / flat);
}

/**
 * For each month, sunlight on a tilted panel as a multiple of sunlight on a
 * flat surface.
 *
 * The month's sunlight is split into direct and scattered light from how clear
 * the sky is on average (Erbs' correlation). Direct light gains or loses by the
 * panel's angle to the sun, scattered light is lost in proportion to the sky
 * the panel no longer sees, and a little is reflected up from the ground
 * (Liu and Jordan's model). A panel turned away from the equator by
 * `offEquatorDeg` counts only the part of its tilt that leans towards it.
 */
export function tiltGain(latDeg: number, tiltDeg: number, offEquatorDeg: number, monthlyGhi: number[]): number[] {
  if (tiltDeg <= 0) return monthlyGhi.map(() => 1);
  const towardsEquator = Math.atan(Math.tan(tiltDeg * DEG) * Math.cos(offEquatorDeg * DEG)) / DEG;
  const skySeen = (1 + Math.cos(tiltDeg * DEG)) / 2;
  const groundSeen = (1 - Math.cos(tiltDeg * DEG)) / 2;
  return monthlyGhi.map((ghi, month) => {
    const day = MONTH_DAYS[month];
    const decl = declination(day);
    const sunset = sunsetAngle(latDeg, decl);
    const aboveAtmosphere =
      (24 / Math.PI) *
      SOLAR_CONSTANT *
      (1 + 0.033 * Math.cos(((360 * day) / 365) * DEG)) *
      (Math.cos(latDeg * DEG) * Math.cos(decl * DEG) * Math.sin(sunset) + sunset * Math.sin(latDeg * DEG) * Math.sin(decl * DEG));
    if (!(ghi > 0) || aboveAtmosphere <= 0.05) return 1;
    const clearness = Math.min(0.8, Math.max(0.3, ghi / aboveAtmosphere));
    const scattered =
      sunset <= 81.4 * DEG
        ? 1.391 - 3.56 * clearness + 4.189 * clearness ** 2 - 2.137 * clearness ** 3
        : 1.311 - 3.022 * clearness + 3.427 * clearness ** 2 - 1.821 * clearness ** 3;
    return (1 - scattered) * beamRatio(latDeg, towardsEquator, decl) + scattered * skySeen + GROUND_REFLECTANCE * groundSeen;
  });
}

export interface YieldBasis {
  /** For each month, sunlight on the panels as a multiple of sunlight on a flat surface. */
  gain: number[];
  /** The same over the whole year. */
  annualGain: number;
  /** Units at the meter per unit of sunlight on a 1 kW panel. */
  factor: number;
  /** Whether the factor comes from Google's measured sunlight for this spot. */
  measured: boolean;
}

/**
 * How sunlight becomes units at the meter for one layout.
 *
 * Where the site was measured, each panel position's share of sun is a share of
 * `openSkyKwhPerKw`, Google's measured yearly sunlight for an open spot there,
 * which already allows for the weather and for the way a sloped surface faces.
 * Google's own factor turns that into units at the meter, and the months are
 * shared out by the long-term climate record. Elsewhere, the climate record
 * and a standard performance ratio are used.
 *
 * Panels standing in tilted rows gain over the flat surface they stand on.
 * Panels lying flush on a slope do not: the measurement is already of the slope.
 */
export function yieldBasis(input: {
  lat: number;
  monthlyGhi: number[];
  tiltDeg: number;
  facingDeg: number;
  mounting: "tilted rows" | "flush on the slope";
  openSkyKwhPerKw: number | null;
}): YieldBasis {
  const { lat, monthlyGhi, tiltDeg, facingDeg, mounting, openSkyKwhPerKw } = input;
  const equator = lat >= 0 ? 180 : 0;
  const offEquator = Math.abs(((facingDeg - equator + 540) % 360) - 180);
  const gain = mounting === "tilted rows" ? tiltGain(lat, tiltDeg, offEquator, monthlyGhi) : monthlyGhi.map(() => 1);
  const flatYear = monthlyGhi.reduce((sum, ghi, i) => sum + ghi * DAYS_IN_MONTH[i], 0);
  const tiltedYear = monthlyGhi.reduce((sum, ghi, i) => sum + ghi * DAYS_IN_MONTH[i] * gain[i], 0);
  const annualGain = flatYear > 0 ? tiltedYear / flatYear : 1;

  const fromGoogle = openSkyKwhPerKw && flatYear > 0 ? (openSkyKwhPerKw * GOOGLE_DC_TO_AC) / flatYear : null;
  // A factor far outside what panels can do means the two sources disagree about this place; fall back.
  const measured = fromGoogle !== null && fromGoogle >= 0.5 && fromGoogle <= 1.1;
  return { gain, annualGain, factor: measured ? fromGoogle : PERFORMANCE_RATIO, measured };
}
