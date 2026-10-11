import { useEffect, useMemo, useState } from "react";
import type { LngLat } from "./geo/local";
import { fetchMonthlyIrradiance } from "./irradiance";
import type { Analysis } from "./site/analysis";
import { sizeSystem, type Sizing } from "./solar/sizing";
import { useStore } from "./store";

type Sunlight = { values: number[] } | { error: string };

// One request per location, shared by every component that sizes the system.
const requests = new Map<string, Promise<number[]>>();
function irradianceFor(at: LngLat): Promise<number[]> {
  const key = `${at[0].toFixed(2)},${at[1].toFixed(2)}`;
  let request = requests.get(key);
  if (!request) {
    request = fetchMonthlyIrradiance(at);
    request.catch(() => requests.delete(key));
    requests.set(key, request);
  }
  return request;
}

/** The recommended system for the surveyed property and the household's usage. */
export function useSizing(analysis: Analysis | null): { sizing: Sizing | null; sunlight: Sunlight | null } {
  const monthlyUnits = useStore((s) => s.monthlyUnits);
  const [sunlight, setSunlight] = useState<Sunlight | null>(null);
  const at = analysis?.at ?? null;
  const key = at ? `${at[0].toFixed(2)},${at[1].toFixed(2)}` : null;

  useEffect(() => {
    if (!at) return;
    let current = true;
    irradianceFor(at)
      .then((values) => current && setSunlight({ values }))
      .catch((err: Error) => current && setSunlight({ error: err.message }));
    return () => {
      current = false;
    };
    // The key stands for the location; `at` is a fresh array on every analysis.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const sizing = useMemo(() => {
    if (!analysis || !monthlyUnits || !sunlight || !("values" in sunlight)) return null;
    const { panels, good } = analysis.layout;
    return sizeSystem({
      monthlyIrradiance: sunlight.values,
      monthlyUsageKwh: monthlyUnits,
      panelAccess: panels.slice(0, good).map((p) => p.access),
    });
  }, [analysis, monthlyUnits, sunlight]);
  return { sizing, sunlight };
}
