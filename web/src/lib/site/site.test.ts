import { describe, expect, it } from "vitest";
import { localFrame, pointInPolygon, type LngLat } from "../geo/local";
import { clockIn, zoneAt, zonedDate } from "../time";
import { gridToLngLat, lngLatToGrid, modelFromCells, type SiteModel } from "./model";
import { flatSurfaceTilt, GOOD_ACCESS, layoutPanels, PANEL_LONG_M } from "./panels";
import { analyseShade, castShadows, shadowGrid } from "./shadows";

const MUMBAI: LngLat = [72.8777, 19.076];
const SYDNEY: LngLat = [151.2093, -33.8688];
const PX = 0.5;

/** A north-up site with flat ground at height 0, `size` pixels square, centred on `at`. */
function site(at: LngLat, size: number, edit: (m: SiteModel, set: (r0: number, r1: number, c0: number, c1: number, height: number, label: number) => void) => void): SiteModel {
  const frame = localFrame(at);
  const half = (size * PX) / 2;
  const model: SiteModel = {
    rows: size,
    cols: size,
    pixelM: PX,
    corners: [frame.toLngLat([-half, half]), frame.toLngLat([half, half]), frame.toLngLat([half, -half]), frame.toLngLat([-half, -half])],
    northDeg: 0,
    heights: new Float32Array(size * size),
    access: new Float32Array(size * size).fill(1),
    labels: new Uint8Array(size * size),
    photo: null,
    outline: [],
    surface: { kind: "roof", area_m2: 0, height_m: 6, floors: 2, tilt_deg: 0, faces_deg: 180, faces: "south", found_by: "tap", cut_off: false },
    obstructions: [],
    measured: true,
    imageryDate: null,
    imageryQuality: null,
  };
  edit(model, (r0, r1, c0, c1, height, label) => {
    for (let r = r0; r < r1; r++) {
      for (let c = c0; c < c1; c++) {
        model.heights![r * size + c] = height;
        model.labels[r * size + c] = label;
      }
    }
  });
  return model;
}

/** A 10 m x 10 m flat roof, 6 m up, in the middle of an 80-pixel site, outlined. */
function roofSite(at: LngLat, extra?: Parameters<typeof site>[2]): SiteModel {
  return site(at, 80, (m, set) => {
    set(30, 50, 30, 50, 6, 1);
    m.outline = [gridToLngLat(m, 30, 30), gridToLngLat(m, 50, 30), gridToLngLat(m, 50, 50), gridToLngLat(m, 30, 50)];
    extra?.(m, set);
  });
}

describe("time zones", () => {
  it("finds the zone of a place and converts its wall-clock time", () => {
    expect(zoneAt(MUMBAI)).toBe("Asia/Kolkata");
    expect(zoneAt(SYDNEY)).toBe("Australia/Sydney");
    expect(zonedDate("Asia/Kolkata", 2026, 12, 21, 11 * 60).toISOString()).toBe("2026-12-21T05:30:00.000Z");
    // Sydney is on daylight time in December, eleven hours ahead.
    expect(zonedDate("Australia/Sydney", 2026, 12, 21, 12 * 60).toISOString()).toBe("2026-12-21T01:00:00.000Z");
    expect(clockIn("Asia/Kolkata", new Date("2026-06-21T06:45:00Z"))).toBe("12:15");
  });
});

describe("grid coordinates", () => {
  it("converts between grid and map positions both ways", () => {
    const m = roofSite(MUMBAI);
    const p = gridToLngLat(m, 12.5, 61);
    const [col, row] = lngLatToGrid(m, p);
    expect(col).toBeCloseTo(12.5, 3);
    expect(row).toBeCloseTo(61, 3);
    const frame = localFrame(MUMBAI);
    // Pixel (40, 40) is the centre; ten pixels east is five metres east.
    expect(frame.toXY(gridToLngLat(m, 50, 40))[0]).toBeCloseTo(5, 2);
  });
});

