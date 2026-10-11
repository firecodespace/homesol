"use client";

import { useEffect, useRef } from "react";
import {
  Map as MapLibreMap,
  Marker,
  NavigationControl,
  setWorkerUrl,
  type GeoJSONSource,
  type ImageSource,
} from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { Feature, FeatureCollection } from "geojson";
import { fetchAreaPicture, type Picture } from "@/lib/api";
import { centroid, type LngLat } from "@/lib/geo/local";
import { SATELLITE_ATTRIBUTION, SATELLITE_TILES } from "@/lib/imagery";
import { completeMeasurement } from "@/lib/measure";
import { pickRoofAt } from "@/lib/pick";
import type { ShadingResult } from "@/lib/solar/shading";
import { useStore } from "@/lib/store";

// The bundler cannot resolve MapLibre's worker, so it is served from /public.
setWorkerUrl("/maplibre-gl-worker.mjs");

const CLOSE_SHAPE_PX = 14;
/** A transparent pixel parked off the map stands in until there is a photo to show. */
const BLANK_IMAGE = "data:image/gif;base64,R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw==";
const OFF_MAP: Picture["corners"] = [
  [0, 0.001],
  [0.001, 0.001],
  [0.001, 0],
  [0, 0],
];
/** Below this zoom a tap is too imprecise to mean one roof. */
const PICK_MIN_ZOOM = 16.5;
const SOURCES = ["cells", "shadows", "roof", "obstructions", "measures", "draft"] as const;
type SourceId = (typeof SOURCES)[number];

/** Whether a point sits well inside a photo, away from its edges. */
function covers(picture: Picture, [lng, lat]: LngLat): boolean {
  const [[left, top], , [right, bottom]] = picture.corners;
  const x = (lng - left) / (right - left);
  const y = (top - lat) / (top - bottom);
  return x > 0.25 && x < 0.75 && y > 0.25 && y < 0.75;
}

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
  const previewRef = useRef<() => void>(() => {});
  const pendingPicture = useRef<{ url: string; coordinates: Picture["corners"] } | null>(null);

  const { mode, draft, roof, obstructions, flyTo, showSunMap, pick, picture } = useStore();

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
      // Google's photo of the property sits above the base imagery and below everything drawn.
      map.addSource("picture", { type: "image", url: BLANK_IMAGE, coordinates: OFF_MAP });
      map.addLayer({
        id: "picture",
        type: "raster",
        source: "picture",
        layout: { visibility: pendingPicture.current ? "visible" : "none" },
        paint: { "raster-fade-duration": 0 },
      });
      if (pendingPicture.current) {
        (map.getSource("picture") as ImageSource).updateImage(pendingPicture.current);
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
          "fill-opacity": 0.6,
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
      if (s.mode === "pick") {
        if (map.getZoom() < PICK_MIN_ZOOM) {
          useStore.setState({ pick: { state: "failed", message: "Zoom in until you can see your roof clearly, then tap it." } });
        } else {
          void pickRoofAt(point);
        }
      } else if (s.mode === "roof" || s.mode === "obstruction") {
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

    // While the user is looking for their roof, swap in Google's photo of wherever they have zoomed
    // to. Google's measurements match Google's imagery, which sits a few metres off the base map,
    // so a tap has to land on this photo to pick the right building.
    let previewTimer: ReturnType<typeof setTimeout> | undefined;
    let previewRequest: AbortController | undefined;
    const schedulePreview = () => {
      clearTimeout(previewTimer);
      previewTimer = setTimeout(() => {
        const s = useStore.getState();
        if (s.mode !== "pick" || map.getZoom() < PICK_MIN_ZOOM) return;
        const { lng, lat } = map.getCenter();
        if (s.picture && covers(s.picture, [lng, lat])) return;
        previewRequest?.abort();
        previewRequest = new AbortController();
        fetchAreaPicture([lng, lat], previewRequest.signal)
          .then((picture) => {
            if (picture && useStore.getState().mode === "pick") useStore.setState({ picture });
          })
          .catch(() => {});
      }, 700);
    };
    map.on("moveend", schedulePreview);
    previewRef.current = schedulePreview;

    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") useStore.getState().cancel();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      clearTimeout(previewTimer);
      previewRequest?.abort();
      readyRef.current = false;
      map.remove();
      mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    const canvas = mapRef.current?.getCanvas();
    if (canvas) canvas.style.cursor = mode === "idle" ? "" : "crosshair";
    // Entering tap-to-find without moving the map still needs the photo for where it already is.
    if (mode === "pick") previewRef.current();
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
    // Mark where the user tapped while the roof there is being found.
    if (pick?.state === "finding") {
      features.push({ type: "Feature", properties: { first: true }, geometry: { type: "Point", coordinates: pick.point } });
    }
    setData("draft", collection(features));
  }, [draft, mode, pick]);

  useEffect(() => {
    setData("roof", collection(roof ? [polygon(roof)] : []));
  }, [roof]);

  useEffect(() => {
    const map = mapRef.current;
    const update = picture ? { url: picture.image, coordinates: picture.corners } : null;
    if (!map || !readyRef.current) {
      pendingPicture.current = update;
      return;
    }
    // With no photo the layer is hidden rather than emptied, which the renderer handles cleanly.
    if (update) (map.getSource("picture") as ImageSource).updateImage(update);
    map.setLayoutProperty("picture", "visibility", update ? "visible" : "none");
  }, [picture]);

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
    // Keep the imagery clear while the user is tracing shapes on it.
    const visible = showSunMap && mode === "idle";
    const cells = visible ? (analysis?.cells ?? []) : [];
    setData("cells", collection(cells.map((c) => polygon(c.polygon, { access: c.access }))));
  }, [analysis, showSunMap, mode]);

  useEffect(() => {
    setData("shadows", collection(shadows.map((s) => polygon(s))));
  }, [shadows]);

  return <div ref={container} className="h-full w-full" />;
}
