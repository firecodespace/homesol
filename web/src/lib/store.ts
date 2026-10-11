import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { ChatTurn, Picture, Place } from "./api";
import { reportVerdict } from "./feedback";
import type { LngLat } from "./geo/local";
import type { ImageryInfo } from "./imagery";
import type { SiteModel } from "./site/model";
import type { ObstructionName } from "./site/naming";
import type { HorizonProfile } from "./solar/horizon";
import type { ShadowHeightEstimate } from "./solar/shadowHeight";

export const FLOOR_HEIGHT_M = 3;

/** `pick` waits for a tap on the roof to outline automatically; the others draw by hand. */
export type Mode = "idle" | "pick" | "roof" | "obstruction" | "measure";
export type ObstructionKind = "building" | "tree" | "tank" | "other";
/** What is drawn over the surface: the year's sun, the shadows at one moment, or nothing. */
export type MapView = "sun" | "shadows" | "photo";

export interface ShadowMeasurement {
  base: LngLat;
  tip: LngLat;
  imagery: ImageryInfo;
  /** `capturedAt` becomes an ISO string once restored from storage. */
  estimate: Omit<ShadowHeightEstimate, "capturedAt"> & { capturedAt: Date | string };
}

/** An obstruction marked by hand, used where Google has no survey. */
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
  /** The detection run that proposed this obstruction, and its position in that run. */
  detectionId?: string;
  modelIndex?: number;
}

interface State {
  mode: Mode;
  /** Points clicked so far for the shape being drawn. */
  draft: LngLat[];
  /** Obstruction whose shadow is being measured. */
  measureTarget: string | null;
  /** Outline of the surface being planned: found from a tap, or drawn by hand. */
  roof: LngLat[] | null;
  /** False until the saved survey has been read back; nothing may write state before then. */
  hydrated: boolean;
  /** Progress of finding a roof from a tap. */
  pick: { state: "finding"; point: LngLat } | { state: "failed"; message: string } | null;
  /** The measured model of the property, where Google has surveyed it. */
  site: SiteModel | null;
  /** Whether the measured model is being fetched, or why there is none. */
  siteStatus: { state: "idle" | "loading" } | { state: "unavailable"; reason: string };
  /** What each measured obstruction is, by obstruction id, once the vision model has looked. */
  names: Record<number, ObstructionName>;
  /** Google's photo of the area, shown under the outline so both line up. */
  picture: Picture | null;
  /** Country, state and currency of the property. */
  place: Place | null;
  /** The conversation with the advisor. Asked from the tools panel, read in the results panel. */
  chat: { turns: ChatTurn[]; waiting: boolean; error: string | null };
  /** Link and QR code from the last save, if any. */
  shared: { url: string; qr: string } | null;
  floors: number;
  obstructions: Obstruction[];
  /** Skyline traced from the roof with a phone, if the user has scanned one. */
  horizon: HorizonProfile | null;
  scanOpen: boolean;
  /** Units (kWh) on a typical monthly electricity bill. */
  monthlyUnits: number | null;
  /** Typical monthly bill in the local currency, if the user gave it. */
  monthlyBill: number | null;
  /** A vendor's quote before subsidy, if the user has one. */
  quotedCost: number | null;
  /** Sanctioned load in kW, when read from the bill. */
  sanctionedLoadKw: number | null;
  /** Latest detection run on this roof; hand-drawn obstructions after it count as its misses. */
  lastDetectionId: string | null;
  /** Chosen electricity distributor; null until matched from the property's location. */
  discomId: string | null;
  view: MapView;
  showPanels: boolean;
  showObstructions: boolean;
  /** Month (1–12) and minutes past midnight, local time, shown by the shadow view. */
  preview: { month: number; minutes: number };
  flyTo: LngLat | null;
  /** Progress of the height-from-shadow lookup for `measureTarget`. */
  measureStatus: { state: "loading" } | { state: "error"; message: string } | null;

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
  addObstructions(found: Obstruction[], detectionId: string | null): void;
  setPreview(patch: Partial<State["preview"]>): void;
  requestFlyTo(p: LngLat | null): void;
  setHorizon(horizon: HorizonProfile | null): void;
  setScanOpen(open: boolean): void;
  setMonthlyUnits(units: number | null): void;
  setMoney(patch: Partial<Pick<State, "monthlyBill" | "quotedCost" | "discomId" | "sanctionedLoadKw">>): void;
}

