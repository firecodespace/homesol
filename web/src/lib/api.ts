import type { LngLat } from "./geo/local";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface PolicyEntry {
  summary: string;
  /** One rate, or rates by system size where the regulator sets them that way. */
  surplus_rate: number | { up_to_kw: number | null; rate: number }[] | null;
  source: string;
  verified: boolean;
}

export interface PolicyOverview {
  as_of: string;
  /** Distributor matched to the requested state, if supported. */
  matched: string | null;
  central_subsidy: { scheme: string; max_total: number; apply_at: string; source: string };
  discoms: Record<string, { name: string; state: string; net_metering: PolicyEntry }>;
}

export interface Finance {
  gross_cost: number;
  gross_cost_range: [number, number];
  cost_is_quote: boolean;
  subsidy: number;
  net_cost: number;
  bill_before: number;
  bill_after: number;
  first_year_savings: number;
  surplus_units: number;
  surplus_credit: number;
  payback_years: number | null;
  lifetime_savings: number;
  rate_basis: "your_bill" | "discom_slabs";
  notes: string[];
}

export interface FinanceInput {
  system_kw: number;
  monthly_generation: number[];
  monthly_usage: number;
  discom_id: string | null;
  monthly_bill: number | null;
  quoted_cost: number | null;
  sanctioned_load_kw: number | null;
}

export interface ChatTurn {
  role: "user" | "assistant";
  text: string;
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, init);
  } catch {
    throw new Error("Can't reach the homesol server. Check that it is running.");
  }
  const body: unknown = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = (body as { detail?: unknown } | null)?.detail;
    throw new Error(typeof detail === "string" ? detail : "The homesol server returned an error.");
  }
  return body as T;
}

const post = <T>(path: string, payload: unknown, signal?: AbortSignal) =>
  call<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal,
  });

export const fetchPolicy = (state: string | null) =>
  call<PolicyOverview>(`/policy${state ? `?state=${encodeURIComponent(state)}` : ""}`);

export const fetchFinance = (input: FinanceInput, signal?: AbortSignal) => post<Finance>("/finance", input, signal);

export const askAdvisor = (question: string, survey: unknown, history: ChatTurn[]) =>
  post<{ answer: string }>("/advise", { question, survey, history });

export const requestDetection = (payload: {
  image: string;
  size: number;
  metres_per_pixel: number;
  shadow_bearing: number | null;
}) => post<unknown>("/detect", payload);

/** Google's photo of the area with the map position of its corners (TL, TR, BR, BL). */
export interface Picture {
  image: string;
  corners: [LngLat, LngLat, LngLat, LngLat];
}

export type MeasuredSun =
  | { available: false; reason: string }
  | {
      available: true;
      cells: { polygon: LngLat[]; access: number }[];
      cell_size_m: number;
      /** Area of the surface panels would sit on, leaving out structures above it and ground below. */
      surface_area_m2: number;
      /** What the outlined area is, from its height above nearby ground. */
      surface: "roof" | "ground" | null;
      structures_m2: number;
      roof_height_m: number | null;
      floors?: number;
      imagery_date: string | null;
      imagery_quality: string | null;
      picture: Picture | null;
    };

/** Google's measured sun map for a roof, where Google has surveyed it. */
export const fetchMeasuredSun = (roof: LngLat[], signal?: AbortSignal) =>
  post<MeasuredSun>("/measured-sun", { roof }, signal);

export type RoofAt =
  | { available: false; reason: string }
  | { available: true; found: false; kind: "ground" | "not_building" | "too_small"; height_m: number }
  | {
      available: true;
      found: true;
      roof: LngLat[];
      area_m2: number;
      height_m: number;
      floors: number;
      cut_off: boolean;
    };

/** Google's photo of the neighbourhood around a point, or null where Google has none. */
export const fetchAreaPicture = async ([lng, lat]: LngLat, signal?: AbortSignal): Promise<Picture | null> => {
  const res = await post<{ available: boolean; picture?: Picture }>("/picture", { lng, lat }, signal);
  return res.available && res.picture ? res.picture : null;
};

/** The roof under a tapped point, outlined from Google's height data. */
export const findRoofAt = ([lng, lat]: LngLat) => post<RoofAt>("/roof-at", { lng, lat });

export const sendVerdict = (verdict: {
  detection_id: string;
  verdict: "confirmed" | "rejected" | "missed";
  model_index: number | null;
  kind: string;
  footprint: LngLat[];
  height_m: number | null;
  height_from: "ground" | "roof";
  roof: LngLat[];
}) => post<{ ok: boolean }>("/feedback", verdict);

export interface BillReading {
  units_per_month: number | null;
  bill_per_month: number | null;
  discom_id: string | null;
  distributor: string | null;
  sanctioned_load_kw: number | null;
  basis: string | null;
}

export const readBill = (image: string) => post<BillReading>("/bill", { image, format: "jpeg" });

export type SpeechLanguage = "en-IN" | "hi-IN";

export const transcribe = (audio: string, language: SpeechLanguage) =>
  post<{ text: string; language: string | null }>("/transcribe", { audio, language });

export const saveSurvey = (survey: unknown) => post<{ code: string }>("/surveys", { survey });

export const loadSurvey = (code: string) =>
  call<{ survey: Record<string, unknown> }>(`/surveys/${encodeURIComponent(code)}`);

/** The Indian state a point falls in, by reverse geocoding. */
export async function stateAt([lng, lat]: LngLat): Promise<string | null> {
  try {
    const res = await fetch(`https://photon.komoot.io/reverse?lon=${lng.toFixed(4)}&lat=${lat.toFixed(4)}`);
    if (!res.ok) return null;
    const body = (await res.json()) as { features: { properties: { state?: string } }[] };
    return body.features[0]?.properties.state ?? null;
  } catch {
    return null;
  }
}
