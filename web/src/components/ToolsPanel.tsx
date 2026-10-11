"use client";

import { useRef, useState, type ReactNode } from "react";
import QRCode from "qrcode";
import { ask } from "@/lib/advisor";
import { saveSurvey, transcribe, type SpeechLanguage } from "@/lib/api";
import { startRecording, type Recording } from "@/lib/audio";
import type { Analysis } from "@/lib/site/analysis";
import { FLOOR_HEIGHT_M, useStore } from "@/lib/store";
import { OTHER_DISCOM, type Money } from "@/lib/useMoney";
import BillUpload from "./BillUpload";
import { FindProperty, ObstructionsStep } from "./PropertyTools";
import { Icon } from "./ui";

const SUGGESTIONS = ["Is solar worth it for my home?", "What is shading my roof?", "मुझे सब्सिडी कितनी मिलेगी?"];

/** One tool: what it is, what it does for you, then its controls. */
function Tool({ icon, title, description, children }: { icon: string; title: string; description: string; children: ReactNode }) {
  return (
    <section className="rounded-lg bg-surface p-4">
      <div className="flex items-center gap-3">
        <Icon name={icon} className="text-primary" />
        <h2 className="md-title">{title}</h2>
      </div>
      <p className="md-body mt-2">{description}</p>
      <div className="mt-4 space-y-4">{children}</div>
    </section>
  );
}

/** A labelled field: label above, the control full width, an optional hint below. */
export function Field({ label, hint, suffix, children }: { label: string; hint?: string; suffix?: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="md-label">{label}</span>
      <span className="relative mt-1 block">
        {children}
        {suffix && (
          <span className="pointer-events-none absolute right-4 top-1/2 -translate-y-1/2 text-sm text-on-surface-variant">
            {suffix}
          </span>
        )}
      </span>
      {hint && <span className="md-supporting mt-1 block">{hint}</span>}
    </label>
  );
}

function NumberField(props: {
  label: string;
  hint?: string;
  suffix?: string;
  placeholder: string;
  value: number | null;
  onChange: (v: number | null) => void;
}) {
  return (
    <Field label={props.label} hint={props.hint} suffix={props.suffix}>
      <input
        type="number"
        inputMode="decimal"
        min={0}
        value={props.value ?? ""}
        placeholder={props.placeholder}
        onChange={(e) => props.onChange(e.target.value === "" ? null : Math.max(0, Number(e.target.value)))}
        className={`md-field w-full ${props.suffix ? "pr-14" : ""}`}
      />
    </Field>
  );
}

function PropertyTool() {
  const { roof, floors, site, siteStatus, clearRoof, setFloors } = useStore();
  if (!roof) return <FindProperty />;
  return (
    <>
      {siteStatus.state === "loading" && (
        <div>
          <p className="text-sm text-on-surface">Measuring your property in 3D…</p>
          <div className="mt-2 h-1 overflow-hidden rounded-full bg-secondary-container">
            <div className="h-full w-1/3 animate-[slide_1.2s_ease-in-out_infinite] rounded-full bg-primary" />
          </div>
        </div>
      )}
      {siteStatus.state === "limited" && (
        <div className="rounded-md bg-error-container p-3 text-sm text-on-error-container">
          <p>Measuring is paused for now. {siteStatus.reason}</p>
          <button
            className="md-text mt-2 h-8 px-2 text-on-error-container"
            // A fresh copy of the outline makes the page measure it again.
            onClick={() => useStore.setState((s) => ({ roof: s.roof && [...s.roof], siteStatus: { state: "idle" } }))}
          >
            <Icon name="refresh" className="text-[18px]" />
            Try again
          </button>
        </div>
      )}
      {siteStatus.state === "unavailable" && (
        <>
          <p className="rounded-md bg-secondary-container p-3 text-sm text-on-secondary-container">
            No 3D survey is available here, so the shade is estimated from what you tell us. {siteStatus.reason}
          </p>
          <NumberField
            label="Floors below the roof"
            hint={`About ${floors * FLOOR_HEIGHT_M} m high`}
            placeholder="2"
            value={floors}
            onChange={(v) => setFloors(Math.max(1, Math.min(60, v ?? 1)))}
          />
        </>
      )}
      {site?.surface.cut_off && (
        <p className="rounded-md bg-error-container p-3 text-sm text-on-error-container">
          This surface runs past the edge of the area we measured, so part of it is missing.
        </p>
      )}
      <button className="md-outlined w-full" onClick={clearRoof}>
        <Icon name="edit_location_alt" className="text-[18px]" />
        Change property
      </button>
    </>
  );
}

