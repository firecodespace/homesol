import { angleDiffDeg, bearingDeg, distance, localFrame, type LngLat } from "../geo/local";
import { solarTimeHours, sunAt } from "./sun";

const DEG = Math.PI / 180;
const MIN_ELEVATION = 10;
/** Imaging satellites are sun-synchronous and pass over mid-morning local solar time. */
const TYPICAL_PASS_WINDOW: [number, number] = [9, 13.5];
const MAX_AZIMUTH_ERROR = 4;

export interface ShadowHeightEstimate {
  heightM: number;
  shadowLengthM: number;
  /** Bearing the shadow points in, degrees clockwise from north. */
  shadowBearing: number;
  sunElevation: number;
  sunAzimuth: number;
  /** Instant the image was most likely captured, solved from the shadow direction. */
  capturedAt: Date;
  /** How far the drawn shadow is from the closest direction the sun allowed that day. */
  azimuthErrorDeg: number;
  /** Height range if each click is off by `clickErrorM`. */
  range: [number, number];
  warnings: string[];
}

/**
 * Estimate an object's height from its shadow in a satellite image.
 *
 * Only the capture *date* is known, so the capture time is recovered from the
 * shadow itself: a shadow points directly away from the sun, and on a given day
 * each sun azimuth occurs at exactly one moment. That moment fixes the sun's
 * elevation, and height = shadow length × tan(elevation).
 *
 * `base` is the ground point directly below the corner casting the shadow and
 * `tip` is where that corner's shadow ends. Both must be on the same level.
 */
export function estimateHeightFromShadow(
  base: LngLat,
  tip: LngLat,
  captureDate: { year: number; month: number; day: number },
  clickErrorM = 0.75,
): ShadowHeightEstimate {
  const frame = localFrame(base);
  const tipXY = frame.toXY(tip);
  const shadowLengthM = distance([0, 0], tipXY);
  const shadowBearing = bearingDeg([0, 0], tipXY);
  const wantedSunAzimuth = (shadowBearing + 180) % 360;

  // Scan the daylight hours of that date, centred on local solar noon.
  const solarNoonUtc =
    Date.UTC(captureDate.year, captureDate.month - 1, captureDate.day, 12) - (base[0] / 15) * 3_600_000;
  let best: { date: Date; azimuth: number; elevation: number; error: number } | null = null;
  for (let minute = -8 * 60; minute <= 8 * 60; minute++) {
    const date = new Date(solarNoonUtc + minute * 60_000);
    const sun = sunAt(date, base);
    if (sun.elevation < MIN_ELEVATION) continue;
    const error = angleDiffDeg(sun.azimuth, wantedSunAzimuth);
    if (!best || error < best.error) best = { date, ...sun, error };
  }
  if (!best) throw new Error("The sun never rises high enough on that date at this location.");

  const tanEl = Math.tan(best.elevation * DEG);
  const heightM = shadowLengthM * tanEl;
  // Two independent click errors combine on the measured length.
  const lengthError = clickErrorM * Math.SQRT2;
  const range: [number, number] = [
    Math.max(0, (shadowLengthM - lengthError) * tanEl),
    (shadowLengthM + lengthError) * tanEl,
  ];

  const warnings: string[] = [];
  if (best.error > MAX_AZIMUTH_ERROR) {
    warnings.push(
      `The sun was never opposite this shadow direction on that date (off by ${best.error.toFixed(0)}°). ` +
        "Re-check that you clicked the base first, then the shadow tip.",
    );
  }
  const solarTime = solarTimeHours(best.date, base[0]);
  if (solarTime < TYPICAL_PASS_WINDOW[0] || solarTime > TYPICAL_PASS_WINDOW[1]) {
    warnings.push(
      "This shadow direction implies an unusual capture time for a satellite pass, " +
        "so the image date may be wrong for this spot. Treat the height as rough.",
    );
  }
  if (shadowLengthM < 3) {
    warnings.push("The shadow is very short, so small click errors change the height a lot.");
  }

  return {
    heightM,
    shadowLengthM,
    shadowBearing,
    sunElevation: best.elevation,
    sunAzimuth: best.azimuth,
    capturedAt: best.date,
    azimuthErrorDeg: best.error,
    range,
    warnings,
  };
}
