import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { LngLat } from "./geo/local";
import type { ImageryInfo } from "./imagery";
import type { HorizonProfile } from "./solar/horizon";
import type { ShadowHeightEstimate } from "./solar/shadowHeight";

export const FLOOR_HEIGHT_M = 3;

export type Mode = "idle" | "roof" | "obstruction" | "measure";
export type ObstructionKind = "building" | "tree" | "tank" | "other";

export interface ShadowMeasurement {
  base: LngLat;
  tip: LngLat;
  imagery: ImageryInfo;
  /** `capturedAt` becomes an ISO string once restored from storage. */
  estimate: Omit<ShadowHeightEstimate, "capturedAt"> & {
    capturedAt: Date | string;
  };
}

export interface Obstruction {
  id: string;
  kind: ObstructionKind;
  footprint: LngLat[];
  heightM: number | null;
  reference: "ground" | "roof";
  measurement?: ShadowMeasurement;
  /** Short description from automatic detection. */
  label?: string;
  /** Proposed by automatic detection and not yet checked by the user. */
  suggested?: boolean;
}

interface State {
  mode: Mode;
  /** Points clicked so far for the shape being drawn. */
  draft: LngLat[];
  /** Obstruction whose shadow is being measured. */
  measureTarget: string | null;
  roof: LngLat[] | null;
  floors: number;
  obstructions: Obstruction[];
  /** Skyline traced from the roof with a phone, if the user has scanned one. */
  horizon: HorizonProfile | null;
  scanOpen: boolean;
  /** Units (kWh) on a typical monthly electricity bill. */
  monthlyUnits: number | null;
  showSunMap: boolean;
  /** Date and time shown in the live shadow preview (IST). */
  preview: { month: number; minutes: number };
  flyTo: LngLat | null;
  /** Progress of the height-from-shadow lookup for `measureTarget`. */
  measureStatus:
    { state: "loading" } | { state: "error"; message: string } | null;

  startDrawing(mode: "roof" | "obstruction"): void;
  startMeasuring(id: string): void;
  addDraftPoint(p: LngLat): void;
  undoDraftPoint(): void;
  finishDrawing(): void;
  cancel(): void;
  clearRoof(): void;
  setFloors(floors: number): void;
  updateObstruction(id: string, patch: Partial<Omit<Obstruction, "id">>): void;
  removeObstruction(id: string): void;
  addObstructions(found: Obstruction[]): void;
  setPreview(patch: Partial<State["preview"]>): void;
  requestFlyTo(p: LngLat | null): void;
  setHorizon(horizon: HorizonProfile | null): void;
  setScanOpen(open: boolean): void;
  setShowSunMap(show: boolean): void;
  setMonthlyUnits(units: number | null): void;
}

export const useStore = create<State>()(
  persist(
    (set, get) => ({
      mode: "idle",
      draft: [],
      measureTarget: null,
      roof: null,
      floors: 2,
      obstructions: [],
      horizon: null,
      scanOpen: false,
      monthlyUnits: null,
      showSunMap: true,
      preview: { month: 12, minutes: 11 * 60 },
      flyTo: null,
      measureStatus: null,

      startDrawing: (mode) =>
        set({ mode, draft: [], measureTarget: null, measureStatus: null }),
      startMeasuring: (id) =>
        set({
          mode: "measure",
          draft: [],
          measureTarget: id,
          measureStatus: null,
        }),
      addDraftPoint: (p) => set((s) => ({ draft: [...s.draft, p] })),
      undoDraftPoint: () => set((s) => ({ draft: s.draft.slice(0, -1) })),
      finishDrawing: () => {
        const { mode, draft, obstructions } = get();
        if (draft.length < 3) return;
        if (mode === "roof") set({ roof: draft, mode: "idle", draft: [] });
        if (mode === "obstruction") {
          const obstruction: Obstruction = {
            id: crypto.randomUUID(),
            kind: "building",
            footprint: draft,
            heightM: null,
            reference: "ground",
          };
          set({
            obstructions: [...obstructions, obstruction],
            mode: "idle",
            draft: [],
          });
        }
      },
      cancel: () => set({ mode: "idle", draft: [], measureTarget: null }),
      clearRoof: () =>
        set({
          roof: null,
          obstructions: [],
          horizon: null,
          mode: "idle",
          draft: [],
          measureTarget: null,
        }),
      setFloors: (floors) => set({ floors }),
      updateObstruction: (id, patch) =>
        set((s) => ({
          obstructions: s.obstructions.map((o) =>
            o.id === id ? { ...o, ...patch } : o,
          ),
        })),
      removeObstruction: (id) =>
        set((s) => ({
          obstructions: s.obstructions.filter((o) => o.id !== id),
        })),
      addObstructions: (found) =>
        set((s) => ({ obstructions: [...s.obstructions, ...found] })),
      setPreview: (patch) =>
        set((s) => ({ preview: { ...s.preview, ...patch } })),
      requestFlyTo: (flyTo) => set({ flyTo }),
      setHorizon: (horizon) => set({ horizon }),
      setScanOpen: (scanOpen) => set({ scanOpen }),
      setShowSunMap: (showSunMap) => set({ showSunMap }),
      setMonthlyUnits: (monthlyUnits) => set({ monthlyUnits }),
    }),
    {
      name: "homesol-survey",
      // Rehydrated from Planner after mount so server and first client render match.
      skipHydration: true,
      partialize: ({ roof, floors, obstructions, horizon, monthlyUnits }) => ({
        roof,
        floors,
        obstructions,
        horizon,
        monthlyUnits,
      }),
    },
  ),
);
