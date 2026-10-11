import tzlookup from "tz-lookup";
import type { LngLat } from "./geo/local";

/** The IANA time zone at a point, such as "Asia/Kolkata". */
export function zoneAt([lng, lat]: LngLat): string {
  try {
    return tzlookup(lat, lng);
  } catch {
    return "UTC";
  }
}

function offsetMs(zone: string, at: Date): number {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: zone,
    hourCycle: "h23",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).formatToParts(at);
  const part = (type: string) => Number(parts.find((p) => p.type === type)!.value);
  const wall = Date.UTC(part("year"), part("month") - 1, part("day"), part("hour"), part("minute"), part("second"));
  return wall - Math.floor(at.getTime() / 1000) * 1000;
}

/** The instant of a wall-clock time in a time zone. `month` is 1–12, `minutes` counts from midnight. */
export function zonedDate(zone: string, year: number, month: number, day: number, minutes: number): Date {
  const wall = Date.UTC(year, month - 1, day, 0, minutes);
  // The offset depends on the instant, so look it up at a first guess and again at the result.
  const guess = wall - offsetMs(zone, new Date(wall));
  return new Date(wall - offsetMs(zone, new Date(guess)));
}

/** Clock time of an instant in a zone, as "HH:MM". */
export function clockIn(zone: string, at: Date): string {
  return new Intl.DateTimeFormat("en-GB", { timeZone: zone, hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(at);
}

/** Minutes past midnight of an instant in a zone. */
export function minutesIn(zone: string, at: Date): number {
  const [h, m] = clockIn(zone, at).split(":").map(Number);
  return h * 60 + m;
}

/** When the sun is highest on a date at a longitude, to within a quarter of an hour. `month` is 1–12. */
export function solarNoon(year: number, month: number, day: number, lng: number): Date {
  return new Date(Date.UTC(year, month - 1, day, 12) - (lng / 15) * 3_600_000);
}
