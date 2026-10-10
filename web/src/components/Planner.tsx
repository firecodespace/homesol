"use client";

import { useEffect, useMemo } from "react";
import dynamic from "next/dynamic";
import { centroid } from "@/lib/geo/local";
import { sunBlockedByHorizon } from "@/lib/solar/horizon";
import { analyseShading, shadowOutlines, type ShadingObstruction } from "@/lib/solar/shading";
import { istDate, sunAt } from "@/lib/solar/sun";
import { FLOOR_HEIGHT_M, useStore } from "@/lib/store";
import HorizonScan from "./HorizonScan";
import Sidebar from "./Sidebar";

const MapView = dynamic(() => import("./MapView"), { ssr: false });

export default function Planner() {
  const roof = useStore((s) => s.roof);
  const floors = useStore((s) => s.floors);
  const obstructions = useStore((s) => s.obstructions);
  const preview = useStore((s) => s.preview);
  const horizon = useStore((s) => s.horizon);
  const scanOpen = useStore((s) => s.scanOpen);

  useEffect(() => {
    // Restore a saved survey and bring its roof back into view.
    void Promise.resolve(useStore.persist.rehydrate()).then(() => {
      const saved = useStore.getState().roof;
      if (saved) useStore.getState().requestFlyTo(centroid(saved));
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

  const analysis = useMemo(
    () => (roof ? analyseShading(roof, roofHeightM, measured, horizon) : null),
    [roof, roofHeightM, measured, horizon],
  );

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

  return (
    <div className="flex h-dvh flex-col-reverse md:flex-row">
      <Sidebar analysis={analysis} sun={sun} />
      <main className="relative min-h-0 flex-1">
        <MapView analysis={analysis} shadows={shadows} />
      </main>
      {scanOpen && roofCentre && <HorizonScan at={roofCentre} />}
    </div>
  );
}
