"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import QRCode from "qrcode";
import { ask } from "@/lib/advisor";
import { saveSurvey, transcribe, type MeasuredSun, type SpeechLanguage } from "@/lib/api";
import { startRecording, type Recording } from "@/lib/audio";
import type { ShadingResult } from "@/lib/solar/shading";
import type { SunPosition } from "@/lib/solar/sun";
import { FLOOR_HEIGHT_M, useStore } from "@/lib/store";
import { OTHER_DISCOM, type Money } from "@/lib/useMoney";
import BillUpload from "./BillUpload";
import { FindProperty, ObstructionsStep } from "./PropertyTools";
import { field, fmt, outlined, primary, secondary } from "./ui";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const SUGGESTIONS = ["Is solar worth it for my home?", "How do I apply for the subsidy?", "मेरी छत पर पैनल कहाँ लगाने चाहिए?"];
const clock = (minutes: number) =>
  `${String(Math.floor(minutes / 60)).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}`;

/** One tool: what it is, what it does for you, then its controls. */
function Tool({ title, description, children }: { title: string; description: string; children: ReactNode }) {
  return (
    <section className="border-b border-outline-variant px-4 py-5">
      <h2 className="md-title">{title}</h2>
      <p className="md-body mb-4 mt-1">{description}</p>
      {children}
    </section>
  );
}

function NumberRow(props: {
  label: string;
  hint?: string;
  unit: string;
  placeholder: string;
  value: number | null;
  onChange: (v: number | null) => void;
}) {
  return (
    <label className="flex items-center justify-between gap-3">
      <span className="text-sm text-on-surface">
        {props.label}
        {props.hint && <span className="md-supporting block">{props.hint}</span>}
      </span>
      <span className="flex items-center gap-2">
        <input
          type="number"
          min={0}
          value={props.value ?? ""}
          placeholder={props.placeholder}
          onChange={(e) => props.onChange(e.target.value === "" ? null : Math.max(0, Number(e.target.value)))}
          className={`${field} w-28 text-right`}
        />
        <span className="w-8 text-sm text-on-surface-variant">{props.unit}</span>
      </span>
    </label>
  );
}

function PropertyTool({ google }: { google: MeasuredSun | null }) {
  const { roof, floors, clearRoof, setFloors } = useStore();
  if (!roof) return <FindProperty />;
  return (
    <div className="space-y-4">
      {!google?.available && (
        <NumberRow
          label="Floors below the roof"
          hint={`About ${floors * FLOOR_HEIGHT_M} m high`}
          unit=""
          placeholder="2"
          value={floors}
          onChange={(v) => setFloors(Math.max(1, Math.min(60, v ?? 1)))}
        />
      )}
      <button className={outlined} onClick={clearRoof}>
        Choose a different property
      </button>
    </div>
  );
}

function ElectricityTool() {
  const { monthlyUnits, setMonthlyUnits } = useStore();
  return (
    <div className="space-y-4">
      <BillUpload />
      <NumberRow
        label="Units in a typical month"
        hint="Shown on your bill as “units consumed”"
        unit="kWh"
        placeholder="e.g. 300"
        value={monthlyUnits}
        onChange={setMonthlyUnits}
      />
    </div>
  );
}

function CostTool({ money }: { money: Money }) {
  const { monthlyBill, quotedCost, discomId, setMoney } = useStore();
  return (
    <div className="space-y-4">
      <label className="block">
        <span className="text-sm text-on-surface">Electricity company</span>
        <select
          value={discomId ?? OTHER_DISCOM}
          onChange={(e) => setMoney({ discomId: e.target.value })}
          className={`${field} mt-1 w-full`}
        >
          {Object.entries(money.policy?.discoms ?? {}).map(([id, d]) => (
            <option key={id} value={id}>
              {d.name}
            </option>
          ))}
          <option value={OTHER_DISCOM}>Another company</option>
        </select>
      </label>
      <NumberRow
        label="Typical monthly bill"
        hint="Makes savings match what you really pay"
        unit="₹"
        placeholder="optional"
        value={monthlyBill}
        onChange={(v) => setMoney({ monthlyBill: v })}
      />
      <NumberRow
        label="A vendor's quote"
        hint="Before subsidy, if you have one"
        unit="₹"
        placeholder="optional"
        value={quotedCost}
        onChange={(v) => setMoney({ quotedCost: v })}
      />
    </div>
  );
}

