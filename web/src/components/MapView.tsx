"use client";

import { useEffect, useRef } from "react";
import {
  Map as MapLibreMap,
  Marker,
  NavigationControl,
  Popup,
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
import type { Analysis } from "@/lib/site/analysis";
import { gridToLngLat, type SiteModel, type SiteObstruction } from "@/lib/site/model";
import type { ObstructionName } from "@/lib/site/naming";
import { GOOD_ACCESS } from "@/lib/site/panels";
import { castShadows } from "@/lib/site/shadows";
import type { SunPosition } from "@/lib/solar/sun";
import { useStore } from "@/lib/store";

// The bundler cannot resolve MapLibre's worker, so it is served from /public.
setWorkerUrl("/maplibre-gl-worker.mjs");

const CLOSE_SHAPE_PX = 14;
/** A transparent pixel parked off the map stands in until there is an image to show. */
const BLANK_IMAGE = "data:image/gif;base64,R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw==";
const OFF_MAP: Picture["corners"] = [
  [0, 0.001],
  [0.001, 0.001],
  [0.001, 0],
  [0, 0],
];
/** Below this zoom a tap is too imprecise to mean one roof. */
const PICK_MIN_ZOOM = 16.5;
const IMAGES = ["picture", "sunmap", "shade"] as const;
const SHAPES = ["castShadows", "roof", "neighbours", "marked", "panels", "measures", "draft"] as const;
type ImageId = (typeof IMAGES)[number];
type ShapeId = (typeof SHAPES)[number];

/** Colours of the sun map, from deep shade to full sun. The legend in the results panel matches. */
const SUN_RAMP: [number, [number, number, number]][] = [
  [0, [59, 7, 100]],
  [0.5, [194, 65, 12]],
  [0.85, [250, 204, 21]],
  [1, [254, 249, 195]],
];
const OBSTRUCTION_COLOURS: Record<string, string> = {
  building: "#2563eb",
  surroundings: "#2563eb",
  tree: "#16a34a",
};
const ON_SURFACE_COLOUR = "#dc2626";

/** What an obstruction of each kind means for the panels, in a line. */
const KIND_NOTES: Record<string, string> = {
  tank: "Panels are kept clear of it and out of the worst of its shadow.",
  room: "It shades the part of the surface behind it, most in the morning or evening.",
  structure: "Panels are placed around it.",
  wall: "Low, so it only shades the strip right beside it.",
  upper_level: "A taller part of the same building. Panels on it would need their own survey.",
  building: "A taller neighbour. It blocks the sun when the sun is low on that side.",
  surroundings: "Taller buildings or trees on that side block low sun.",
  tree: "Trees grow, so its shade may increase over the years.",
};

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
const escape = (text: string) =>
  text.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]!);

function sunColour(access: number): [number, number, number] {
  for (let i = 1; i < SUN_RAMP.length; i++) {
    const [stop, colour] = SUN_RAMP[i];
    if (access <= stop) {
      const [from, low] = SUN_RAMP[i - 1];
      const t = (access - from) / (stop - from);
      return [0, 1, 2].map((k) => low[k] + (colour[k] - low[k]) * t) as [number, number, number];
    }
  }
  return SUN_RAMP[SUN_RAMP.length - 1][1];
}

/** The year's sun over the surface as a picture, one pixel per grid cell. */
function drawSunMap(model: SiteModel): string {
  const canvas = document.createElement("canvas");
  canvas.width = model.cols;
  canvas.height = model.rows;
  const ctx = canvas.getContext("2d")!;
  const image = ctx.createImageData(model.cols, model.rows);
  for (let i = 0; i < model.labels.length; i++) {
    if (model.labels[i] !== 1 || !Number.isFinite(model.access[i])) continue;
    const [r, g, b] = sunColour(model.access[i]);
    image.data.set([r, g, b, 215], i * 4);
  }
  ctx.putImageData(image, 0, 0);
  return canvas.toDataURL();
}