describe("castShadows", () => {
  // A 10 m tower, 4 m square, in the middle of flat ground.
  const tower = site(MUMBAI, 80, (_, set) => set(36, 44, 36, 44, 10, 2));
  const grid = shadowGrid(tower, PX)!;
  const out = new Uint8Array(80 * 80);
  const at = (row: number, col: number) => out[row * 80 + col];

  it("throws a shadow away from the sun, as long as the tower is tall when the sun is at 45°", () => {
    castShadows(grid, 180, 45, out); // sun due south, so the shadow falls north (smaller rows)
    expect(at(26, 40)).toBe(1); // 5 m north of the tower
    expect(at(12, 40)).toBe(0); // 12 m north of the tower's edge, beyond its 10 m shadow
    expect(at(54, 40)).toBe(0); // south of the tower, in sun
    expect(at(40, 20)).toBe(0); // to the west, in sun
  });

  it("makes the shadow longer when the sun is lower and swings it with the sun", () => {
    castShadows(grid, 180, 20, out);
    expect(at(12, 40)).toBe(1); // 12 m north; the shadow is about 27 m long now
    castShadows(grid, 90, 45, out); // sun in the east, shadow falls west
    expect(at(40, 26)).toBe(1);
    expect(at(26, 40)).toBe(0);
  });

  it("treats a sun below the horizon as shade everywhere", () => {
    castShadows(grid, 180, -5, out);
    expect(out.every((v) => v === 1)).toBe(true);
  });
});

describe("analyseShade", () => {
  it("blames the shade on a roof on what casts it, and reports when the roof is clear", () => {
    // A roof with a tall neighbour right against its southern edge.
    const m = roofSite(MUMBAI, (_, set) => set(50, 60, 30, 50, 16, 2));
    const grid = shadowGrid(m, PX)!;
    const tested = Uint8Array.from(grid.labels, (l) => (l === 1 ? 1 : 0));
    const report = analyseShade(m, grid, tested, MUMBAI);

    expect(report.lost).toBeGreaterThan(0.15);
    expect(report.lost).toBeLessThan(0.7);
    expect(report.blame.get(2)).toBeGreaterThan(0.95);
    // In June the sun is nearly overhead in Mumbai, so the southern neighbour barely matters;
    // in December it is low in the south and the roof is never clear.
    expect(report.fullSun[5].from).not.toBeNull();
    expect(report.fullSun[11].from).toBeNull();
  });

  it("finds an open roof loses nothing", () => {
    const m = roofSite(MUMBAI);
    const grid = shadowGrid(m, PX)!;
    const tested = Uint8Array.from(grid.labels, (l) => (l === 1 ? 1 : 0));
    expect(analyseShade(m, grid, tested, MUMBAI).lost).toBe(0);
  });
});