function MapTool({ sun, measured }: { sun: SunPosition | null; measured: boolean }) {
  const { preview, setPreview, showSunMap, setShowSunMap } = useStore();
  const [playing, setPlaying] = useState(false);
  const minutesRef = useRef(preview.minutes);
  useEffect(() => {
    minutesRef.current = preview.minutes;
  }, [preview.minutes]);
  useEffect(() => {
    if (!playing) return;
    const timer = setInterval(() => {
      const next = minutesRef.current + 10;
      setPreview({ minutes: next > 19 * 60 ? 5 * 60 : next });
    }, 80);
    return () => clearInterval(timer);
  }, [playing, setPreview]);

  return (
    <div className="space-y-4">
      <label className="flex items-center gap-3 text-sm text-on-surface">
        <input
          type="checkbox"
          checked={showSunMap}
          onChange={(e) => setShowSunMap(e.target.checked)}
          className="h-[18px] w-[18px] accent-primary"
        />
        Show the sun map colours on the roof
      </label>
      {!measured && (
        <div className="md-card-outlined">
          <div className="flex items-center justify-between">
            <span className="text-sm text-on-surface">
              Shadows on 21 {MONTHS[preview.month - 1]} at {clock(preview.minutes)}
            </span>
            <button className="md-text h-8" onClick={() => setPlaying(!playing)}>
              {playing ? "Pause" : "Play day"}
            </button>
          </div>
          <input
            type="range"
            aria-label="Time of day"
            min={5 * 60}
            max={19 * 60}
            step={10}
            value={preview.minutes}
            onChange={(e) => setPreview({ minutes: Number(e.target.value) })}
            className="mt-3 w-full accent-primary"
          />
          <input
            type="range"
            aria-label="Month"
            min={1}
            max={12}
            value={preview.month}
            onChange={(e) => setPreview({ month: Number(e.target.value) })}
            className="mt-2 w-full accent-primary"
          />
          <p className="md-supporting mt-1">
            {sun && sun.elevation > 0 ? `Sun ${fmt(sun.elevation)}° above the horizon` : "Sun is below the horizon"}
          </p>
        </div>
      )}
    </div>
  );
}

function AskTool({ analysis, money }: { analysis: ShadingResult; money: Money }) {
  const chat = useStore((s) => s.chat);
  const [draft, setDraft] = useState("");
  const [language, setLanguage] = useState<SpeechLanguage>("en-IN");
  const [mic, setMic] = useState<"idle" | "recording" | "transcribing">("idle");
  const [micError, setMicError] = useState<string | null>(null);
  const recording = useRef<Recording | null>(null);

  const send = (question: string) => {
    setDraft("");
    void ask(question, analysis, money.sizing);
  };

  const toggleMic = async () => {
    setMicError(null);
    if (mic === "idle") {
      try {
        recording.current = await startRecording();
        setMic("recording");
      } catch {
        setMicError("Microphone access is needed to speak your question.");
      }
      return;
    }
    if (mic !== "recording" || !recording.current) return;
    setMic("transcribing");
    try {
      const { text } = await transcribe(await recording.current.stop(), language);
      if (text) setDraft((d) => (d ? `${d} ${text}` : text));
      else setMicError("Couldn't hear any words. Try again a little closer to the microphone.");
    } catch (err) {
      setMicError(err instanceof Error ? err.message : "Speech recognition failed.");
    } finally {
      recording.current = null;
      setMic("idle");
    }
  };

  return (
    <div className="space-y-3">
      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          send(draft);
        }}
      >
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Type your question"
          aria-label="Question for the advisor"
          className={`${field} min-w-0 flex-1`}
        />
        <button className={primary} disabled={chat.waiting || !draft.trim()}>
          Ask
        </button>
      </form>
      <div className="flex items-center gap-2">
        <button
          type="button"
          className={mic === "recording" ? "md-button bg-error text-on-error" : secondary}
          disabled={mic === "transcribing"}
          onClick={toggleMic}
        >
          {mic === "idle" ? "Speak instead" : mic === "recording" ? "Stop and transcribe" : "Transcribing…"}
        </button>
        <select
          value={language}
          onChange={(e) => setLanguage(e.target.value as SpeechLanguage)}
          aria-label="Spoken language"
          className={field}
        >
          <option value="en-IN">English</option>
          <option value="hi-IN">हिंदी</option>
        </select>
      </div>
      {micError && <p className="text-xs text-error">{micError}</p>}
      <div className="flex flex-wrap gap-2">
        {SUGGESTIONS.map((s) => (
          <button key={s} className="md-chip" disabled={chat.waiting} onClick={() => send(s)}>
            {s}
          </button>
        ))}
      </div>
    </div>
  );
}

