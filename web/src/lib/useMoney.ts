import { useEffect, useState } from "react";
import { fetchFinance, fetchPolicy, placeAt, type Finance, type Place, type PolicyOverview } from "./api";
import { centroid } from "./geo/local";
import type { Analysis } from "./site/analysis";
import type { Sizing } from "./solar/sizing";
import { useStore } from "./store";
import { useSizing } from "./useSizing";

export const OTHER_DISCOM = "other";

export interface Money {
  sizing: Sizing | null;
  policy: PolicyOverview | null;
  /** Costs and savings for the recommended system, once everything needed is known. */
  finance: Finance | null;
  error: string | null;
  /** The chosen distributor when homesol has tariff data for it. */
  discom: string | null;
  place: Place | null;
  /** Currency every amount is in. */
  currency: string;
  /** Whether homesol has subsidy, tariff and price data for this country. */
  hasPolicyData: boolean;
}

/** The household's recommended system and what it costs and saves. */
export function useMoney(analysis: Analysis | null): Money {
  const { roof, place, monthlyUnits, monthlyBill, quotedCost, discomId, sanctionedLoadKw, setMoney } = useStore();
  const { sizing } = useSizing(analysis);
  const [policy, setPolicy] = useState<PolicyOverview | null>(null);
  const [result, setResult] = useState<{ finance: Finance } | { error: string } | null>(null);

  // Find the property's country, and in India match its state to a distributor unless the user chose one.
  useEffect(() => {
    if (!roof) return;
    let current = true;
    placeAt(centroid(roof))
      .then(async (found) => {
        if (!current) return;
        useStore.setState({ place: found });
        if (found && found.countryCode !== "IN") return setPolicy(null);
        const overview = await fetchPolicy(found?.state ?? null);
        if (!current) return;
        setPolicy(overview);
        if (useStore.getState().discomId === null) setMoney({ discomId: overview.matched ?? OTHER_DISCOM });
      })
      .catch((err: Error) => current && setResult({ error: err.message }));
    return () => {
      current = false;
    };
  }, [roof, setMoney]);

  const india = !place || place.countryCode === "IN";
  const currency = place?.currency ?? "INR";
  const discom = india && discomId && discomId !== OTHER_DISCOM ? discomId : null;
  const ready = Boolean(sizing && sizing.panels > 0 && monthlyUnits && (discom || monthlyBill));

  useEffect(() => {
    if (!ready || !sizing || !monthlyUnits) return;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      fetchFinance(
        {
          system_kw: sizing.systemKw,
          monthly_generation: sizing.monthlyKwh,
          monthly_usage: monthlyUnits,
          discom_id: discom,
          monthly_bill: monthlyBill,
          quoted_cost: quotedCost,
          sanctioned_load_kw: sanctionedLoadKw,
          country_code: place?.countryCode ?? "IN",
          currency,
        },
        controller.signal,
      )
        .then((finance) => setResult({ finance }))
        .catch((err: Error) => {
          if (err.name !== "AbortError") setResult({ error: err.message });
        });
    }, 300);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [ready, sizing, monthlyUnits, discom, monthlyBill, quotedCost, sanctionedLoadKw, place, currency]);

  return {
    sizing,
    policy,
    finance: ready && result && "finance" in result ? result.finance : null,
    error: result && "error" in result ? result.error : null,
    discom,
    place,
    currency,
    hasPolicyData: india,
  };
}
