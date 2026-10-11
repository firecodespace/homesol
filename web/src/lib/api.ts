import type { LngLat } from "./geo/local";
import type { SiteResponse } from "./site/model";

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
  currency: string;
  /** Null when there is no quote and no price data for the country. */
  gross_cost: number | null;
  gross_cost_range: [number, number] | null;
  cost_is_quote: boolean;
  subsidy: number;
  net_cost: number | null;
  bill_before: number;
  bill_after: number;
  first_year_savings: number;
  surplus_units: number;
  surplus_credit: number;
  payback_years: number | null;
  lifetime_savings: number | null;
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
  country_code: string;
  currency: string;
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

export const post = <T>(path: string, payload: unknown, signal?: AbortSignal) =>
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

/** Google's photo of the neighbourhood around a point, or null where Google has none. */
export const fetchAreaPicture = async ([lng, lat]: LngLat, signal?: AbortSignal): Promise<Picture | null> => {
  const res = await post<{ available: boolean; picture?: Picture }>("/picture", { lng, lat }, signal);
  return res.available && res.picture ? res.picture : null;
};

/** The measured model of a property, or why there is none. */
export type SiteResult =
  | { available: false; reason: string }
  | { available: true; found: false; kind: "ground" | "not_building" | "too_small"; height_m: number }
  | ({ available: true; found: true } & SiteResponse);

/** Model the property under a tapped point, or inside a hand-drawn outline. */
export const fetchSite = (request: { point: LngLat } | { outline: LngLat[] }, signal?: AbortSignal) =>
  post<SiteResult>("/site", request, signal);

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

export interface Place {
  /** Two-letter country code, upper case. */
  countryCode: string;
  country: string;
  state: string | null;
  /** Three-letter currency code. */
  currency: string;
  /** The most specific part of the address (building, street, neighbourhood), when the lookup has one. */
  address: string | null;
  /** The rest of the address on one line: town, state and postcode, country. */
  region: string;
}

/** What Photon's reverse lookup says about a point; any of it may be missing. */
export interface PhotonAddress {
  name?: string;
  housenumber?: string;
  street?: string;
  locality?: string;
  district?: string;
  city?: string;
  county?: string;
  state?: string;
  postcode?: string;
  country?: string;
  countrycode?: string;
}

const CURRENCIES: Record<string, string> = {
  IN: "INR", US: "USD", GB: "GBP", AU: "AUD", CA: "CAD", NZ: "NZD", JP: "JPY", CN: "CNY", SG: "SGD", AE: "AED",
  SA: "SAR", ZA: "ZAR", BR: "BRL", MX: "MXN", CH: "CHF", SE: "SEK", NO: "NOK", DK: "DKK", PL: "PLN", TR: "TRY",
  ID: "IDR", MY: "MYR", TH: "THB", PH: "PHP", VN: "VND", KR: "KRW", BD: "BDT", PK: "PKR", LK: "LKR", NP: "NPR",
  KE: "KES", NG: "NGN", EG: "EGP", IL: "ILS", AR: "ARS", CL: "CLP", CO: "COP",
};
const EURO = ["AT", "BE", "CY", "DE", "EE", "ES", "FI", "FR", "GR", "HR", "IE", "IT", "LT", "LU", "LV", "MT", "NL", "PT", "SI", "SK"];

/** A place from a reverse lookup's address, or null when it does not say which country. */
export function placeFrom(p: PhotonAddress | undefined): Place | null {
  if (!p?.countrycode) return null;
  const countryCode = p.countrycode.toUpperCase();
  const country = p.country ?? countryCode;
  const city = p.city ?? p.county;
  const wider = [city, [p.state, p.postcode].filter(Boolean).join(" "), country];
  // Building, street, then neighbourhood, leaving out anything said already or repeated by the region line.
  const street = [p.housenumber, p.street].filter(Boolean).join(" ");
  const name = p.name && !street.includes(p.name) ? p.name : undefined;
  const local = [name, street, p.locality, p.district].filter(
    (part): part is string => Boolean(part) && part !== city && part !== p.state && part !== country,
  );
  return {
    countryCode,
    country,
    state: p.state ?? null,
    currency: CURRENCIES[countryCode] ?? (EURO.includes(countryCode) ? "EUR" : "USD"),
    address: [...new Set(local)].slice(0, 3).join(", ") || null,
    region: [...new Set(wider.filter(Boolean))].join(", "),
  };
}

/** Address, country, state and currency of a point, by reverse geocoding. */
export async function placeAt([lng, lat]: LngLat): Promise<Place | null> {
  try {
    // Five decimals is about a metre, so the address is the property's and not the street's next door.
    const res = await fetch(`https://photon.komoot.io/reverse?lon=${lng.toFixed(5)}&lat=${lat.toFixed(5)}`);
    if (!res.ok) return null;
    const body = (await res.json()) as { features: { properties: PhotonAddress }[] };
    return placeFrom(body.features[0]?.properties);
  } catch {
    return null;
  }
}
