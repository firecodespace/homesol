export type LngLat = [number, number];
export type XY = [number, number];

const EARTH_RADIUS_M = 6_371_008.8;
const DEG = Math.PI / 180;

/**
 * Flat east/north metre frame centred on `origin`. Accurate to centimetres over
 * the few hundred metres a rooftop survey spans.
 */
export interface LocalFrame {
  origin: LngLat;
  toXY(p: LngLat): XY;
  toLngLat(p: XY): LngLat;
}

export function localFrame(origin: LngLat): LocalFrame {
  const mPerDegLat = EARTH_RADIUS_M * DEG;
  const mPerDegLng = mPerDegLat * Math.cos(origin[1] * DEG);
  return {
    origin,
    toXY: ([lng, lat]) => [(lng - origin[0]) * mPerDegLng, (lat - origin[1]) * mPerDegLat],
    toLngLat: ([x, y]) => [origin[0] + x / mPerDegLng, origin[1] + y / mPerDegLat],
  };
}

export function centroid(points: LngLat[]): LngLat {
  const n = points.length;
  return [points.reduce((s, p) => s + p[0], 0) / n, points.reduce((s, p) => s + p[1], 0) / n];
}

/** Compass bearing (0 = north, 90 = east) of the vector `from → to`, in degrees. */
export function bearingDeg(from: XY, to: XY): number {
  const deg = Math.atan2(to[0] - from[0], to[1] - from[1]) / DEG;
  return (deg + 360) % 360;
}

export function distance(a: XY, b: XY): number {
  return Math.hypot(b[0] - a[0], b[1] - a[1]);
}

/** Smallest absolute difference between two compass bearings, in degrees. */
export function angleDiffDeg(a: number, b: number): number {
  const d = Math.abs(a - b) % 360;
  return d > 180 ? 360 - d : d;
}

export function polygonArea(poly: XY[]): number {
  let sum = 0;
  for (let i = 0; i < poly.length; i++) {
    const [x1, y1] = poly[i];
    const [x2, y2] = poly[(i + 1) % poly.length];
    sum += x1 * y2 - x2 * y1;
  }
  return Math.abs(sum) / 2;
}

export function pointInPolygon(p: XY, poly: XY[]): boolean {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i];
    const [xj, yj] = poly[j];
    if (yi > p[1] !== yj > p[1] && p[0] < ((xj - xi) * (p[1] - yi)) / (yj - yi) + xi) {
      inside = !inside;
    }
  }
  return inside;
}

function segmentsIntersect(a: XY, b: XY, c: XY, d: XY): boolean {
  const cross = (o: XY, p: XY, q: XY) => (p[0] - o[0]) * (q[1] - o[1]) - (p[1] - o[1]) * (q[0] - o[0]);
  const d1 = cross(c, d, a);
  const d2 = cross(c, d, b);
  const d3 = cross(a, b, c);
  const d4 = cross(a, b, d);
  return d1 * d2 < 0 && d3 * d4 < 0;
}

/** True if segment `a → b` touches the polygon's interior or boundary. */
export function segmentHitsPolygon(a: XY, b: XY, poly: XY[]): boolean {
  if (pointInPolygon(a, poly) || pointInPolygon(b, poly)) return true;
  for (let i = 0; i < poly.length; i++) {
    if (segmentsIntersect(a, b, poly[i], poly[(i + 1) % poly.length])) return true;
  }
  return false;
}
