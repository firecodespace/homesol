"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { centroid, localFrame, polygonArea } from "@/lib/geo/local";
import { detectObstructions } from "@/lib/detect/detect";
import { reportVerdict } from "@/lib/feedback";
import { fetchImageryInfo, searchPlaces, type ImageryInfo, type Place } from "@/lib/imagery";
import { horizonCoverage } from "@/lib/solar/horizon";
import { USABLE_ACCESS, type ShadingResult } from "@/lib/solar/shading";
import { AREA_PER_KW_M2 } from "@/lib/solar/shading";
import { PANEL_KW, PERFORMANCE_RATIO } from "@/lib/solar/sizing";
import { useSizing } from "@/lib/useSizing";
import type { SunPosition } from "@/lib/solar/sun";
import AdvisorChat from "./AdvisorChat";
import BillUpload from "./BillUpload";
import HorizonChart from "./HorizonChart";
import MoneyStep from "./MoneyStep";
import ShareSurvey from "./ShareSurvey";
import { fmt, primary, secondary, Stat } from "./ui";
import { FLOOR_HEIGHT_M, useStore, type Obstruction, type ObstructionKind } from "@/lib/store";

const SQFT_PER_M2 = 10.7639;
const FT_PER_M = 3.28084;
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const KINDS: Record<ObstructionKind, string> = {
  building: "Building",
  tree: "Tree",
  tank: "Water tank",
  other: "Other",
};

const clock = (minutes: number) =>
  `${String(Math.floor(minutes / 60)).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}`;
const imageryDate = (i: ImageryInfo) => `${i.day} ${MONTHS[i.month - 1]} ${i.year}`;


function Section({ step, title, children }: { step: number; title: string; children: ReactNode }) {
  return (
    <section className="border-b border-slate-800 px-5 py-5">
      <h2 className="mb-3 flex items-center gap-2.5 text-sm font-semibold text-slate-100">
        <span className="grid h-6 w-6 place-items-center rounded-full bg-slate-800 text-xs text-amber-300">{step}</span>
        {title}
      </h2>
      {children}
    </section>
  );
}

function DrawingControls({ hint, canFinish }: { hint: string; canFinish: boolean }) {
  const { draft, finishDrawing, undoDraftPoint, cancel } = useStore();
  return (
    <div className="rounded-lg border border-amber-400/40 bg-amber-400/10 p-3">
      <p className="text-sm text-amber-100">{hint}</p>
      <div className="mt-3 flex gap-2">
        {canFinish && (
          <button className={primary} disabled={draft.length < 3} onClick={finishDrawing}>
            Finish shape
          </button>
        )}
        <button className={secondary} disabled={draft.length === 0} onClick={undoDraftPoint}>
          Undo point
        </button>
        <button className={secondary} onClick={cancel}>
          Cancel
        </button>
      </div>
    </div>
  );
}

