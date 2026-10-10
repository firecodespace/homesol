import type { LngLat } from "./geo/local";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface PolicyEntry {
  summary: string;
  surplus_rate: number | null;
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