function describeObstruction(
  o: SiteObstruction,
  blame: number | undefined,
  surface: string,
  named: ObstructionName | undefined,
): string {
  const where = o.on_surface
    ? `On your ${surface}`
    : `${o.distance_m < 1 ? "Right beside it" : `${Math.round(o.distance_m)} m away`}, to the ${o.direction}`;
  const share =
    blame === undefined
      ? ""
      : blame >= 0.01
        ? `<p>Causes about <strong>${Math.round(blame * 100)}%</strong> of the shade on your ${surface}.</p>`
        : `<p>Casts little or no shade on your ${surface}.</p>`;
  return (
    `<p class="tip-title">${escape(named?.name ?? o.name)}</p>` +
    `<p>${where} · stands ${o.height_above_m} m above it</p>` +
    share +
    `<p class="tip-note">${escape(named?.what ?? KIND_NOTES[o.kind] ?? "")}</p>`
  );
}

interface Props {
  analysis: Analysis | null;
  /** How many of the laid-out panels the recommended system uses, sunniest first. */
  chosen: number;
  sun: SunPosition | null;
  /** Shadow outlines of hand-marked obstructions, for places with no measured model. */
  markedShadows: LngLat[][];
}

export default function MapView({ analysis, chosen, sun, markedShadows }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const readyRef = useRef(false);
  const pendingShapes = useRef<Partial<Record<ShapeId, FeatureCollection>>>({});
  const pendingImages = useRef<Partial<Record<ImageId, { url: string; coordinates: Picture["corners"] } | null>>>({});
  const markers = useRef<Marker[]>([]);
  const previewRef = useRef<() => void>(() => {});
  const shadeCanvas = useRef<HTMLCanvasElement | null>(null);

  const { mode, draft, roof, obstructions, flyTo, pick, picture, view, showPanels, showObstructions, names } = useStore();
  const model = analysis?.model ?? null;

  const setShapes = (id: ShapeId, data: FeatureCollection) => {
    const map = mapRef.current;
    if (map && readyRef.current) (map.getSource(id) as GeoJSONSource).setData(data);
    else pendingShapes.current[id] = data;
  };
  // With nothing to show the layer is hidden rather than emptied, which the renderer handles cleanly.
  const setImage = (id: ImageId, image: { url: string; coordinates: Picture["corners"] } | null) => {
    const map = mapRef.current;
    if (!map || !readyRef.current) {
      pendingImages.current[id] = image;
      return;
    }
    if (image) (map.getSource(id) as ImageSource).updateImage(image);
    map.setLayoutProperty(id, "visibility", image ? "visible" : "none");
  };

  useEffect(() => {
    const map = new MapLibreMap({
      container: container.current!,
      center: [78.96, 22.6],
      zoom: 4.2,
      maxZoom: 21.5,
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
    map.addControl(new NavigationControl({ showCompass: false }), "bottom-right");
    const tip = new Popup({ closeButton: false, closeOnClick: false, offset: 12, maxWidth: "280px", className: "map-tip" });

    map.on("load", () => {
      // Google's photo sits above the base imagery; the sun map and the shadows sit on the photo.
      for (const id of IMAGES) {
        const image = pendingImages.current[id];
        map.addSource(id, { type: "image", url: image?.url ?? BLANK_IMAGE, coordinates: image?.coordinates ?? OFF_MAP });
        map.addLayer({
          id,
          type: "raster",
          source: id,
          layout: { visibility: image ? "visible" : "none" },
          paint: { "raster-fade-duration": 0, "raster-resampling": id === "picture" ? "linear" : "nearest" },
        });
      }
      for (const id of SHAPES) {
        map.addSource(id, { type: "geojson", data: pendingShapes.current[id] ?? collection([]) });
      }
      map.addLayer({
        id: "castShadows",
        type: "fill",
        source: "castShadows",
        paint: { "fill-color": "#020617", "fill-opacity": 0.5 },
      });
      map.addLayer({
        id: "neighbours-fill",
        type: "fill",
        source: "neighbours",
        // What stands on the surface is filled strongly; neighbours are tinted lightly, since on open
        // land in a town they can cover most of the view.
        paint: { "fill-color": ["get", "colour"], "fill-opacity": ["case", ["get", "onSurface"], 0.35, ["get", "minor"], 0.05, 0.16] },
      });
      map.addLayer({
        id: "neighbours-line",
        type: "line",
        source: "neighbours",
        paint: { "line-color": ["get", "colour"], "line-width": ["case", ["get", "minor"], 1, 2] },
      });
      map.addLayer({
        id: "marked-fill",
        type: "fill",
        source: "marked",
        paint: { "fill-color": ON_SURFACE_COLOUR, "fill-opacity": 0.3 },
      });
      map.addLayer({
        id: "marked-line",
        type: "line",
        source: "marked",
        paint: { "line-color": ON_SURFACE_COLOUR, "line-width": 2 },
      });
      map.addLayer({ id: "roof-line", type: "line", source: "roof", paint: { "line-color": "#ffffff", "line-width": 2.5 } });
      map.addLayer({
        id: "panels-fill",
        type: "fill",
        source: "panels",
        paint: { "fill-color": "#0b2a6f", "fill-opacity": ["case", ["get", "chosen"], 0.92, 0.18] },
      });
      map.addLayer({
        id: "panels-line",
        type: "line",
        source: "panels",
        paint: {
          "line-color": ["case", ["get", "chosen"], "#e0ecff", "#ffffff"],
          "line-width": ["case", ["get", "chosen"], 1.2, 0.8],
        },
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

      // Explain whatever is under the pointer.
      for (const layer of ["neighbours-fill", "panels-fill"]) {
        map.on("mousemove", layer, (e) => {
          if (useStore.getState().mode !== "idle") return;
          const html = e.features?.[0]?.properties?.tip;
          if (html) tip.setLngLat(e.lngLat).setHTML(html).addTo(map);
          map.getCanvas().style.cursor = "help";
        });
        map.on("mouseleave", layer, () => {
          tip.remove();
          if (useStore.getState().mode === "idle") map.getCanvas().style.cursor = "";
        });
      }
      readyRef.current = true;
    });

    map.on("click", (e) => {
      const s = useStore.getState();
      const point: LngLat = [e.lngLat.lng, e.lngLat.lat];
      if (s.mode === "pick") {
        if (map.getZoom() < PICK_MIN_ZOOM) {
          useStore.setState({
            pick: { state: "failed", message: "Zoom in until you can see your roof clearly, then tap it." },
          });
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
      } else if (readyRef.current) {
        // A tap explains what is under it, for touch screens where nothing can hover.
        const html = map.queryRenderedFeatures(e.point, { layers: ["panels-fill", "neighbours-fill"] })[0]?.properties?.tip;
        if (html) tip.setLngLat(e.lngLat).setHTML(html).addTo(map);
        else tip.remove();
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
          .then((found) => {
            if (found && useStore.getState().mode === "pick") useStore.setState({ picture: found });
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
    mapRef.current?.flyTo({ center: flyTo, zoom: 19, duration: 1800 });
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
    setShapes("draft", collection(features));
  }, [draft, mode, pick]);

  useEffect(() => {
    setShapes("roof", collection(roof ? [polygon(roof)] : []));
  }, [roof]);

  useEffect(() => {
    setImage("picture", picture ? { url: picture.image, coordinates: picture.corners } : null);
  }, [picture]);

  // The year's sun, painted on the surface.
  useEffect(() => {
    const drawing = mode !== "idle";
    setImage("sunmap", model && view === "sun" && !drawing ? { url: drawSunMap(model), coordinates: model.corners } : null);
  }, [model, view, mode]);

  // Shadows at the chosen moment, cast from the height data across the whole neighbourhood.
  useEffect(() => {
    const grid = analysis?.grid;
    if (!model || !grid || !sun || view !== "shadows") {
      setImage("shade", null);
      return;
    }
    const canvas = (shadeCanvas.current ??= document.createElement("canvas"));
    canvas.width = grid.cols;
    canvas.height = grid.rows;
    const ctx = canvas.getContext("2d")!;
    const shaded = new Uint8Array(grid.rows * grid.cols);
    castShadows(grid, sun.azimuth - model.northDeg, sun.elevation, shaded);
    const image = ctx.createImageData(grid.cols, grid.rows);
    for (let i = 0; i < shaded.length; i++) if (shaded[i]) image.data.set([6, 10, 36, 130], i * 4);
    ctx.putImageData(image, 0, 0);
    const right = grid.cols * grid.scale;
    const bottom = grid.rows * grid.scale;
    setImage("shade", {
      url: canvas.toDataURL(),
      coordinates: [
        gridToLngLat(model, 0, 0),
        gridToLngLat(model, right, 0),
        gridToLngLat(model, right, bottom),
        gridToLngLat(model, 0, bottom),
      ],
    });
  }, [analysis, model, sun, view]);

  // For places with no measured model, the outlines of shadows from hand-marked obstructions.
  useEffect(() => {
    const outlines = view === "shadows" && !analysis?.grid ? markedShadows : [];
    setShapes("castShadows", collection(outlines.map((s) => polygon(s))));
  }, [markedShadows, view, analysis]);

  // Measured obstructions, each explained on hover.
  useEffect(() => {
    if (!model?.measured || !showObstructions) {
      setShapes("neighbours", collection([]));
      return;
    }
    const surface = model.surface.kind.includes("ground") ? "land" : "roof";
    const blame = analysis?.shade?.blame;
    setShapes(
      "neighbours",
      collection(
        model.obstructions
          // Neighbours that cast no meaningful shade would only clutter the map.
          .filter((o) => o.on_surface || !blame || (blame.get(o.id) ?? 0) >= 0.01)
          .map((o) =>
            polygon(o.outline, {
              colour: o.on_surface ? ON_SURFACE_COLOUR : (OBSTRUCTION_COLOURS[o.kind] ?? "#2563eb"),
              onSurface: o.on_surface,
              minor: !o.on_surface && blame ? (blame.get(o.id) ?? 0) < 0.05 : false,
              tip: describeObstruction(o, blame?.get(o.id), surface, names[o.id]),
            }),
          ),
      ),
    );
  }, [model, analysis, showObstructions, names]);

  // Obstructions marked by hand, with their numbers and any shadow measurements.
  useEffect(() => {
    setShapes("marked", collection(obstructions.map((o) => polygon(o.footprint))));
    setShapes(
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

  // Every place a panel fits with good sun; the ones in the plan are solid.
  useEffect(() => {
    if (!analysis || !showPanels || mode !== "idle") {
      setShapes("panels", collection([]));
      return;
    }
    setShapes(
      "panels",
      collection(
        analysis.layout.panels
          .filter((p) => p.access >= GOOD_ACCESS)
          .map((p, i) =>
            polygon(p.corners, {
              chosen: i < chosen,
              tip:
                `<p class="tip-title">${i < chosen ? "Panel in your plan" : "Room for another panel"}</p>` +
                `<p>Gets <strong>${Math.round(p.access * 100)}%</strong> of full sun over a year.</p>` +
                `<p class="tip-note">${
                  i < chosen
                    ? "Your plan uses the sunniest positions first."
                    : "Not needed for your electricity use, but a panel would fit here."
                }</p>`,
            }),
          ),
      ),
    );
  }, [analysis, chosen, showPanels, mode]);

  return <div ref={container} className="h-full w-full" />;
}
