import { askAdvisor } from "./api";
import type { ShadingResult } from "./solar/shading";
import type { Sizing } from "./solar/sizing";
import { FLOOR_HEIGHT_M, useStore } from "./store";

/** What the dashboard shows, so the advisor answers about this household's property. */
function surveyFor(analysis: ShadingResult, sizing: Sizing | null) {
  const s = useStore.getState();
  return {
    roof: {
      area_m2: Math.round(analysis.roofAreaM2),
      usable_area_m2: Math.round(analysis.usableAreaM2),
      yearly_sun_reaching_roof: Number(analysis.meanAccess.toFixed(2)),
      max_system_kw: Number(analysis.capacityKw.toFixed(1)),
      height_m: s.floors * FLOOR_HEIGHT_M,
      skyline_scanned: s.horizon !== null,
    },
    obstructions: s.obstructions.map((o) => ({
      kind: o.kind,
      height_m: o.heightM,
      height_from: o.reference,
      height_source: o.measurement ? "satellite shadow" : o.suggested ? "automatic guess" : "entered by user",
    })),
    household: {
      monthly_units: s.monthlyUnits,
      monthly_bill_rupees: s.monthlyBill,
      discom_id: s.discomId,
      vendor_quote_rupees: s.quotedCost,
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
export async function ask(question: string, analysis: ShadingResult, sizing: Sizing | null): Promise<void> {
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
