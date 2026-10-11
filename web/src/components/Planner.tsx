"use client";

import { useEffect, useMemo, useState } from "react";
import dynamic from "next/dynamic";
import { fetchMeasuredSun, loadSurvey, type MeasuredSun } from "@/lib/api";
import { centroid } from "@/lib/geo/local";
import { sunBlockedByHorizon } from "@/lib/solar/horizon";
import { analyseShading, shadowOutlines, summariseCells, type ShadingObstruction } from "@/lib/solar/shading";
import { istDate, sunAt } from "@/lib/solar/sun";
import { FLOOR_HEIGHT_M, useStore } from "@/lib/store";
import { useMoney } from "@/lib/useMoney";
import HorizonScan from "./HorizonScan";
import ResultsPanel from "./ResultsPanel";
import ToolsPanel from "./ToolsPanel";

const MapView = dynamic(() => import("./MapView"), { ssr: false });

export default function Planner() {
  const roof = useStore((s) => s.roof);
  const floors = useStore((s) => s.floors);
  const obstructions = useStore((s) => s.obstructions);
  const preview = useStore((s) => s.preview);
  const horizon = useStore((s) => s.horizon);
  const scanOpen = useStore((s) => s.scanOpen);

  useEffect(() => {
    // Open a shared survey from its link, or else restore this device's last one.
    const code = new URLSearchParams(window.location.search).get("s");
    const showRoof = () => {
      const saved = useStore.getState().roof;
      if (saved) useStore.getState().requestFlyTo(centroid(saved));
    };
    void Promise.resolve(useStore.persist.rehydrate()).then(async () => {
      if (code) {
        try {
          useStore.setState((await loadSurvey(code)).survey);
        } catch {
          // Fall back to whatever this device already has.
        }
      }
      useStore.setState({ hydrated: true });
      showRoof();
    });
  }, []);

  const roofCentre = useMemo(() => (roof ? centroid(roof) : null), [roof]);

  const roofHeightM = floors * FLOOR_HEIGHT_M;
  const measured = useMemo(
    () =>
      obstructions.flatMap((o): ShadingObstruction[] =>
        o.heightM ? [{ footprint: o.footprint, heightM: o.heightM, reference: o.reference }] : [],
      ),
    [obstructions],
  );

  // Where Google has surveyed the roof in 3D, its measured sun map replaces the hand-marked estimate.
  const [measuredSun, setMeasuredSun] = useState<{ roof: typeof roof; result: MeasuredSun } | null>(null);
  useEffect(() => {
    if (!roof) return;
    const controller = new AbortController();
    fetchMeasuredSun(roof, controller.signal)
      .then((result) => {
        setMeasuredSun({ roof, result });
        if (result.available && result.floors) useStore.getState().setFloors(result.floors);
        // Keep the wider neighbourhood photo if it already shows this roof; otherwise use this one.
        const shown = useStore.getState().picture;
        const [lng, lat] = centroid(roof);
        const inShown =
          shown && lng > shown.corners[0][0] && lng < shown.corners[2][0] && lat < shown.corners[0][1] && lat > shown.corners[2][1];
        if (result.available && result.picture && !inShown) useStore.setState({ picture: result.picture });
      })
      .catch(() => {});
    return () => controller.abort();
  }, [roof]);
  const google = measuredSun && measuredSun.roof === roof ? measuredSun.result : null;

  const analysis = useMemo(() => {
    if (!roof) return null;
    if (google?.available) {
      return summariseCells(google.cells, google.cell_size_m, google.surface_area_m2);
    }
    return analyseShading(roof, roofHeightM, measured, horizon);
  }, [roof, roofHeightM, measured, horizon, google]);

  const sun = useMemo(
    () => (roofCentre ? sunAt(istDate(2026, preview.month, 21, 0, preview.minutes), roofCentre) : null),
    [roofCentre, preview],
  );
  const shadows = useMemo(() => {
    if (!sun || !roof) return [];
    // Below the scanned skyline the whole roof is in shade.
    if (sun.elevation > 0 && sunBlockedByHorizon(horizon, sun)) return [roof];
    return shadowOutlines(measured, roofHeightM, sun);
  }, [sun, roof, horizon, measured, roofHeightM]);

  const money = useMoney(analysis);

  return (
    <div className="flex min-h-dvh flex-col lg:h-dvh">
      <header className="flex h-16 shrink-0 items-center gap-4 border-b border-outline-variant bg-surface-container px-4">
        <h1 className="md-title-large">
          home<span className="text-primary">sol</span>
        </h1>
        <p className="md-body hidden sm:block">Find out what rooftop solar would do for your home.</p>
      </header>
      {/* Tools on the left, map in the middle, results on the right. On small screens they stack. */}
      <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
        <ToolsPanel analysis={analysis} sun={sun} google={google} money={money} />
        <main className="relative order-first h-[50dvh] min-h-0 shrink-0 lg:order-none lg:h-auto lg:flex-1">
          <MapView analysis={analysis} shadows={shadows} />
        </main>
        <ResultsPanel analysis={analysis} google={google} money={money} />
      </div>
      {scanOpen && roofCentre && <HorizonScan at={roofCentre} />}
    </div>
  );
}