function CostTool({ money }: { money: Money }) {
  const { monthlyBill, quotedCost, discomId, setMoney } = useStore();
  const symbol = new Intl.NumberFormat("en", { style: "currency", currency: money.currency, maximumFractionDigits: 0 })
    .formatToParts(0)
    .find((p) => p.type === "currency")?.value;
  return (
    <>
      {money.hasPolicyData && (
        <Field label="Electricity company" hint="Chosen from your location. Change it if it is wrong.">
          <select
            value={discomId ?? OTHER_DISCOM}
            onChange={(e) => setMoney({ discomId: e.target.value })}
            className="md-field w-full"
          >
            {Object.entries(money.policy?.discoms ?? {}).map(([id, d]) => (
              <option key={id} value={id}>
                {d.name}
              </option>
            ))}
            <option value={OTHER_DISCOM}>Another company</option>
          </select>
        </Field>
      )}
      <NumberField
        label="Typical monthly bill"
        hint={
          money.hasPolicyData
            ? "Optional. Makes savings match what you really pay."
            : "Needed to work out savings: we have no tariff data for this country."
        }
        suffix={symbol}
        placeholder={money.hasPolicyData ? "Optional" : "Your monthly bill"}
        value={monthlyBill}
        onChange={(v) => setMoney({ monthlyBill: v })}
      />
      <NumberField
        label="A vendor's quote"
        hint={
          money.hasPolicyData
            ? "Optional. Before subsidy. We check it against the usual price."
            : "Before any incentives. Needed to work out payback."
        }
        suffix={symbol}
        placeholder="Optional"
        value={quotedCost}
        onChange={(v) => setMoney({ quotedCost: v })}
      />
    </>
  );
}

function AskTool({ analysis, money }: { analysis: Analysis; money: Money }) {
  const waiting = useStore((s) => s.chat.waiting);
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
    <>
      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          send(draft);
        }}
      >
        <Field label="Your question">
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="Type, or speak below"
            className="md-field w-full"
          />
        </Field>
        <button className="md-filled w-full" disabled={waiting || !draft.trim()}>
          <Icon name="send" className="text-[18px]" />
          {waiting ? "Answering…" : "Ask"}
        </button>
      </form>
      <div className="grid grid-cols-[1fr_auto] gap-2">
        <button
          type="button"
          className={mic === "recording" ? "md-button bg-error text-on-error" : "md-tonal"}
          disabled={mic === "transcribing"}
          onClick={toggleMic}
        >
          <Icon name={mic === "recording" ? "stop" : "mic"} className="text-[18px]" />
          {mic === "idle" ? "Speak" : mic === "recording" ? "Stop" : "Writing it down…"}
        </button>
        <select
          value={language}
          onChange={(e) => setLanguage(e.target.value as SpeechLanguage)}
          aria-label="Spoken language"
          className="md-field-dense"
        >
          <option value="en-IN">English</option>
          <option value="hi-IN">हिंदी</option>
        </select>
      </div>
      {micError && <p className="text-sm text-error">{micError}</p>}
      <div className="flex flex-wrap gap-2">
        {SUGGESTIONS.map((s) => (
          <button key={s} className="md-chip" disabled={waiting} onClick={() => send(s)}>
            {s}
          </button>
        ))}
      </div>
    </>
  );
}

