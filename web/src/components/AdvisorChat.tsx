"use client";

import { useRef, useState } from "react";
import { askAdvisor, transcribe, type ChatTurn, type SpeechLanguage } from "@/lib/api";
import { startRecording, type Recording } from "@/lib/audio";
import type { ShadingResult } from "@/lib/solar/shading";
import { FLOOR_HEIGHT_M, useStore } from "@/lib/store";
import { useSizing } from "@/lib/useSizing";
import { field, primary, secondary } from "./ui";

const SUGGESTIONS = ["Is solar worth it for my home?", "How do I apply for the subsidy?", "मेरी छत पर पैनल कहाँ लगाने चाहिए?"];

export default function AdvisorChat({ analysis }: { analysis: ShadingResult }) {
  const store = useStore();
  const { sizing } = useSizing(analysis);
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [draft, setDraft] = useState("");
  const [waiting, setWaiting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [language, setLanguage] = useState<SpeechLanguage>("en-IN");
  const [mic, setMic] = useState<"idle" | "recording" | "transcribing">("idle");
  const recording = useRef<Recording | null>(null);

  const toggleMic = async () => {
    setError(null);
    if (mic === "idle") {
      try {
        recording.current = await startRecording();
        setMic("recording");
      } catch {
        setError("Microphone access is needed to speak your question.");
      }
      return;
    }
    if (mic !== "recording" || !recording.current) return;
    setMic("transcribing");
    try {
      const { text } = await transcribe(await recording.current.stop(), language);
      if (text) setDraft((d) => (d ? `${d} ${text}` : text));
      else setError("Couldn't hear any words. Try again a little closer to the microphone.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Speech recognition failed.");
    } finally {
      recording.current = null;
      setMic("idle");
    }
  };

  const ask = async (question: string) => {
    if (!question.trim() || waiting) return;
    // What the dashboard shows, so the advisor answers about this household's roof.
    const survey = {
      roof: {
        area_m2: Math.round(analysis.roofAreaM2),
        usable_area_m2: Math.round(analysis.usableAreaM2),
        yearly_sun_reaching_roof: Number(analysis.meanAccess.toFixed(2)),
        max_system_kw: Number(analysis.capacityKw.toFixed(1)),
        height_m: store.floors * FLOOR_HEIGHT_M,
        skyline_scanned: store.horizon !== null,
      },
      obstructions: store.obstructions.map((o) => ({
        kind: o.kind,
        height_m: o.heightM,
        height_from: o.reference,
        height_source: o.measurement ? "satellite shadow" : o.suggested ? "automatic guess" : "entered by user",
      })),
      household: {
        monthly_units: store.monthlyUnits,
        monthly_bill_rupees: store.monthlyBill,
        discom_id: store.discomId,
        vendor_quote_rupees: store.quotedCost,
      },
      recommended_system: sizing && {
        system_kw: sizing.systemKw,
        panels: sizing.panels,
        monthly_generation_units: sizing.monthlyKwh,
        share_of_usage_covered: Number(sizing.coverage.toFixed(2)),
        limited_by: sizing.limitedBy,
      },
    };

    const history = turns;
    setTurns([...history, { role: "user", text: question }]);
    setDraft("");
    setWaiting(true);
    setError(null);
    try {
      const { answer } = await askAdvisor(question, survey, history);
      setTurns((t) => [...t, { role: "assistant", text: answer }]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "The advisor is unavailable.");
    } finally {
      setWaiting(false);
    }
  };

  return (
    <div className="space-y-3">
      {turns.length === 0 && (
        <div className="flex flex-wrap gap-2">
          {SUGGESTIONS.map((s) => (
            <button
              key={s}
              className="rounded-full border border-slate-700 px-3 py-1 text-xs text-slate-300 hover:bg-slate-800"
              onClick={() => ask(s)}
            >
              {s}
            </button>
          ))}
        </div>
      )}
      {turns.map((turn, i) => (
        <p
          key={i}
          className={`whitespace-pre-wrap rounded-lg px-3 py-2 text-sm ${
            turn.role === "user" ? "ml-8 bg-amber-400/15 text-amber-50" : "mr-4 bg-slate-900 text-slate-200"
          }`}
        >
          {turn.text}
        </p>
      ))}
      {waiting && <p className="text-xs text-slate-400">Checking your survey and the rules…</p>}
      {error && <p className="text-xs text-rose-300">{error}</p>}
      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          void ask(draft);
        }}
      >
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Ask in English or Hindi"
          aria-label="Question for the advisor"
          className={`${field} min-w-0 flex-1 py-2 text-sm`}
        />
        <button className={primary} disabled={waiting || !draft.trim()}>
          Ask
        </button>
      </form>
      <div className="flex items-center gap-2">
        <button
          type="button"
          className={`${secondary} ${mic === "recording" ? "border-rose-400 text-rose-200" : ""}`}
          disabled={mic === "transcribing"}
          onClick={toggleMic}
        >
          {mic === "idle" ? "Speak your question" : mic === "recording" ? "Stop and transcribe" : "Transcribing…"}
        </button>
        <select
          value={language}
          onChange={(e) => setLanguage(e.target.value as SpeechLanguage)}
          aria-label="Spoken language"
          className={`${field} py-2 text-sm`}
        >
          <option value="en-IN">English</option>
          <option value="hi-IN">हिंदी</option>
        </select>
      </div>
    </div>
  );
}
