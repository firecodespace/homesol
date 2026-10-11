import type { LngLat } from "./geo/local";

export const SATELLITE_TILES =
  "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}";
export const SATELLITE_ATTRIBUTION = "Imagery © Esri, Vantor, Earthstar Geographics";

const IDENTIFY_URL = "https://services.arcgisonline.com/arcgis/rest/services/World_Imagery/MapServer/identify";

export interface ImageryInfo {
  year: number;
  month: number;
  day: number;
  source: string;
  resolutionM: number | null;
}

interface IdentifyResult {
  attributes: Record<string, string>;
}

/** Capture date of the highest-resolution satellite image covering a point. */
export async function fetchImageryInfo([lng, lat]: LngLat, signal?: AbortSignal): Promise<ImageryInfo | null> {
  const pad = 0.0005;
  const params = new URLSearchParams({
    geometry: `${lng},${lat}`,
    geometryType: "esriGeometryPoint",
    sr: "4326",
    layers: "all",
    tolerance: "1",
    mapExtent: [lng - pad, lat - pad, lng + pad, lat + pad].join(","),
    imageDisplay: "400,400,96",
    returnGeometry: "false",
    f: "json",
  });
  const res = await fetch(`${IDENTIFY_URL}?${params}`, { signal });
  if (!res.ok) return null;
  const body = (await res.json()) as { results?: IdentifyResult[] };

  let best: ImageryInfo | null = null;
  for (const { attributes: a } of body.results ?? []) {
    const raw = a["DATE (YYYYMMDD)"] ?? a.SRC_DATE;
    if (!raw || !/^\d{8}$/.test(raw)) continue;
    const resolution = Number(a["RESOLUTION (M)"] ?? a.SRC_RES);
    const info: ImageryInfo = {
      year: Number(raw.slice(0, 4)),
      month: Number(raw.slice(4, 6)),
      day: Number(raw.slice(6, 8)),
      source: a.SOURCE ?? a.NICE_NAME ?? "Satellite",
      resolutionM: Number.isFinite(resolution) ? resolution : null,
    };
    if (!best || (info.resolutionM ?? Infinity) < (best.resolutionM ?? Infinity)) best = info;
  }
  return best;
}

export interface Place {
  label: string;
  center: LngLat;
}

/** Address search, anywhere in the world. */
export async function searchPlaces(query: string, signal?: AbortSignal): Promise<Place[]> {
  const params = new URLSearchParams({ q: query, limit: "6", lang: "en" });
  const res = await fetch(`https://photon.komoot.io/api/?${params}`, { signal });
  if (!res.ok) return [];
  const body = (await res.json()) as {
    features: { geometry: { coordinates: LngLat }; properties: Record<string, string | undefined> }[];
  };
  return body.features.map((f) => {
    const p = f.properties;
    const parts = [p.name, p.street, p.district, p.city, p.state, p.country].filter(Boolean);
    return { label: [...new Set(parts)].join(", "), center: f.geometry.coordinates };
  });
}