function SaveTool() {
  const shared = useStore((s) => s.shared);
  const [state, setState] = useState<"idle" | "saving" | { error: string }>("idle");

  const save = async () => {
    setState("saving");
    try {
      const s = useStore.getState();
      const { code } = await saveSurvey({
        roof: s.roof,
        floors: s.floors,
        obstructions: s.obstructions,
        horizon: s.horizon,
        monthlyUnits: s.monthlyUnits,
        monthlyBill: s.monthlyBill,
        quotedCost: s.quotedCost,
        discomId: s.discomId,
        sanctionedLoadKw: s.sanctionedLoadKw,
      });
      const url = `${window.location.origin}${window.location.pathname}?s=${code}`;
      useStore.setState({ shared: { url, qr: await QRCode.toDataURL(url, { margin: 1, width: 180 }) } });
      setState("idle");
    } catch (err) {
      setState({ error: err instanceof Error ? err.message : "Couldn't save the survey." });
    }
  };

  return (
    <>
      <button className="md-tonal w-full" disabled={state === "saving"} onClick={save}>
        <Icon name="link" className="text-[18px]" />
        {state === "saving" ? "Saving…" : shared ? "Save again with latest changes" : "Save and get a link"}
      </button>
      {typeof state === "object" && <p className="text-sm text-error">{state.error}</p>}
    </>
  );
}

/** Left panel: everything the user does. What each tool produces appears in the results panel. */
export default function ToolsPanel({ analysis, money }: { analysis: Analysis | null; money: Money }) {
  const roof = useStore((s) => s.roof);
  const hydrated = useStore((s) => s.hydrated);
  const monthlyUnits = useStore((s) => s.monthlyUnits);
  const setMonthlyUnits = useStore((s) => s.setMonthlyUnits);
  const estimated = useStore((s) => s.siteStatus.state === "unavailable");
  const land = analysis?.model.surface.kind.includes("ground");

  return (
    <aside className="w-full shrink-0 overflow-x-hidden bg-surface-container-low lg:h-full lg:w-[300px] lg:overflow-y-auto xl:w-[360px]">
      <div className="space-y-3 p-3">
        {hydrated && (
          <Tool
            icon="location_on"
            title="Your property"
            description={
              roof
                ? "The white outline on the map is what we are planning for."
                : "Search for your address, then tap your roof. We outline it and measure its sun and shade for you."
            }
          >
            <PropertyTool />
          </Tool>
        )}

        {roof && analysis && (
          <>
            <Tool
              icon="bolt"
              title="Your electricity"
              description="Sets the size of system you need. Upload a photo of a recent bill and we read it, or type your monthly units."
            >
              <BillUpload />
              <NumberField
                label="Units in a typical month"
                hint="Your bill calls this “units consumed”."
                suffix="kWh"
                placeholder="For example 300"
                value={monthlyUnits}
                onChange={setMonthlyUnits}
              />
            </Tool>

            {monthlyUnits && (
              <Tool
                icon="payments"
                title="Cost details"
                description="Add what you know to sharpen the money figures. Everything here is optional unless it says otherwise."
              >
                <CostTool money={money} />
              </Tool>
            )}

            {estimated && (
              <Tool
                icon="visibility"
                title={land ? "Shade around the land" : "Shade around the roof"}
                description="Mark what could shade it: taller neighbours, trees, tanks, stair rooms. Or scan the skyline with your phone."
              >
                <ObstructionsStep />
              </Tool>
            )}

            <Tool
              icon="forum"
              title="Ask a question"
              description="Ask anything about your plan, in English or Hindi. The answer appears on the right and uses your own figures."
            >
              <AskTool analysis={analysis} money={money} />
            </Tool>

            <Tool
              icon="share"
              title="Save or share"
              description="Get a link and QR code to open this on your phone, or to send to family or an installer."
            >
              <SaveTool />
            </Tool>
          </>
        )}
      </div>
    </aside>
  );
}
