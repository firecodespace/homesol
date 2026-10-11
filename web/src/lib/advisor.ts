import { askAdvisor } from "./api";
import type { Analysis } from "./site/analysis";
import { PANEL_WATTS } from "./site/panels";
import type { Sizing } from "./solar/sizing";
import { useStore } from "./store";
import { clockIn, zoneAt } from "./time";

/** The property and household as the dashboard shows them, so the advisor answers about this one. */
export function surveyFor(analysis: Analysis, sizing: Sizing | null) {
  const s = useStore.getState();
  const { model, layout, shade } = analysis;
  const zone = zoneAt(analysis.at);
  const northern = analysis.at[1] >= 0;
  const window = (month: number) => {
    const day = shade?.fullSun[month - 1];
    return day?.from && day.to ? `${clockIn(zone, day.from)} to ${clockIn(zone, day.to)}` : null;
  };

  return {
    location: s.place
      ? { country_code: s.place.countryCode, country: s.place.country, state: s.place.state, currency: s.place.currency }
      : { country_code: "IN", country: "India", state: null, currency: "INR" },
    surface: {
      kind: model.surface.kind,
      area_m2: Math.round(analysis.areaM2),
      height_m: model.surface.height_m,
      floors: model.surface.floors,
      tilt_deg: model.surface.tilt_deg,
      faces: model.surface.faces,
      measured: model.measured,
      imagery_date: model.imageryDate,
    },
    sun: {
      share_of_full_sun: Number(analysis.meanAccess.toFixed(2)),
      full_sun_hours: shade
        ? { winter: window(northern ? 12 : 6), equinox: window(3), summer: window(northern ? 6 : 12) }
        : undefined,
    },
    obstructions: model.measured
      ? model.obstructions
          .map((o) => ({
            name: o.name,
            on_surface: o.on_surface,
            height_above_m: o.height_above_m,
            distance_m: o.distance_m,
            direction: o.direction,
            share_of_shade: Number((shade?.blame.get(o.id) ?? 0).toFixed(2)),
          }))
          .filter((o) => o.on_surface || o.share_of_shade >= 0.02)
          .sort((a, b) => b.share_of_shade - a.share_of_shade)
          .slice(0, 8)
      : s.obstructions.map((o) => ({
          name: o.label ?? o.kind,
          on_surface: o.reference === "roof",
          height_above_m: o.heightM,
          distance_m: null,
          direction: null,
          share_of_shade: null,
        })),
    panels: {
      fit: layout.good,
      recommended: sizing?.panels ?? null,
      panel_watts: PANEL_WATTS,
      tilt_deg: layout.tiltDeg,
      facing: ["north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west"][
        Math.round((((layout.facingDeg % 360) + 360) % 360) / 45) % 8
      ],
      mounting: layout.mounting,
    },
    household: {
      monthly_units: s.monthlyUnits,
      monthly_bill: s.monthlyBill,
      discom_id: s.discomId,
      vendor_quote: s.quotedCost,
    },
    recommended_system: sizing && {
      system_kw: sizing.systemKw,
      panels: sizing.panels,
      monthly_generation_units: sizing.monthlyKwh,
      share_of_usage_covered: Number(sizing.coverage.toFixed(2)),
      limited_by: sizing.limitedBy,
    },
  };
}

/** Send a question to the advisor and add its answer to the conversation. */
export async function ask(question: string, analysis: Analysis, sizing: Sizing | null): Promise<void> {
  const { chat } = useStore.getState();
  if (!question.trim() || chat.waiting) return;
  const history = chat.turns;
  useStore.setState({ chat: { turns: [...history, { role: "user", text: question }], waiting: true, error: null } });
  try {
    const { answer } = await askAdvisor(question, surveyFor(analysis, sizing), history);
    useStore.setState((s) => ({
      chat: { turns: [...s.chat.turns, { role: "assistant", text: answer }], waiting: false, error: null },
    }));
  } catch (err) {
    const error = err instanceof Error ? err.message : "The advisor is unavailable.";
    useStore.setState((s) => ({ chat: { ...s.chat, waiting: false, error } }));
  }
}
