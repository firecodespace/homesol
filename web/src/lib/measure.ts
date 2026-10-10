import type { LngLat } from "./geo/local";
import { fetchImageryInfo } from "./imagery";
import { estimateHeightFromShadow } from "./solar/shadowHeight";
import { useStore } from "./store";

/** Turn a base → shadow-tip pair into a height for the obstruction being measured. */
export async function completeMeasurement(base: LngLat, tip: LngLat): Promise<void> {
  const { measureTarget: id, updateObstruction } = useStore.getState();
  if (!id) return;
  useStore.setState({ mode: "idle", draft: [], measureStatus: { state: "loading" } });

  try {
    const imagery = await fetchImageryInfo(base);
    if (!imagery) {
      throw new Error("Couldn't find the capture date of this satellite image. Enter the height by hand instead.");
    }
    const estimate = estimateHeightFromShadow(base, tip, imagery);
    updateObstruction(id, {
      heightM: Math.round(estimate.heightM * 10) / 10,
      measurement: { base, tip, imagery, estimate },
    });
    useStore.setState({ measureStatus: null });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Measurement failed.";
    useStore.setState({ measureStatus: { state: "error", message } });
  }
}
