import { centroid, type LngLat } from "../geo/local";
import { fetchImageryInfo } from "../imagery";
import { estimateHeightFromShadow } from "../solar/shadowHeight";
import { sunAt } from "../solar/sun";
import type { Obstruction } from "../store";
import { captureRoof } from "./capture";
import { Detection, type DetectRequest } from "./schema";

/** Imaging satellites pass over at about this local solar time. */
const TYPICAL_PASS_SOLAR_HOUR = 10.5;
const PLAUSIBLE_HEIGHT_M: [number, number] = [0.5, 150];

/**
 * Ask the vision model which objects could shade the roof, then turn its pixel
 * answers into map obstructions. Heights come from the shadow geometry where
 * the model found a clean shadow, and from its typical-size guess otherwise.
 */
export async function detectObstructions(roof: LngLat[]): Promise<Obstruction[]> {
  const centre = centroid(roof);
  const [capture, imagery] = await Promise.all([captureRoof(roof), fetchImageryInfo(centre).catch(() => null)]);

  let shadowBearing: number | null = null;
  if (imagery) {
    const passUtc =
      Date.UTC(imagery.year, imagery.month - 1, imagery.day, 0, TYPICAL_PASS_SOLAR_HOUR * 60) -
      (centre[0] / 15) * 3_600_000;
    shadowBearing = (sunAt(new Date(passUtc), centre).azimuth + 180) % 360;
  }

  const payload: DetectRequest = {
    image: capture.image,
    size: capture.size,
    metresPerPixel: capture.metresPerPixel,
    shadowBearing,
  };
  const res = await fetch("/api/detect", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const body: unknown = await res.json().catch(() => null);
  if (!res.ok) {
    const message = (body as { error?: string } | null)?.error;
    throw new Error(message ?? "Detection failed.");
  }

  return Detection.parse(body).obstructions.flatMap((found): Obstruction[] => {
    if (found.outline.length < 3) return [];
    const obstruction: Obstruction = {
      id: crypto.randomUUID(),
      kind: found.kind,
      label: found.label,
      suggested: true,
      footprint: found.outline.map(capture.toLngLat),
      heightM: Math.round(found.typical_height_m * 10) / 10,
      reference: found.on_roof ? "roof" : "ground",
    };

    if (found.shadow && imagery) {
      const base = capture.toLngLat(found.shadow.base);
      const tip = capture.toLngLat(found.shadow.tip);
      try {
        const estimate = estimateHeightFromShadow(base, tip, imagery);
        const plausible = estimate.heightM >= PLAUSIBLE_HEIGHT_M[0] && estimate.heightM <= PLAUSIBLE_HEIGHT_M[1];
        if (plausible && estimate.warnings.length === 0) {
          obstruction.heightM = Math.round(estimate.heightM * 10) / 10;
          obstruction.measurement = { base, tip, imagery, estimate };
        }
      } catch {
        // Keep the typical-size guess.
      }
    }
    return [obstruction];
  });
}
