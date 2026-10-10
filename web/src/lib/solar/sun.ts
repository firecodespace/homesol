import { getPosition } from "suncalc";
import type { LngLat } from "../geo/local";

const IST_OFFSET_MS = 5.5 * 3_600_000;

export interface SunPosition {
  /** Compass bearing of the sun, degrees clockwise from north. */
  azimuth: number;
  /** Angle above the horizon, degrees. Negative at night. */
  elevation: number;
}

export function sunAt(date: Date, [lng, lat]: LngLat): SunPosition {
  const { azimuth, altitude } = getPosition(date, lat, lng);
  return { azimuth, elevation: altitude };
}

/** The instant of a wall-clock time in India Standard Time. `month` is 1–12. */
export function istDate(year: number, month: number, day: number, hours = 0, minutes = 0): Date {
  return new Date(Date.UTC(year, month - 1, day, hours, minutes) - IST_OFFSET_MS);
}

/** Local solar time in hours (12 = sun due south/north) for an instant at a longitude. */
export function solarTimeHours(date: Date, lng: number): number {
  const utcHours = date.getUTCHours() + date.getUTCMinutes() / 60;
  return (((utcHours + lng / 15) % 24) + 24) % 24;
}
