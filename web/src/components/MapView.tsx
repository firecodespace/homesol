"use client";

import { useEffect, useRef } from "react";
import { Map as MapLibreMap, Marker, NavigationControl, setWorkerUrl, type GeoJSONSource } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { Feature, FeatureCollection } from "geojson";
import { centroid, type LngLat } from "@/lib/geo/local";
import { SATELLITE_ATTRIBUTION, SATELLITE_TILES } from "@/lib/imagery";
import { completeMeasurement } from "@/lib/measure";
import type { ShadingResult } from "@/lib/solar/shading";
import { useStore } from "@/lib/store";

// The bundler cannot resolve MapLibre's worker, so it is served from /public.
setWorkerUrl("/maplibre-gl-worker.mjs");

const CLOSE_SHAPE_PX = 14;
const SOURCES = ["cells", "shadows", "roof", "obstructions", "measures", "draft"] as const;
type SourceId = (typeof SOURCES)[number];

const polygon = (ring: LngLat[], properties = {}): Feature => ({
  type: "Feature",
  properties,
  geometry: { type: "Polygon", coordinates: [[...ring, ring[0]]] },
});
const line = (points: LngLat[], properties = {}): Feature => ({
  type: "Feature",
  properties,
  geometry: { type: "LineString", coordinates: points },
});
const collection = (features: Feature[]): FeatureCollection => ({ type: "FeatureCollection", features });

interface Props {
  analysis: ShadingResult | null;
  shadows: LngLat[][];
}

export default function MapView({ analysis, shadows }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const readyRef = useRef(false);
  const pending = useRef<Partial<Record<SourceId, FeatureCollection>>>({});
  const markers = useRef<Marker[]>([]);

  const { mode, draft, roof, obstructions, flyTo } = useStore();

  const setData = (id: SourceId, data: FeatureCollection) => {
    const map = mapRef.current;
    if (map && readyRef.current) (map.getSource(id) as GeoJSONSource).setData(data);
    else pending.current[id] = data;
  };

  useEffect(() => {
    const map = new MapLibreMap({
      container: container.current!,
      center: [78.96, 22.6],
      zoom: 4.2,
      maxZoom: 21,
      doubleClickZoom: false,
      style: {
        version: 8,
        sources: {
          satellite: {
            type: "raster",
            tiles: [SATELLITE_TILES],
            tileSize: 256,
            maxzoom: 19,
            attribution: SATELLITE_ATTRIBUTION,
          },
        },
        layers: [{ id: "satellite", type: "raster", source: "satellite" }],
      },
    });
    mapRef.current = map;
    map.addControl(new NavigationControl({ showCompass: false }), "top-right");

    map.on("load", () => {
      for (const id of SOURCES) {
        map.addSource(id, { type: "geojson", data: pending.current[id] ?? collection([]) });
      }
      map.addLayer({
        id: "cells",
        type: "fill",
        source: "cells",
        paint: {
          "fill-color": [
            "interpolate",
            ["linear"],
            ["get", "access"],
            0, "#3b0764",
            0.5, "#c2410c",
            0.85, "#facc15",
            1, "#fef9c3",
          ],
          "fill-opacity": 0.78,
        },
      });
      map.addLayer({
        id: "shadows",
        type: "fill",
        source: "shadows",
        paint: { "fill-color": "#020617", "fill-opacity": 0.5 },
      });
      map.addLayer({
        id: "roof-fill",
        type: "fill",
        source: "roof",
        paint: { "fill-color": "#facc15", "fill-opacity": 0.12 },
      });
      map.addLayer({
        id: "roof-line",
        type: "line",
        source: "roof",
        paint: { "line-color": "#facc15", "line-width": 2.5 },
      });
      map.addLayer({
        id: "obstructions-fill",
        type: "fill",
        source: "obstructions",
        paint: { "fill-color": "#f43f5e", "fill-opacity": 0.3 },
      });
      map.addLayer({
        id: "obstructions-line",
        type: "line",
        source: "obstructions",
        paint: { "line-color": "#fb7185", "line-width": 2 },
      });
      map.addLayer({
        id: "measures",
        type: "line",
        source: "measures",
        paint: { "line-color": "#38bdf8", "line-width": 3, "line-dasharray": [1.5, 1] },
      });
      map.addLayer({
        id: "draft-line",
        type: "line",
        source: "draft",
        filter: ["==", ["geometry-type"], "LineString"],
        paint: { "line-color": "#ffffff", "line-width": 2, "line-dasharray": [2, 1.5] },
      });
      map.addLayer({
        id: "draft-points",
        type: "circle",
        source: "draft",
        filter: ["==", ["geometry-type"], "Point"],
        paint: {
          "circle-radius": ["case", ["get", "first"], 7, 5],
          "circle-color": ["case", ["get", "first"], "#facc15", "#ffffff"],
          "circle-stroke-color": "#0f172a",
          "circle-stroke-width": 2,
        },
      });
      readyRef.current = true;
    });

    map.on("click", (e) => {
      const s = useStore.getState();
      const point: LngLat = [e.lngLat.lng, e.lngLat.lat];
      if (s.mode === "roof" || s.mode === "obstruction") {
        if (s.draft.length >= 3) {
          const first = map.project(s.draft[0]);
          if (Math.hypot(first.x - e.point.x, first.y - e.point.y) < CLOSE_SHAPE_PX) {
            s.finishDrawing();
            return;
          }
        }
        s.addDraftPoint(point);
      } else if (s.mode === "measure") {
        if (s.draft.length === 0) s.addDraftPoint(point);
        else void completeMeasurement(s.draft[0], point);
      }
    });

    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") useStore.getState().cancel();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      readyRef.current = false;
      map.remove();
      mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    const canvas = mapRef.current?.getCanvas();
    if (canvas) canvas.style.cursor = mode === "idle" ? "" : "crosshair";
  }, [mode]);

  useEffect(() => {
    if (!flyTo) return;
    mapRef.current?.flyTo({ center: flyTo, zoom: 18, duration: 1800 });
    useStore.getState().requestFlyTo(null);
  }, [flyTo]);

  useEffect(() => {
    const features: Feature[] = draft.map((p, i) => ({
      type: "Feature",
      properties: { first: i === 0 && mode !== "measure" },
      geometry: { type: "Point", coordinates: p },
    }));
    if (draft.length >= 2) features.push(line(draft));
    setData("draft", collection(features));
  }, [draft, mode]);

  useEffect(() => {
    setData("roof", collection(roof ? [polygon(roof)] : []));
  }, [roof]);

  useEffect(() => {
    setData("obstructions", collection(obstructions.map((o) => polygon(o.footprint))));
    setData(
      "measures",
      collection(obstructions.flatMap((o) => (o.measurement ? [line([o.measurement.base, o.measurement.tip])] : []))),
    );

    const map = mapRef.current;
    markers.current.forEach((m) => m.remove());
    markers.current = [];
    if (!map) return;
    obstructions.forEach((o, i) => {
      const el = document.createElement("div");
      el.className = "obstruction-badge";
      el.textContent = String(i + 1);
      markers.current.push(new Marker({ element: el }).setLngLat(centroid(o.footprint)).addTo(map));
    });
  }, [obstructions]);

  useEffect(() => {
    setData("cells", collection(analysis?.cells.map((c) => polygon(c.polygon, { access: c.access })) ?? []));
  }, [analysis]);

  useEffect(() => {
    setData("shadows", collection(shadows.map((s) => polygon(s))));
  }, [shadows]);

  return <div ref={container} className="h-full w-full" />;
}
