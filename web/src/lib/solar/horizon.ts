import type { SunPosition } from "./sun";

const DEG = Math.PI / 180;
export const HORIZON_BIN_DEG = 5;
const BINS = 360 / HORIZON_BIN_DEG;

/**
 * Skyline seen from the roof: the elevation angle of whatever blocks the sky,
 * for each 5° of compass bearing. `null` bins were never scanned and count as
 * open sky.
 */
export type HorizonProfile = (number | null)[];

export const emptyHorizon = (): HorizonProfile => Array<number | null>(BINS).fill(null);

/**
 * Where a phone's rear camera points, from its orientation sensor angles
 * (W3C DeviceOrientation: alpha about z, beta about x, gamma about y, with
 * alpha measured against true/magnetic north).
 */
export function cameraDirection(alpha: number, beta: number, gamma: number): SunPosition {
  const [a, b, g] = [alpha * DEG, beta * DEG, gamma * DEG];
  // The camera looks along the device's -z axis; rotate it into east/north/up.
  const east = -(Math.cos(g) * Math.sin(a) * Math.sin(b) + Math.cos(a) * Math.sin(g));
  const north = -(Math.sin(a) * Math.sin(g) - Math.cos(a) * Math.cos(g) * Math.sin(b));
  const up = -Math.cos(b) * Math.cos(g);
  return {
    azimuth: (Math.atan2(east, north) / DEG + 360) % 360,
    elevation: Math.asin(Math.max(-1, Math.min(1, up))) / DEG,
  };
}

const binOf = (azimuth: number) => Math.round((((azimuth % 360) + 360) % 360) / HORIZON_BIN_DEG) % BINS;

/** Record one skyline sample, replacing whatever was traced at that bearing before. */
export function withSample(profile: HorizonProfile, { azimuth, elevation }: SunPosition): HorizonProfile {
  const next = [...profile];
  next[binOf(azimuth)] = Math.max(0, elevation);
  return next;
}

/** Skyline elevation at a bearing, interpolated between neighbouring bins. */
export function horizonElevation(profile: HorizonProfile, azimuth: number): number {
  const position = (((azimuth % 360) + 360) % 360) / HORIZON_BIN_DEG;
  const lower = Math.floor(position) % BINS;
  const upper = (lower + 1) % BINS;
  const t = position - Math.floor(position);
  return (profile[lower] ?? 0) * (1 - t) + (profile[upper] ?? 0) * t;
}

export function sunBlockedByHorizon(profile: HorizonProfile | null, sun: SunPosition): boolean {
  return profile !== null && sun.elevation < horizonElevation(profile, sun.azimuth);
}

/** Share of the compass that has been scanned, 0–1. */
export function horizonCoverage(profile: HorizonProfile): number {
  return profile.filter((v) => v !== null).length / BINS;
}