function PlaceSearch() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Place[] | null>(null);
  const requestFlyTo = useStore((s) => s.requestFlyTo);

  useEffect(() => {
    if (query.trim().length < 3) return;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      searchPlaces(query, controller.signal)
        .then(setResults)
        .catch(() => {});
    }, 300);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [query]);

  const shown = query.trim().length < 3 ? null : results;
  return (
    <div>
      <input
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Search your area, street or landmark"
        className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500 focus:border-amber-400 focus:outline-none"
      />
      {shown && (
        <ul className="mt-2 overflow-hidden rounded-lg border border-slate-800">
          {shown.length === 0 && <li className="px-3 py-2 text-sm text-slate-500">No places found.</li>}
          {shown.map((place, i) => (
            <li key={i}>
              <button
                className="block w-full px-3 py-2 text-left text-sm text-slate-300 hover:bg-slate-800"
                onClick={() => {
                  requestFlyTo(place.center);
                  setResults(null);
                  setQuery("");
                }}
              >
                {place.label}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function RoofStep() {
  const { mode, roof, floors, startDrawing, clearRoof, setFloors } = useStore();
  const [imagery, setImagery] = useState<ImageryInfo | null>(null);

  useEffect(() => {
    if (!roof) return;
    const controller = new AbortController();
    fetchImageryInfo(centroid(roof), controller.signal)
      .then(setImagery)
      .catch(() => {});
    return () => controller.abort();
  }, [roof]);

  if (mode === "roof") {
    return (
      <DrawingControls
        canFinish
        hint="Click each corner of your roof on the map. Click the first corner again, or press Finish, to close the shape."
      />
    );
  }
  if (!roof) {
    return (
      <div className="space-y-3">
        <PlaceSearch />
        <p className="text-sm text-slate-400">Zoom in until you can see your roof clearly, then outline it.</p>
        <button className={primary} onClick={() => startDrawing("roof")}>
          Outline my roof
        </button>
      </div>
    );
  }

  const frame = localFrame(centroid(roof));
  const area = polygonArea(roof.map(frame.toXY));
  return (
    <div className="space-y-3">
      <p className="text-sm text-slate-300">
        Roof area <span className="font-semibold text-slate-50">{fmt(area)} m²</span>{" "}
        <span className="text-slate-500">({fmt(area * SQFT_PER_M2)} sq ft)</span>
      </p>
      <label className="flex items-center justify-between gap-3 text-sm text-slate-300">
        Floors below the roof
        <span className="flex items-center gap-2">
          <input
            type="number"
            min={1}
            max={60}
            value={floors}
            onChange={(e) => setFloors(Math.max(1, Math.min(60, Number(e.target.value) || 1)))}
            className="w-16 rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-right text-slate-100"
          />
          <span className="w-16 text-slate-500">≈ {floors * FLOOR_HEIGHT_M} m</span>
        </span>
      </label>
      {imagery && (
        <p className="text-xs text-slate-500">
          Satellite image taken {imageryDate(imagery)} · {imagery.source}
        </p>
      )}
      <button className={secondary} onClick={clearRoof}>
        Start over
      </button>
    </div>
  );
}

function ObstructionCard({ index, obstruction: o }: { index: number; obstruction: Obstruction }) {
  const { mode, draft, measureTarget, measureStatus, updateObstruction, removeObstruction, startMeasuring, cancel } =
    useStore();
  const measuring = mode === "measure" && measureTarget === o.id;
  const status = measureTarget === o.id ? measureStatus : null;
  const m = o.measurement;
  const roof = useStore((s) => s.roof);

  // A person's yes or no on each detection is what detection is scored and improved on.
  const confirm = () => {
    if (o.detectionId && roof) reportVerdict("confirmed", o.detectionId, o, roof);
    updateObstruction(o.id, { suggested: false });
  };
  const reject = () => {
    if (o.suggested && o.detectionId && roof) reportVerdict("rejected", o.detectionId, o, roof);
    removeObstruction(o.id);
  };

  return (
    <li className="rounded-lg border border-slate-800 bg-slate-900/60 p-3">
      <div className="flex items-center gap-2">
        <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-rose-500 text-xs font-semibold text-white">
          {index + 1}
        </span>
        <select
          value={o.kind}
          onChange={(e) => {
            const kind = e.target.value as ObstructionKind;
            updateObstruction(o.id, { kind, reference: kind === "tank" ? "roof" : o.reference });
          }}
          className="flex-1 rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-sm text-slate-100"
        >
          {Object.entries(KINDS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
        <button
          className="text-xs text-slate-500 hover:text-rose-400"
          onClick={reject}
          aria-label={`Remove obstruction ${index + 1}`}
        >
          Remove
        </button>
      </div>

      {o.suggested && (
        <div className="mt-2 rounded-md bg-violet-500/10 px-2 py-2 text-xs text-violet-200">
          <p>
            Found automatically{o.label ? `: ${o.label}` : ""}. Is this really something that could shade your roof?
            Fix its type and height below first if they are off
            {o.measurement ? " (height measured from its shadow)" : " (height is a typical-size guess)"}.
          </p>
          <div className="mt-2 flex gap-2">
            <button className="rounded-md bg-violet-500/30 px-2 py-1 font-medium hover:bg-violet-500/50" onClick={confirm}>
              Yes, it&apos;s there
            </button>
            <button className="rounded-md border border-violet-400/40 px-2 py-1 font-medium hover:bg-violet-500/20" onClick={reject}>
              No, remove it
            </button>
          </div>
        </div>
      )}

      <div className="mt-3 flex items-center gap-2 text-sm text-slate-300">
        <span>Height</span>
        <input
          type="number"
          min={0}
          step={0.5}
          value={o.heightM ?? ""}
          placeholder="?"
          onChange={(e) =>
            updateObstruction(o.id, { heightM: e.target.value === "" ? null : Math.max(0, Number(e.target.value)) })
          }
          className="w-20 rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-right text-slate-100"
        />
        <span>m above</span>
        <select
          value={o.reference}
          onChange={(e) => updateObstruction(o.id, { reference: e.target.value as Obstruction["reference"] })}
          className="rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-slate-100"
        >
          <option value="ground">the ground</option>
          <option value="roof">my roof</option>
        </select>
      </div>

      {measuring ? (
        <div className="mt-3 rounded-lg border border-sky-400/40 bg-sky-400/10 p-3 text-sm text-sky-100">
          {draft.length === 0
            ? "Step 1 of 2: click the foot of the corner that casts the shadow, where the wall meets the surface the shadow falls on."
            : "Step 2 of 2: click the tip of that same corner's shadow."}
          <button className={`${secondary} mt-3 block`} onClick={cancel}>
            Cancel
          </button>
        </div>
      ) : (
        <button className={`${secondary} mt-3`} onClick={() => startMeasuring(o.id)}>
          {m ? "Re-measure from shadow" : "Measure height from its shadow"}
        </button>
      )}

      {status?.state === "loading" && <p className="mt-2 text-xs text-slate-400">Reading the satellite image date…</p>}
      {status?.state === "error" && <p className="mt-2 text-xs text-rose-300">{status.message}</p>}

      {m && (
        <div className="mt-3 space-y-1 text-xs text-slate-400">
          <p>
            Shadow of {fmt(m.estimate.shadowLengthM, 1)} m with the sun {fmt(m.estimate.sunElevation)}° high gives{" "}
            <span className="text-slate-200">
              {fmt(m.estimate.heightM, 1)} m ({fmt(m.estimate.heightM * FT_PER_M)} ft)
            </span>
            , likely between {fmt(m.estimate.range[0], 1)} and {fmt(m.estimate.range[1], 1)} m.
          </p>
          <p>
            Image dated {imageryDate(m.imagery)}; capture time solved from the shadow direction as{" "}
            {new Date(m.estimate.capturedAt).toLocaleTimeString("en-IN", {
              timeZone: "Asia/Kolkata",
              hour: "2-digit",
              minute: "2-digit",
            })}{" "}
            IST.
          </p>
          {m.estimate.warnings.map((w) => (
            <p key={w} className="text-amber-300">
              {w}
            </p>
          ))}
        </div>
      )}
    </li>
  );
}

function SkylineScan() {
  const { roof, horizon, setHorizon, setScanOpen } = useStore();
  if (!roof) return null;
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-3">
      <p className="text-sm font-medium text-slate-200">Scan the skyline from the roof</p>
      {horizon ? (
        <div className="mt-3 space-y-3">
          <HorizonChart profile={horizon} at={centroid(roof)} />
          <p className="text-xs text-slate-400">
            {fmt(horizonCoverage(horizon) * 100)}% of the compass traced. Untraced directions count as open sky.
          </p>
          <div className="flex gap-2">
            <button className={secondary} onClick={() => setScanOpen(true)}>
              Scan again
            </button>
            <button className={secondary} onClick={() => setHorizon(null)}>
              Remove scan
            </button>
          </div>
        </div>
      ) : (
        <>
          <p className="mt-1 text-sm text-slate-400">
            The most accurate option. Stand on the roof with your phone and trace the tops of everything around you.
          </p>
          <button className={`${secondary} mt-3`} onClick={() => setScanOpen(true)}>
            Scan with my phone
          </button>
        </>
      )}
    </div>
  );
}

function ObstructionsStep() {
  const { mode, roof, obstructions, startDrawing, addObstructions } = useStore();
  const [detecting, setDetecting] = useState(false);
  const [detectNote, setDetectNote] = useState<{ ok: boolean; text: string } | null>(null);

  const detect = async () => {
    if (!roof) return;
    setDetecting(true);
    setDetectNote(null);
    try {
      const { detectionId, obstructions: found } = await detectObstructions(roof);
      addObstructions(found, detectionId);
      setDetectNote({
        ok: true,
        text: found.length
          ? `Found ${found.length} possible obstruction${found.length > 1 ? "s" : ""}. Say yes or no to each one below, and add any it missed.`
          : "Nothing that would shade this roof was found. Add anything it missed by hand.",
      });
    } catch (err) {
      setDetectNote({ ok: false, text: err instanceof Error ? err.message : "Detection failed." });
    } finally {
      setDetecting(false);
    }
  };

  return (
    <div className="space-y-3">
      <p className="text-sm text-slate-400">
        Outline anything that could shade the roof: taller neighbours, trees, water tanks, stair rooms.
      </p>
      <button className={primary} disabled={detecting || mode !== "idle"} onClick={detect}>
        {detecting ? "Looking at the satellite image…" : "Find obstructions for me"}
      </button>
      {detectNote && <p className={`text-xs ${detectNote.ok ? "text-slate-400" : "text-rose-300"}`}>{detectNote.text}</p>}
      <p className="text-xs text-slate-500">
        Your yes and no answers, with the roof&apos;s outline and location, are saved to make detection better. No
        name or contact details are attached.
      </p>
      {obstructions.length > 0 && (
        <ul className="space-y-2">
          {obstructions.map((o, i) => (
            <ObstructionCard key={o.id} index={i} obstruction={o} />
          ))}
        </ul>
      )}
      {mode === "obstruction" ? (
        <DrawingControls canFinish hint="Click around the outline of the object, then close the shape." />
      ) : (
        <button className={secondary} disabled={mode !== "idle"} onClick={() => startDrawing("obstruction")}>
          + Add one by hand
        </button>
      )}
      <SkylineScan />
    </div>
  );
}

function ResultsStep({ analysis, sun }: { analysis: ShadingResult; sun: SunPosition | null }) {
  const { preview, setPreview, obstructions, showSunMap, setShowSunMap } = useStore();
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

  const unmeasured = obstructions.filter((o) => !o.heightM).length;
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-2">
        <Stat label="Yearly sun reaching roof" value={`${fmt(analysis.meanAccess * 100)}%`} />
        <Stat label="Roof could hold up to" value={`${fmt(analysis.capacityKw, 1)} kW`} sub="see step 4 for what you need" />
        <Stat
          label="Good area for panels"
          value={`${fmt(analysis.usableAreaM2)} m²`}
          sub={`${fmt(analysis.usableAreaM2 * SQFT_PER_M2)} sq ft`}
        />
        <Stat label="Lost to shade" value={`${fmt(Math.max(0, Math.round(analysis.roofAreaM2 - analysis.usableAreaM2)))} m²`} />
      </div>

      <div>
        <div className="h-2.5 rounded-full bg-gradient-to-r from-[#3b0764] via-[#c2410c] via-60% to-[#fef9c3]" />
        <div className="mt-1 flex justify-between text-xs text-slate-500">
          <span>Mostly shaded</span>
          <span>Full sun all year</span>
        </div>
        <label className="mt-2 flex items-center gap-2 text-xs text-slate-400">
          <input
            type="checkbox"
            checked={showSunMap}
            onChange={(e) => setShowSunMap(e.target.checked)}
            className="accent-amber-400"
          />
          Show the sun map on the roof
        </label>
      </div>

      <div className="rounded-lg border border-slate-800 p-3">
        <div className="flex items-center justify-between text-sm text-slate-300">
          <span>
            Shadows on 21 {MONTHS[preview.month - 1]} at {clock(preview.minutes)}
          </span>
          <button className="text-xs font-medium text-amber-300 hover:text-amber-200" onClick={() => setPlaying(!playing)}>
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
          className="mt-3 w-full accent-amber-400"
        />
        <input
          type="range"
          aria-label="Month"
          min={1}
          max={12}
          value={preview.month}
          onChange={(e) => setPreview({ month: Number(e.target.value) })}
          className="mt-2 w-full accent-amber-400"
        />
        <p className="mt-1 text-xs text-slate-500">
          {sun && sun.elevation > 0 ? `Sun ${fmt(sun.elevation)}° above the horizon` : "Sun is below the horizon"}
        </p>
      </div>

      {unmeasured > 0 && (
        <p className="text-xs text-amber-300">
          {unmeasured} obstruction{unmeasured > 1 ? "s have" : " has"} no height yet and{" "}
          {unmeasured > 1 ? "are" : "is"} left out of these numbers.
        </p>
      )}
      <p className="text-xs text-slate-500">
        Panels are counted where at least {USABLE_ACCESS * 100}% of the year&apos;s direct sun arrives, at 10 m² per kW.
        Assumes a flat roof.
      </p>
    </div>
  );
}

function SizingStep({ analysis }: { analysis: ShadingResult }) {
  const { monthlyUnits, setMonthlyUnits } = useStore();
  const { sizing, sunlight } = useSizing(analysis);
  const lowest = sizing ? sizing.monthlyKwh.indexOf(Math.min(...sizing.monthlyKwh)) : 0;
  const highest = sizing ? sizing.monthlyKwh.indexOf(Math.max(...sizing.monthlyKwh)) : 0;

  return (
    <div className="space-y-4">
      <BillUpload />
      <label className="flex items-center justify-between gap-3 text-sm text-slate-300">
        Units on a typical monthly bill
        <span className="flex items-center gap-2">
          <input
            type="number"
            min={0}
            step={10}
            placeholder="e.g. 300"
            value={monthlyUnits ?? ""}
            onChange={(e) => setMonthlyUnits(e.target.value === "" ? null : Math.max(0, Number(e.target.value)))}
            className="w-24 rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-right text-slate-100"
          />
          <span className="text-slate-500">kWh</span>
        </span>
      </label>
      <p className="text-xs text-slate-500">
        Your bill lists this as &quot;units consumed&quot;. Use an average month, not your highest.
      </p>

      {sunlight && "error" in sunlight && <p className="text-xs text-rose-300">{sunlight.error}</p>}
      {monthlyUnits && !sunlight && <p className="text-xs text-slate-400">Loading sunlight data for your location…</p>}

      {sizing && sizing.panels === 0 && (
        <p className="text-sm text-amber-300">The unshaded part of this roof is too small for even one panel.</p>
      )}
      {sizing && sizing.panels > 0 && (
        <>
          <div className="grid grid-cols-2 gap-2">
            <Stat label="Recommended system" value={`${fmt(sizing.systemKw, 1)} kW`} sub={`${sizing.panels} panels`} />
            <Stat label="Covers" value={`${fmt(sizing.coverage * 100)}%`} sub="of your yearly usage" />
            <Stat label="Generates about" value={`${fmt(sizing.annualKwh / 12)} units`} sub="per month on average" />
            <Stat
              label="Roof space needed"
              value={`${fmt(sizing.systemKw * AREA_PER_KW_M2)} m²`}
              sub={`of ${fmt(analysis.usableAreaM2)} m² available`}
            />
          </div>
          <p className="text-xs text-slate-400">
            Expect about {fmt(sizing.monthlyKwh[highest])} units in {MONTHS[highest]} and{" "}
            {fmt(sizing.monthlyKwh[lowest])} in {MONTHS[lowest]}.
            {sizing.limitedBy === "roof" && " The roof is the limit here: a bigger system would not fit in the sunny area."}
          </p>
          <p className="text-xs text-slate-500">
            Based on 25 years of NASA satellite sunlight records for this spot, {PANEL_KW * 1000} W
            panels, and {PERFORMANCE_RATIO * 100}% of that sunlight reaching your meter after real-world losses.
          </p>
        </>
      )}
    </div>
  );
}

export default function Sidebar({ analysis, sun }: { analysis: ShadingResult | null; sun: SunPosition | null }) {
  const roof = useStore((s) => s.roof);
  return (
    <aside className="flex max-h-[55dvh] w-full shrink-0 flex-col overflow-y-auto bg-slate-950 md:max-h-none md:w-[400px]">
      <header className="border-b border-slate-800 px-5 py-4">
        <h1 className="text-lg font-semibold tracking-tight text-slate-50">
          home<span className="text-amber-400">sol</span>
        </h1>
        <p className="text-sm text-slate-400">See how much sun your roof really gets.</p>
      </header>
      <Section step={1} title="Find and outline your roof">
        <RoofStep />
      </Section>
      {roof && (
        <Section step={2} title="Mark what could shade it">
          <ObstructionsStep />
        </Section>
      )}
      {analysis && (
        <Section step={3} title="Your roof's sun map">
          <ResultsStep analysis={analysis} sun={sun} />
        </Section>
      )}
      {analysis && (
        <Section step={4} title="Size it to your electricity bill">
          <SizingStep analysis={analysis} />
        </Section>
      )}
      {analysis && (
        <Section step={5} title="Cost, subsidy and savings">
          <MoneyStep analysis={analysis} />
        </Section>
      )}
      {analysis && (
        <Section step={6} title="Ask the advisor">
          <AdvisorChat analysis={analysis} />
        </Section>
      )}
      {roof && (
        <Section step={7} title="Save and share">
          <ShareSurvey />
        </Section>
      )}
    </aside>
  );
}
