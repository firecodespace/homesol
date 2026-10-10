"use client";

import { useMemo } from "react";
import dynamic from "next/dynamic";
import { centroid } from "@/lib/geo/local";
import { analyseShading, shadowOutlines, type ShadingObstruction } from "@/lib/solar/shading";
import { istDate, sunAt } from "@/lib/solar/sun";
import { FLOOR_HEIGHT_M, useStore } from "@/lib/store";
import Sidebar from "./Sidebar";

const MapView = dynamic(() => import("./MapView"), { ssr: false });

export default function Planner() {
  const roof = useStore((s) => s.roof);
  const floors = useStore((s) => s.floors);
  const obstructions = useStore((s) => s.obstructions);
  const preview = useStore((s) => s.preview);

  const roofHeightM = floors * FLOOR_HEIGHT_M;
  const measured = useMemo(
    () =>
      obstructions.flatMap((o): ShadingObstruction[] =>
        o.heightM ? [{ footprint: o.footprint, heightM: o.heightM, reference: o.reference }] : [],
      ),
    [obstructions],
  );

  const analysis = useMemo(
    () => (roof ? analyseShading(roof, roofHeightM, measured) : null),
    [roof, roofHeightM, measured],
  );

  const sun = useMemo(
    () => (roof ? sunAt(istDate(2026, preview.month, 21, 0, preview.minutes), centroid(roof)) : null),
    [roof, preview],
  );
  const shadows = useMemo(
    () => (sun ? shadowOutlines(measured, roofHeightM, sun) : []),
    [sun, measured, roofHeightM],
  );

  return (
    <div className="flex h-dvh flex-col-reverse md:flex-row">
      <Sidebar analysis={analysis} sun={sun} />
      <main className="relative min-h-0 flex-1">
        <MapView analysis={analysis} shadows={shadows} />
      </main>
    </div>
  );
}
