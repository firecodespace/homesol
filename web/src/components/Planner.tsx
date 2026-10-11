"use client";

import { useEffect, useMemo } from "react";
import dynamic from "next/dynamic";
import { fetchSite, loadSurvey } from "@/lib/api";
import { centroid } from "@/lib/geo/local";
import { analyse } from "@/lib/site/analysis";
import { decodeSite, modelFromCells } from "@/lib/site/model";
import { nameObstructions } from "@/lib/site/naming";
import { analyseShading, shadowOutlines, type ShadingObstruction } from "@/lib/solar/shading";
import { sunAt } from "@/lib/solar/sun";
import { FLOOR_HEIGHT_M, useStore } from "@/lib/store";
import { zonedDate, zoneAt } from "@/lib/time";
import { useMoney } from "@/lib/useMoney";
import HorizonScan from "./HorizonScan";
import MapControls from "./MapControls";
import ResultsPanel from "./ResultsPanel";
import ToolsPanel from "./ToolsPanel";

const MapView = dynamic(() => import("./MapView"), { ssr: false });

export default function Planner() {
  const hydrated = useStore((s) => s.hydrated);
  const roof = useStore((s) => s.roof);
  const site = useStore((s) => s.site);
  const siteStatus = useStore((s) => s.siteStatus);
  const floors = useStore((s) => s.floors);
  const obstructions = useStore((s) => s.obstructions);
  const preview = useStore((s) => s.preview);
  const horizon = useStore((s) => s.horizon);
  const scanOpen = useStore((s) => s.scanOpen);

  useEffect(() => {
    // Open a shared survey from its link, or else restore this device's last one.
    const code = new URLSearchParams(window.location.search).get("s");
    void Promise.resolve(useStore.persist.rehydrate()).then(async () => {
      if (code) {
        try {
          const { survey } = await loadSurvey(code);
          // A shared survey is its own property: nothing from this device's last one carries over.
          useStore.getState().clearRoof();
          useStore.setState(survey);
        } catch {
          // Fall back to whatever this device already has.
        }
      }
      useStore.setState({ hydrated: true });
      const saved = useStore.getState().roof;
      if (saved) useStore.getState().requestFlyTo(centroid(saved));
    });
  }, []);

  // An outline drawn by hand, or restored from a save, has no measured model yet: fetch one.
  useEffect(() => {
    if (!hydrated || !roof) return;
    if (useStore.getState().site?.outline === roof) return;
    const controller = new AbortController();
    useStore.setState({ site: null, names: {}, siteStatus: { state: "loading" } });
    fetchSite({ outline: roof }, controller.signal)
      .then(async (found) => {
        if (!found.available || !found.found) {
          const reason = found.available ? "Google's survey has no usable surface here." : found.reason;
          useStore.setState({ siteStatus: { state: "unavailable", reason } });
          return;
        }
        const model = await decodeSite(found);
        if (controller.signal.aborted) return;
        useStore.setState({
          site: { ...model, outline: roof },
          siteStatus: { state: "idle" },
          floors: Math.max(1, model.surface.floors),
        });
      })
      .catch((err: Error) => {
        if (err.name === "AbortError") return;
        useStore.setState({ siteStatus: { state: "unavailable", reason: "The measuring service could not be reached." } });
      });
    return () => controller.abort();
  }, [hydrated, roof]);

  // Show Google's photo of the property under everything drawn on it.
  useEffect(() => {
    if (site?.photo) useStore.setState({ picture: { image: site.photo, corners: site.corners } });
  }, [site]);

  // Where Google has no survey, estimate shade from what the user marks by hand.
  const roofHeightM = floors * FLOOR_HEIGHT_M;
  const marked = useMemo(
    () =>
      obstructions.flatMap((o): ShadingObstruction[] =>
        o.heightM ? [{ footprint: o.footprint, heightM: o.heightM, reference: o.reference }] : [],
      ),
    [obstructions],
  );
  const estimated = siteStatus.state === "unavailable";
  const estimate = useMemo(
    () => (roof && estimated ? analyseShading(roof, roofHeightM, marked, horizon) : null),
    [roof, estimated, roofHeightM, marked, horizon],
  );
  const model = useMemo(
    () => site ?? (roof && estimate ? modelFromCells(roof, estimate.cells, estimate.cellSizeM, roofHeightM) : null),
    [site, roof, estimate, roofHeightM],
  );
  const analysis = useMemo(() => (model ? analyse(model) : null), [model]);

  // Once the measured model is analysed, have the vision model say what each obstruction is.
  useEffect(() => {
    if (!analysis?.model.measured || !analysis.shade) return;
    const model = analysis.model;
    let current = true;
    nameObstructions(model, analysis.shade.blame)
      .then((names) => {
        if (current && useStore.getState().site === model) useStore.setState({ names });
      })
      .catch(() => {});
    return () => {
      current = false;
    };
  }, [analysis]);

  const centre = useMemo(() => (roof ? centroid(roof) : null), [roof]);
  const zone = useMemo(() => (centre ? zoneAt(centre) : "UTC"), [centre]);
  const sun = useMemo(
    () => (centre ? sunAt(zonedDate(zone, 2026, preview.month, 21, preview.minutes), centre) : null),
    [centre, zone, preview],
  );
  const markedShadows = useMemo(
    () => (sun && roof && estimated ? shadowOutlines(marked, roofHeightM, sun) : []),
    [sun, roof, estimated, marked, roofHeightM],
  );

  const money = useMoney(analysis);

  return (
    <div className="flex min-h-dvh flex-col lg:h-dvh">
      <header className="flex h-14 shrink-0 items-center gap-4 border-b border-outline-variant bg-surface-container px-4">
        <h1 className="text-[22px] leading-7 text-on-surface">
          home<span className="font-medium text-primary">sol</span>
        </h1>
        <p className="md-body hidden sm:block">Everything you need to decide on solar, for your own property.</p>
      </header>
      {/* Tools on the left, map in the middle, results on the right. On small screens they stack. */}
      <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
        <ToolsPanel analysis={analysis} money={money} />
        <main className="relative order-first h-[55dvh] min-h-0 shrink-0 lg:order-none lg:h-auto lg:flex-1">
          <MapView analysis={analysis} chosen={money.sizing?.panels ?? 0} sun={sun} markedShadows={markedShadows} />
          <MapControls analysis={analysis} sun={sun} zone={zone} />
        </main>
        <ResultsPanel analysis={analysis} money={money} zone={zone} />
      </div>
      {scanOpen && centre && <HorizonScan at={centre} />}
    </div>
  );
}
