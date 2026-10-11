"use client";

import { useEffect, useState } from "react";
import { centroid } from "@/lib/geo/local";
import { detectObstructions } from "@/lib/detect/detect";
import { reportVerdict } from "@/lib/feedback";
import { searchPlaces, type ImageryInfo, type Place } from "@/lib/imagery";
import { horizonCoverage } from "@/lib/solar/horizon";
import { useStore, type Obstruction, type ObstructionKind } from "@/lib/store";
import HorizonChart from "./HorizonChart";
import { fmt, outlined, primary, secondary, textButton } from "./ui";

const FT_PER_M = 3.28084;
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const KINDS: Record<ObstructionKind, string> = {
  building: "Building",
  tree: "Tree",
  tank: "Water tank",
  other: "Other",
};

const imageryDate = (i: ImageryInfo) => `${i.day} ${MONTHS[i.month - 1]} ${i.year}`;


export function DrawingControls({ hint, canFinish }: { hint: string; canFinish: boolean }) {
  const { draft, finishDrawing, undoDraftPoint, cancel } = useStore();
  return (
    <div className="rounded-md bg-primary-container p-4">
      <p className="text-sm text-on-primary-container">{hint}</p>
      <div className="mt-3 flex flex-wrap gap-2">
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

export function PlaceSearch() {
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
        className="md-field w-full"
      />
      {shown && (
        <ul className="mt-1 overflow-hidden rounded-xs bg-surface-container shadow-level2">
          {shown.length === 0 && <li className="px-3 py-2 text-sm text-on-surface-variant">No places found.</li>}
          {shown.map((place, i) => (
            <li key={i}>
              <button
                className="block w-full px-4 py-3 text-left text-sm text-on-surface hover:bg-on-surface/8"
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

/** Search, then tap the roof to have it outlined; outlining by hand is the fallback. */
export function FindProperty() {
  const { mode, pick, startDrawing } = useStore();

  // With no roof yet, a tap on the map means "this is my roof".
  useEffect(() => {
    if (mode === "idle") useStore.setState({ mode: "pick" });
  }, [mode]);

  if (mode === "roof") {
    return (
      <DrawingControls
        canFinish
        hint="Click each corner of the area on the map. Click the first corner again, or press Finish, to close the shape."
      />
    );
  }
  return (
    <div className="space-y-3">
      <PlaceSearch />
      <div className="rounded-md bg-primary-container px-4 py-3 text-sm text-on-primary-container">
        {pick?.state === "finding" ? "Measuring the roof you tapped…" : "Zoom in and tap your roof on the map."}
      </div>
      {pick?.state === "failed" && <p className="text-sm text-error">{pick.message}</p>}
      <button className={textButton} onClick={() => startDrawing("roof")}>
        Outline it myself instead
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
    <li className="md-card-outlined">
      <div className="flex items-center gap-2">
        <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-error text-xs font-medium text-on-error">
          {index + 1}
        </span>
        <select
          value={o.kind}
          onChange={(e) => {
            const kind = e.target.value as ObstructionKind;
            updateObstruction(o.id, { kind, reference: kind === "tank" ? "roof" : o.reference });
          }}
          className="md-field-dense min-w-0 flex-1"
        >
          {Object.entries(KINDS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
        <button
          className="md-text h-8 px-2 text-error"
          onClick={reject}
          aria-label={`Remove obstruction ${index + 1}`}
        >
          Remove
        </button>
      </div>

      {o.suggested && (
        <div className="mt-3 rounded-md bg-tertiary-container p-3 text-xs text-on-tertiary-container">
          <p>
            Found automatically{o.label ? `: ${o.label}` : ""}. Is this really something that could shade your roof?
            Fix its type and height below first if they are off
            {o.measurement ? " (height measured from its shadow)" : " (height is a typical-size guess)"}.
          </p>
          <div className="mt-2 flex gap-2">
            <button className="md-button h-8 bg-tertiary px-4 text-on-tertiary" onClick={confirm}>
              Yes, it&apos;s there
            </button>
            <button className="md-button h-8 border border-tertiary px-4 text-tertiary" onClick={reject}>
              No, remove it
            </button>
          </div>
        </div>
      )}

      <div className="mt-3 flex items-center gap-2 text-sm text-on-surface">
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
          className="md-field-dense w-20 text-right"
        />
        <span>m above</span>
        <select
          value={o.reference}
          onChange={(e) => updateObstruction(o.id, { reference: e.target.value as Obstruction["reference"] })}
          className="md-field-dense"
        >
          <option value="ground">the ground</option>
          <option value="roof">my roof</option>
        </select>
      </div>

      {measuring ? (
        <div className="mt-3 rounded-md bg-secondary-container p-3 text-sm text-on-secondary-container">
          {draft.length === 0
            ? "Step 1 of 2: click the foot of the corner that casts the shadow, where the wall meets the surface the shadow falls on."
            : "Step 2 of 2: click the tip of that same corner's shadow."}
          <button className={`${outlined} mt-3`} onClick={cancel}>
            Cancel
          </button>
        </div>
      ) : (
        <button className={`${secondary} mt-3`} onClick={() => startMeasuring(o.id)}>
          {m ? "Re-measure from shadow" : "Measure height from its shadow"}
        </button>
      )}

      {status?.state === "loading" && <p className="mt-2 text-xs text-on-surface-variant">Reading the satellite image date…</p>}
      {status?.state === "error" && <p className="mt-2 text-xs text-error">{status.message}</p>}

      {m && (
        <div className="mt-3 space-y-1 text-xs text-on-surface-variant">
          <p>
            Shadow of {fmt(m.estimate.shadowLengthM, 1)} m with the sun {fmt(m.estimate.sunElevation)}° high gives{" "}
            <span className="text-on-surface">
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
            <p key={w} className="text-primary">
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
    <div className="md-card-outlined">
      <p className="md-title">Scan the skyline from the roof</p>
      {horizon ? (
        <div className="mt-3 space-y-3">
          <HorizonChart profile={horizon} at={centroid(roof)} />
          <p className="text-xs text-on-surface-variant">
            {fmt(horizonCoverage(horizon) * 100)}% of the compass traced. Untraced directions count as open sky.
          </p>
          <div className="flex gap-2">
            <button className={secondary} onClick={() => setScanOpen(true)}>
              Scan again
            </button>
            <button className={outlined} onClick={() => setHorizon(null)}>
              Remove scan
            </button>
          </div>
        </div>
      ) : (
        <>
          <p className="mt-1 text-sm text-on-surface-variant">
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

export function ObstructionsStep() {
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
      <p className="text-sm text-on-surface-variant">
        Outline anything that could shade the roof: taller neighbours, trees, water tanks, stair rooms.
      </p>
      <button className={secondary} disabled={detecting || mode !== "idle"} onClick={detect}>
        {detecting ? "Looking at the satellite image…" : "Find obstructions for me"}
      </button>
      {detectNote && <p className={`text-xs ${detectNote.ok ? "text-on-surface-variant" : "text-error"}`}>{detectNote.text}</p>}
      <p className="text-xs text-on-surface-variant">
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
        <button className={outlined} disabled={mode !== "idle"} onClick={() => startDrawing("obstruction")}>
          + Add one by hand
        </button>
      )}
      <SkylineScan />
    </div>
  );
}

