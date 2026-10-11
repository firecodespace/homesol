"use client";

import { useEffect, useRef, useState } from "react";
import type { Analysis } from "@/lib/site/analysis";
import type { SunPosition } from "@/lib/solar/sun";
import { useStore, type MapView } from "@/lib/store";
import { Icon } from "./ui";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const VIEWS: { id: MapView; label: string; icon: string }[] = [
  { id: "sun", label: "Year's sun", icon: "wb_sunny" },
  { id: "shadows", label: "Shadows", icon: "schedule" },
  { id: "photo", label: "Photo", icon: "image" },
];
const clock = (minutes: number) =>
  `${String(Math.floor(minutes / 60)).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}`;

/** What is drawn on the map, and for the shadow view, the moment it shows. */
export default function MapControls({ analysis, sun, zone }: { analysis: Analysis | null; sun: SunPosition | null; zone: string }) {
  const { mode, view, showPanels, showObstructions, preview, setPreview } = useStore();
  const [playing, setPlaying] = useState(false);
  const minutes = useRef(preview.minutes);
  useEffect(() => {
    minutes.current = preview.minutes;
  }, [preview.minutes]);
  useEffect(() => {
    if (!playing || view !== "shadows") return;
    const timer = setInterval(() => {
      const next = minutes.current + 10;
      setPreview({ minutes: next > 19 * 60 + 30 ? 5 * 60 : next });
    }, 90);
    return () => clearInterval(timer);
  }, [playing, view, setPreview]);

  if (!analysis || mode !== "idle") return null;
  const measured = analysis.model.measured;

  return (
    <>
      <div className="pointer-events-none absolute left-3 top-3 right-3 flex flex-wrap items-start gap-2">
        <div className="pointer-events-auto flex overflow-hidden rounded-full border border-outline bg-surface shadow-level1" role="group" aria-label="What the map shows">
          {VIEWS.map((v) => (
            <button
              key={v.id}
              className={`flex h-10 items-center gap-1.5 border-r border-outline px-4 text-sm font-medium last:border-r-0 ${
                view === v.id ? "bg-secondary-container text-on-secondary-container" : "text-on-surface hover:bg-on-surface/8"
              }`}
              aria-pressed={view === v.id}
              onClick={() => useStore.setState({ view: v.id })}
            >
              <Icon name={view === v.id ? "check" : v.icon} className="text-[18px]" />
              {v.label}
            </button>
          ))}
        </div>
        <button
          className={`pointer-events-auto md-chip bg-surface shadow-level1 ${showPanels ? "border-transparent bg-secondary-container text-on-secondary-container" : ""}`}
          aria-pressed={showPanels}
          onClick={() => useStore.setState({ showPanels: !showPanels })}
        >
          <Icon name={showPanels ? "check" : "solar_power"} className="mr-1.5 text-[18px]" />
          Panels
        </button>
        {measured && (
          <button
            className={`pointer-events-auto md-chip bg-surface shadow-level1 ${showObstructions ? "border-transparent bg-secondary-container text-on-secondary-container" : ""}`}
            aria-pressed={showObstructions}
            onClick={() => useStore.setState({ showObstructions: !showObstructions })}
          >
            <Icon name={showObstructions ? "check" : "domain"} className="mr-1.5 text-[18px]" />
            What casts shade
          </button>
        )}
      </div>

      {view === "shadows" && (
        <div className="absolute bottom-3 left-3 right-14 mx-auto max-w-xl rounded-lg bg-surface p-3 shadow-level2">
          <div className="flex items-center gap-3">
            <button
              className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-primary text-on-primary"
              aria-label={playing ? "Pause" : "Play the day"}
              onClick={() => setPlaying(!playing)}
            >
              <Icon name={playing ? "pause" : "play_arrow"} />
            </button>
            <div className="min-w-0 flex-1">
              <div className="flex items-baseline justify-between gap-2">
                <p className="text-sm font-medium text-on-surface">
                  {clock(preview.minutes)} on 21 {MONTHS[preview.month - 1]}
                </p>
                <p className="md-supporting truncate">
                  {sun && sun.elevation > 0 ? `Sun ${Math.round(sun.elevation)}° above the horizon` : "Before sunrise or after sunset"}
                </p>
              </div>
              <input
                type="range"
                aria-label="Time of day"
                min={5 * 60}
                max={19 * 60 + 30}
                step={10}
                value={preview.minutes}
                onChange={(e) => setPreview({ minutes: Number(e.target.value) })}
                className="mt-1 w-full accent-primary"
              />
            </div>
            <select
              aria-label="Month"
              value={preview.month}
              onChange={(e) => setPreview({ month: Number(e.target.value) })}
              className="md-field-dense w-20 shrink-0"
            >
              {MONTHS.map((m, i) => (
                <option key={m} value={i + 1}>
                  {m}
                </option>
              ))}
            </select>
          </div>
          <p className="md-supporting mt-2">
            {measured
              ? `Shadows are cast from the measured heights of everything in view. Times are local (${zone.replace("_", " ")}).`
              : "Shadows of the obstructions you marked. Mark more under “Improve the shade estimate”."}
          </p>
        </div>
      )}
    </>
  );
}
