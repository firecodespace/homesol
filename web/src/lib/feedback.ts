import { sendVerdict } from "./api";
import type { LngLat } from "./geo/local";
import type { Obstruction } from "./store";

/**
 * Tell the server whether a detected obstruction was right, wrong, or missed.
 * Verdicts build the dataset detection is measured and later trained on, so a
 * failed send is dropped quietly rather than interrupting the survey.
 */
export function reportVerdict(
  verdict: "confirmed" | "rejected" | "missed",
  detectionId: string,
  obstruction: Obstruction,
  roof: LngLat[],
): void {
  void sendVerdict({
    detection_id: detectionId,
    verdict,
    model_index: obstruction.modelIndex ?? null,
    kind: obstruction.kind,
    footprint: obstruction.footprint,
    height_m: obstruction.heightM,
    height_from: obstruction.reference,
    roof,
  }).catch(() => {});
}