describe("layoutPanels", () => {
  const inside = (m: SiteModel, p: LngLat) => pointInPolygon(lngLatToGrid(m, p), m.outline.map((o) => lngLatToGrid(m, o)));

  it("fills a flat roof with tilted rows facing south, clear of the edge", () => {
    const m = roofSite(MUMBAI);
    const layout = layoutPanels(m);

    expect(layout.mounting).toBe("tilted rows");
    expect(layout.tiltDeg).toBe(flatSurfaceTilt(MUMBAI[1]));
    expect(layout.facingDeg).toBeCloseTo(180, 0);
    // 100 m² holds roughly 8 to 10 kW in rows: three panels across, five or six rows.
    expect(layout.panels.length).toBeGreaterThanOrEqual(15);
    expect(layout.panels.length).toBeLessThanOrEqual(18);
    expect(layout.good).toBe(layout.panels.length);
    for (const panel of layout.panels) for (const corner of panel.corners) expect(inside(m, corner)).toBe(true);

    // Each panel is its long side wide on the map, and rows do not touch.
    const frame = localFrame(MUMBAI);
    const [a, b] = layout.panels[0].corners.map(frame.toXY);
    expect(Math.hypot(b[0] - a[0], b[1] - a[1])).toBeCloseTo(PANEL_LONG_M, 1);
    expect(layout.rowPitchM).toBeGreaterThan(1.3);
  });

  it("goes around a structure on the roof", () => {
    const m = roofSite(MUMBAI, (_, set) => set(38, 42, 38, 42, 8.5, 2));
    const open = layoutPanels(roofSite(MUMBAI)).panels.length;
    const layout = layoutPanels(m);
    expect(layout.panels.length).toBeLessThan(open);
    expect(layout.panels.length).toBeGreaterThanOrEqual(open / 2);
    const tank = [gridToLngLat(m, 38, 38), gridToLngLat(m, 42, 38), gridToLngLat(m, 42, 42), gridToLngLat(m, 38, 42)].map((p) => lngLatToGrid(m, p));
    for (const panel of layout.panels) for (const corner of panel.corners) expect(pointInPolygon(lngLatToGrid(m, corner), tank)).toBe(false);
  });

  it("ranks positions by sun and counts only the good ones", () => {
    const m = roofSite(MUMBAI);
    // The western half of the roof is poorly lit.
    for (let r = 30; r < 50; r++) for (let c = 30; c < 40; c++) m.access[r * 80 + c] = 0.5;
    const layout = layoutPanels(m);
    expect(layout.panels[0].access).toBeGreaterThan(layout.panels[layout.panels.length - 1].access);
    expect(layout.good).toBeLessThan(layout.panels.length);
    expect(layout.panels.slice(0, layout.good).every((p) => p.access >= GOOD_ACCESS)).toBe(true);
  });

  it("faces panels north in the southern hemisphere", () => {
    expect(layoutPanels(roofSite(SYDNEY)).facingDeg).toBeCloseTo(0, 0);
  });

  it("lays panels flat against a slope, facing the way it faces, with no gaps between rows", () => {
    const m = roofSite(MUMBAI);
    m.surface = { ...m.surface, kind: "sloped_roof", tilt_deg: 25, faces_deg: 200 };
    const layout = layoutPanels(m);
    expect(layout.mounting).toBe("flush on the slope");
    expect(layout.tiltDeg).toBe(25);
    expect(layout.facingDeg).toBe(200);
    expect(layout.rowPitchM).toBeLessThan(1.1);
    expect(layout.panels.length).toBeGreaterThan(layoutPanels(roofSite(MUMBAI)).panels.length);
  });

  it("lines rows up with a building that is turned away from north", () => {
    // A roof rotated 20° clockwise.
    const frame = localFrame(MUMBAI);
    const turn = (20 * Math.PI) / 180;
    const corner = (x: number, y: number): LngLat => frame.toLngLat([x * Math.cos(turn) + y * Math.sin(turn), -x * Math.sin(turn) + y * Math.cos(turn)]);
    const m = site(MUMBAI, 80, (model) => {
      model.outline = [corner(-6, 6), corner(6, 6), corner(6, -6), corner(-6, -6)];
      const poly = model.outline.map((p) => lngLatToGrid(model, p));
      for (let r = 0; r < 80; r++) for (let c = 0; c < 80; c++) if (pointInPolygon([c + 0.5, r + 0.5], poly)) model.labels[r * 80 + c] = 1;
    });
    expect(layoutPanels(m).facingDeg).toBeCloseTo(200, -1);
  });
});

describe("modelFromCells", () => {
  it("turns a hand-estimated shade grid into a site panels can be laid out on", () => {
    const frame = localFrame(MUMBAI);
    const roof = [frame.toLngLat([-5, 5]), frame.toLngLat([5, 5]), frame.toLngLat([5, -5]), frame.toLngLat([-5, -5])];
    const cells = [];
    for (let x = -5; x < 5; x += 0.5) {
      for (let y = -5; y < 5; y += 0.5) {
        cells.push({ polygon: [frame.toLngLat([x, y]), frame.toLngLat([x + 0.5, y]), frame.toLngLat([x + 0.5, y + 0.5]), frame.toLngLat([x, y + 0.5])], access: 1 });
      }
    }
    const m = modelFromCells(roof, cells, 0.5, 6);
    expect(m.measured).toBe(false);
    expect(m.heights).toBeNull();
    expect(m.labels.reduce((n, l) => n + l, 0)).toBe(400);
    expect(layoutPanels(m).panels.length).toBeGreaterThanOrEqual(15);
  });
});
