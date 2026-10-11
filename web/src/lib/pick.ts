import { findRoofAt } from "./api";
import type { LngLat } from "./geo/local";
import { useStore } from "./store";

const MESSAGES: Record<string, string> = {
  ground:
    "That spot is open ground, not a roof. Tap on the roof itself, or outline the land yourself if that is where the panels would go.",
  not_building:
    "We couldn't find a flat roof at that spot. It may be trees, or a sloped or sheet-metal roof, which can't be outlined automatically yet. Tap another part of your roof, or outline it yourself.",
  too_small: "The level area there is too small for panels. Tap a larger part of the roof.",
};

/** Find and outline the roof under a tapped map point. */
export async function pickRoofAt(point: LngLat): Promise<void> {
  useStore.setState({ pick: { state: "finding", point } });
  try {
    const found = await findRoofAt(point);
    // The user may have tapped elsewhere or started outlining by hand while this was running.
    const now = useStore.getState();
    if (now.pick?.state !== "finding" || now.pick.point !== point) return;

    if (!found.available) {
      useStore.setState({
        pick: { state: "failed", message: `We can't find roofs automatically here. ${found.reason} Outline your roof yourself instead.` },
      });
    } else if (!found.found) {
      useStore.setState({ pick: { state: "failed", message: MESSAGES[found.kind] ?? MESSAGES.not_building } });
    } else {
      useStore.setState({ roof: found.roof, floors: found.floors, mode: "idle", pick: null, autoFound: true });
    }
  } catch (err) {
    const message = err instanceof Error ? err.message : "Something went wrong finding the roof.";
    useStore.setState({ pick: { state: "failed", message } });
  }
}
