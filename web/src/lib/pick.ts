import { fetchSite } from "./api";
import type { LngLat } from "./geo/local";
import { decodeSite } from "./site/model";
import { useStore } from "./store";

const MESSAGES: Record<string, string> = {
  ground:
    "That spot is open ground. To plan panels on land, choose “Outline it myself” and mark the plot. For a building, tap on its roof.",
  not_building:
    "We couldn't find a roof at that spot; it looks like trees. Tap directly on your roof, or outline it yourself.",
  too_small: "The surface there is too small for panels. Tap a larger part of the roof.",
};

/** Find the roof under a tapped map point and load the measured model of the property. */
export async function pickRoofAt(point: LngLat): Promise<void> {
  useStore.setState({ pick: { state: "finding", point } });
  try {
    const found = await fetchSite({ point });
    // The user may have tapped elsewhere or started outlining by hand while this was running.
    const now = useStore.getState();
    if (now.pick?.state !== "finding" || now.pick.point !== point) return;

    if (!found.available) {
      useStore.setState({
        pick: {
          state: "failed",
          message: `We can't measure properties automatically here. ${found.reason} Outline yours by hand instead.`,
        },
      });
    } else if (!found.found) {
      useStore.setState({ pick: { state: "failed", message: MESSAGES[found.kind] ?? MESSAGES.not_building } });
    } else {
      const site = await decodeSite(found);
      useStore.setState({
        roof: site.outline,
        site,
        siteStatus: { state: "idle" },
        floors: Math.max(1, site.surface.floors),
        mode: "idle",
        pick: null,
      });
    }
  } catch (err) {
    const message = err instanceof Error ? err.message : "Something went wrong finding the roof.";
    useStore.setState({ pick: { state: "failed", message } });
  }
}
