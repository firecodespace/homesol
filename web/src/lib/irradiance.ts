import type { LngLat } from "./geo/local";

const MONTH_KEYS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];

/**
 * Long-term average sunlight on a flat surface for each month, kWh/m²/day,
 * from NASA POWER's satellite climatology. Includes cloud and monsoon effects.
 */
export async function fetchMonthlyIrradiance([lng, lat]: LngLat, signal?: AbortSignal): Promise<number[]> {
  const params = new URLSearchParams({
    parameters: "ALLSKY_SFC_SW_DWN",
    community: "RE",
    longitude: lng.toFixed(3),
    latitude: lat.toFixed(3),
    format: "JSON",
  });
  const res = await fetch(`https://power.larc.nasa.gov/api/temporal/climatology/point?${params}`, { signal });
  if (!res.ok) throw new Error("Sunlight data is unavailable right now.");
  const body = (await res.json()) as { properties: { parameter: { ALLSKY_SFC_SW_DWN: Record<string, number> } } };
  const values = MONTH_KEYS.map((k) => body.properties.parameter.ALLSKY_SFC_SW_DWN[k]);
  if (values.some((v) => !(v > 0))) throw new Error("No sunlight data for this location.");
  return values;
}