/**
 * What a new property starts from: nothing found, nothing asked, nothing shared, and none of the
 * last property's electricity or cost figures, which belonged to that household.
 */
const NO_PROPERTY = {
  roof: null,
  pick: null,
  site: null,
  names: {} as Record<number, ObstructionName>,
  siteStatus: { state: "idle" } as State["siteStatus"],
  picture: null,
  place: null,
  chat: { turns: [], waiting: false, error: null },
  shared: null,
  floors: 2,
  obstructions: [] as Obstruction[],
  horizon: null,
  monthlyUnits: null,
  monthlyBill: null,
  quotedCost: null,
  sanctionedLoadKw: null,
  discomId: null,
  lastDetectionId: null,
  draft: [] as LngLat[],
  measureTarget: null,
};

export const useStore = create<State>()(
  persist(
    (set, get) => ({
      ...NO_PROPERTY,
      mode: "idle",
      hydrated: false,
      scanOpen: false,
      view: "sun",
      showPanels: true,
      showObstructions: true,
      preview: { month: 12, minutes: 11 * 60 },
      flyTo: null,
      measureStatus: null,

      startDrawing: (mode) => set({ mode, draft: [], measureTarget: null, measureStatus: null, pick: null }),
      startMeasuring: (id) => set({ mode: "measure", draft: [], measureTarget: id, measureStatus: null }),
      addDraftPoint: (p) => set((s) => ({ draft: [...s.draft, p] })),
      undoDraftPoint: () => set((s) => ({ draft: s.draft.slice(0, -1) })),
      finishDrawing: () => {
        const { mode, draft, obstructions } = get();
        if (draft.length < 3) return;
        if (mode === "roof") set({ roof: draft, site: null, names: {}, mode: "idle", draft: [] });
        if (mode === "obstruction") {
          const obstruction: Obstruction = {
            id: crypto.randomUUID(),
            kind: "building",
            footprint: draft,
            heightM: null,
            reference: "ground",
          };
          set({ obstructions: [...obstructions, obstruction], mode: "idle", draft: [] });
          const { lastDetectionId, roof } = get();
          if (lastDetectionId && roof) reportVerdict("missed", lastDetectionId, obstruction, roof);
        }
      },
      cancel: () => set({ mode: "idle", draft: [], measureTarget: null }),
      clearRoof: () => set({ ...NO_PROPERTY, mode: "idle" }),
      setFloors: (floors) => set({ floors }),
      updateObstruction: (id, patch) =>
        set((s) => ({ obstructions: s.obstructions.map((o) => (o.id === id ? { ...o, ...patch } : o)) })),
      removeObstruction: (id) => set((s) => ({ obstructions: s.obstructions.filter((o) => o.id !== id) })),
      addObstructions: (found, detectionId) =>
        set((s) => ({
          obstructions: [...s.obstructions, ...found],
          lastDetectionId: detectionId ?? s.lastDetectionId,
        })),
      setPreview: (patch) => set((s) => ({ preview: { ...s.preview, ...patch } })),
      requestFlyTo: (flyTo) => set({ flyTo }),
      setHorizon: (horizon) => set({ horizon }),
      setScanOpen: (scanOpen) => set({ scanOpen }),
      setMonthlyUnits: (monthlyUnits) => set({ monthlyUnits }),
      setMoney: (patch) => set(patch),
    }),
    {
      name: "homesol-survey",
      // Rehydrated from Planner after mount so server and first client render match.
      skipHydration: true,
      partialize: (s) => ({
        roof: s.roof,
        floors: s.floors,
        obstructions: s.obstructions,
        horizon: s.horizon,
        monthlyUnits: s.monthlyUnits,
        monthlyBill: s.monthlyBill,
        quotedCost: s.quotedCost,
        discomId: s.discomId,
        sanctionedLoadKw: s.sanctionedLoadKw,
        lastDetectionId: s.lastDetectionId,
      }),
    },
  ),
);