function SaveTool() {
  const shared = useStore((s) => s.shared);
  const [state, setState] = useState<"idle" | "saving" | { error: string }>("idle");

  const save = async () => {
    setState("saving");
    try {
      const { roof, floors, obstructions, horizon, monthlyUnits, monthlyBill, quotedCost, discomId, sanctionedLoadKw } =
        useStore.getState();
      const { code } = await saveSurvey({
        roof,
        floors,
        obstructions,
        horizon,
        monthlyUnits,
        monthlyBill,
        quotedCost,
        discomId,
        sanctionedLoadKw,
      });
      const url = `${window.location.origin}${window.location.pathname}?s=${code}`;
      useStore.setState({ shared: { url, qr: await QRCode.toDataURL(url, { margin: 1, width: 180 }) } });
      setState("idle");
    } catch (err) {
      setState({ error: err instanceof Error ? err.message : "Couldn't save the survey." });
    }
  };

  return (
    <div className="space-y-2">
      <button className={secondary} disabled={state === "saving"} onClick={save}>
        {state === "saving" ? "Saving…" : shared ? "Save again with latest changes" : "Save and get a link"}
      </button>
      {typeof state === "object" && <p className="text-xs text-error">{state.error}</p>}
    </div>
  );
}

/** Left panel: everything the user does. Results of each tool appear in the right panel. */
export default function ToolsPanel({
  analysis,
  sun,
  google,
  money,
}: {
  analysis: ShadingResult | null;
  sun: SunPosition | null;
  google: MeasuredSun | null;
  money: Money;
}) {
  const roof = useStore((s) => s.roof);
  const hydrated = useStore((s) => s.hydrated);
  const monthlyUnits = useStore((s) => s.monthlyUnits);
  const measured = Boolean(google?.available);
  if (!hydrated) return <aside className="w-full shrink-0 bg-surface lg:w-[340px]" />;

  return (
    <aside className="w-full shrink-0 overflow-y-auto bg-surface lg:h-full lg:w-[340px] lg:border-r lg:border-outline-variant">
      <Tool
        title="Your property"
        description={
          roof
            ? "The outlined area is what we are planning for."
            : "Search for your address, then tap your roof. We outline it and measure its sun and shade for you."
        }
      >
        <PropertyTool google={google} />
      </Tool>

      {roof && analysis && (
        <>
          <Tool
            title="Your electricity"
            description="Sets the size of system you need. Upload a photo of a recent bill and we read it, or type your monthly units."
          >
            <ElectricityTool />
          </Tool>

          {monthlyUnits && (
            <Tool
              title="Cost details"
              description="We pick your electricity company from the map. Add your bill amount or a vendor's quote to sharpen the figures."
            >
              <CostTool money={money} />
            </Tool>
          )}

          <Tool
            title="Map display"
            description={
              measured
                ? "The colours on the roof show where the sun falls over a year."
                : "The colours show yearly sun. The sliders show where shadows fall at a chosen time."
            }
          >
            <MapTool sun={sun} measured={measured} />
          </Tool>

          <details className="group border-b border-outline-variant" open={Boolean(google && !measured)}>
            <summary className="flex cursor-pointer list-none items-start justify-between gap-3 px-4 py-5 hover:bg-surface-container-low">
              <span>
                <span className="md-title block">Improve the shade estimate</span>
                <span className="md-body mt-1 block">
                  {measured
                    ? "Not needed here: the shade is already measured. Use it only if something nearby is newer than the survey."
                    : google
                      ? "No 3D survey exists for this spot, so mark what stands around the roof, or scan it with your phone."
                      : "Mark anything that shades the roof, or scan the skyline with your phone."}
                </span>
              </span>
              <span className="mt-1 text-on-surface-variant transition group-open:rotate-90" aria-hidden>
                ›
              </span>
            </summary>
            <div className="px-4 pb-5">
              <ObstructionsStep />
            </div>
          </details>

          <Tool
            title="Ask a question"
            description="Ask about your plan in English or Hindi, by typing or speaking. Answers appear on the right and use your own figures."
          >
            <AskTool analysis={analysis} money={money} />
          </Tool>

          <Tool
            title="Save or share"
            description="Get a link and QR code to open this on your phone, or to send to family or an installer."
          >
            <SaveTool />
          </Tool>
        </>
      )}
    </aside>
  );
}
