import { useEffect, useState } from "react";
import { centroid, type LngLat } from "./geo/local";
import { fetchMonthlyIrradiance } from "./irradiance";
import type { ShadingResult } from "./solar/shading";
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

/** The recommended system for the surveyed roof and the household's usage. */
export function useSizing(analysis: ShadingResult): { sizing: Sizing | null; sunlight: Sunlight | null } {
  const roof = useStore((s) => s.roof);
  const monthlyUnits = useStore((s) => s.monthlyUnits);
  const [sunlight, setSunlight] = useState<Sunlight | null>(null);

  useEffect(() => {
    if (!roof) return;
    let current = true;
    irradianceFor(centroid(roof))
      .then((values) => current && setSunlight({ values }))
      .catch((err: Error) => current && setSunlight({ error: err.message }));
    return () => {
      current = false;
    };
  }, [roof]);

  const sizing =
    monthlyUnits && sunlight && "values" in sunlight
      ? sizeSystem({
          monthlyIrradiance: sunlight.values,
          monthlyUsageKwh: monthlyUnits,
          roofCapacityKw: analysis.capacityKw,
          solarAccess: analysis.usableAccess,
        })
      : null;
  return { sizing, sunlight };
}
