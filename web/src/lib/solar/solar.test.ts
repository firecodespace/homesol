import { describe, expect, it } from "vitest";
import { localFrame, type LngLat } from "../geo/local";
import { cameraDirection, emptyHorizon, horizonElevation, withSample } from "./horizon";
import { analyseShading, shadowOutlines } from "./shading";
import { estimateHeightFromShadow } from "./shadowHeight";
import { PANEL_KW, sizeSystem } from "./sizing";
import { istDate, sunAt } from "./sun";

const DELHI: LngLat = [77.209, 28.6139];
const MUMBAI: LngLat = [72.8777, 19.076];
const DEG = Math.PI / 180;

function square(centre: LngLat, east: number, north: number, size: number): LngLat[] {
  const frame = localFrame(centre);
  const h = size / 2;
  return [
    frame.toLngLat([east - h, north - h]),
    frame.toLngLat([east + h, north - h]),
    frame.toLngLat([east + h, north + h]),
    frame.toLngLat([east - h, north + h]),
  ];
}

describe("sunAt", () => {
  it("puts the winter midday sun low in the south over Delhi", () => {
    const sun = sunAt(istDate(2025, 12, 21, 12, 20), DELHI);
    expect(sun.azimuth).toBeGreaterThan(170);
    expect(sun.azimuth).toBeLessThan(190);
    expect(sun.elevation).toBeGreaterThan(36);
    expect(sun.elevation).toBeLessThan(39);
  });

  it("puts the morning sun in the east", () => {
    const sun = sunAt(istDate(2025, 3, 21, 8, 0), MUMBAI);
    expect(sun.azimuth).toBeGreaterThan(80);
    expect(sun.azimuth).toBeLessThan(110);
  });
});

describe("estimateHeightFromShadow", () => {
  it.each([
    { place: MUMBAI, date: { year: 2025, month: 11, day: 11 }, hh: 10, mm: 45, height: 21 },
    { place: DELHI, date: { year: 2025, month: 1, day: 15 }, hh: 11, mm: 5, height: 9 },
    { place: DELHI, date: { year: 2025, month: 6, day: 2 }, hh: 10, mm: 30, height: 45 },
  ])("recovers a $height m building without knowing the capture time", ({ place, date, hh, mm, height }) => {
    const captured = istDate(date.year, date.month, date.day, hh, mm);
    const sun = sunAt(captured, place);
    const length = height / Math.tan(sun.elevation * DEG);
    const away = (sun.azimuth + 180) * DEG;
    const tip = localFrame(place).toLngLat([Math.sin(away) * length, Math.cos(away) * length]);

    const est = estimateHeightFromShadow(place, tip, date);

    expect(est.heightM).toBeCloseTo(height, 0);
    expect(Math.abs(est.capturedAt.getTime() - captured.getTime())).toBeLessThan(3 * 60_000);
    expect(est.warnings).toEqual([]);
    expect(est.range[0]).toBeLessThan(height);
    expect(est.range[1]).toBeGreaterThan(height);
  });

  it("warns when the shadow points towards the sun's side of the sky", () => {
    // A shadow pointing due south is impossible in Delhi in January.
    const tip = localFrame(DELHI).toLngLat([0, -20]);
    const est = estimateHeightFromShadow(DELHI, tip, { year: 2025, month: 1, day: 15 });
    expect(est.warnings.length).toBeGreaterThan(0);
  });
});

describe("analyseShading", () => {
  const roof = square(DELHI, 0, 0, 10);

  it("gives an open roof full sun and sizes it at 10 m² per kW", () => {
    const result = analyseShading(roof, 6, []);
    expect(result.roofAreaM2).toBeCloseTo(100, 0);
    expect(result.meanAccess).toBe(1);
    expect(result.capacityKw).toBeCloseTo(10, 0);
  });

  it("shades the roof more from a tower to the south than from one to the north", () => {
    const tower = (north: number) => [
      { footprint: square(DELHI, 0, north, 10), heightM: 30, reference: "ground" as const },
    ];
    const south = analyseShading(roof, 6, tower(-12));
    const north = analyseShading(roof, 6, tower(12));
    expect(south.meanAccess).toBeLessThan(0.8);
    expect(north.meanAccess).toBeGreaterThan(0.95);
    expect(south.meanAccess).toBeLessThan(north.meanAccess);
  });

  it("ignores neighbours that are no taller than the roof", () => {
    const low = [{ footprint: square(DELHI, 0, -12, 10), heightM: 6, reference: "ground" as const }];
    expect(analyseShading(roof, 6, low).meanAccess).toBe(1);
  });

  it("treats a rooftop water tank as unusable area that shades its north side", () => {
    const tank = [{ footprint: square(DELHI, 0, 0, 2), heightM: 2, reference: "roof" as const }];
    const result = analyseShading(roof, 6, tank);
    const frame = localFrame(DELHI);
    const accessAt = (east: number, north: number) => {
      const cell = result.cells.find((c) => {
        const [x, y] = frame.toXY(c.polygon[0]);
        return Math.abs(x + result.cellSizeM / 2 - east) < 0.3 && Math.abs(y + result.cellSizeM / 2 - north) < 0.3;
      });
      return cell!.access;
    };
    expect(accessAt(0.25, 0.25)).toBe(0);
    expect(accessAt(0.25, 2.25)).toBeLessThan(accessAt(0.25, -2.25));
    expect(accessAt(0.25, -2.25)).toBe(1);
  });
});

describe("shadowOutlines", () => {
  it("casts a midday winter shadow northwards, about as long as height / tan(elevation)", () => {
    const when = istDate(2025, 12, 21, 12, 20);
    const sun = sunAt(when, DELHI);
    const [outline] = shadowOutlines(
      [{ footprint: square(DELHI, 0, 0, 4), heightM: 10, reference: "roof" }],
      0,
      sun,
    );
    const frame = localFrame(DELHI);
    const northmost = Math.max(...outline.map((p) => frame.toXY(p)[1]));
    expect(northmost).toBeCloseTo(2 + 10 / Math.tan(sun.elevation * DEG), 0);
  });

  it("casts nothing at night", () => {
    const sun = sunAt(istDate(2025, 12, 21, 23, 0), DELHI);
    expect(shadowOutlines([{ footprint: square(DELHI, 0, 0, 4), heightM: 10, reference: "roof" }], 0, sun)).toEqual([]);
  });
});

describe("cameraDirection", () => {
  it.each([
    { name: "upright facing north", angles: [0, 90, 0], azimuth: 0, elevation: 0 },
    { name: "upright facing west", angles: [90, 90, 0], azimuth: 270, elevation: 0 },
    { name: "upright facing east", angles: [270, 90, 0], azimuth: 90, elevation: 0 },
    { name: "facing south, tilted back 30°", angles: [180, 120, 0], azimuth: 180, elevation: 30 },
    { name: "lying flat, camera down", angles: [0, 0, 0], azimuth: null, elevation: -90 },
  ])("reads a phone held $name", ({ angles, azimuth, elevation }) => {
    const dir = cameraDirection(angles[0], angles[1], angles[2]);
    expect(dir.elevation).toBeCloseTo(elevation, 5);
    if (azimuth !== null) expect(Math.abs(dir.azimuth - azimuth) % 360).toBeCloseTo(0, 5);
  });
});

describe("horizon profile", () => {
  it("interpolates between scanned bearings and treats unscanned sky as open", () => {
    let profile = emptyHorizon();
    profile = withSample(profile, { azimuth: 180, elevation: 40 });
    profile = withSample(profile, { azimuth: 185, elevation: 20 });
    expect(horizonElevation(profile, 180)).toBe(40);
    expect(horizonElevation(profile, 182.5)).toBeCloseTo(30, 5);
    expect(horizonElevation(profile, 90)).toBe(0);
  });

  it("lets a re-trace replace an earlier sample and never goes below the horizon", () => {
    let profile = withSample(emptyHorizon(), { azimuth: 358, elevation: 50 });
    profile = withSample(profile, { azimuth: 1, elevation: -10 });
    expect(horizonElevation(profile, 0)).toBe(0);
  });

  it("cuts yearly sun when a southern skyline hides the winter sun", () => {
    const roof = square(DELHI, 0, 0, 10);
    let wall = emptyHorizon();
    for (let az = 120; az <= 240; az += 5) wall = withSample(wall, { azimuth: az, elevation: 45 });
    let northWall = emptyHorizon();
    for (let az = 300; az <= 420; az += 5) northWall = withSample(northWall, { azimuth: az, elevation: 45 });

    const south = analyseShading(roof, 6, [], wall);
    const north = analyseShading(roof, 6, [], northWall);
    expect(south.meanAccess).toBeLessThan(0.85);
    expect(south.meanAccess).toBeGreaterThan(0.2);
    expect(north.meanAccess).toBeGreaterThan(0.9);
  });
});

describe("sizeSystem", () => {
  // NASA POWER climatology for Mumbai, kWh/m²/day.
  const mumbai = [4.88, 5.74, 6.59, 7.08, 7.09, 5.0, 3.79, 4.04, 4.78, 5.21, 4.84, 4.53];
  const open = (count: number, access = 1) => Array<number>(count).fill(access);

  it("sizes a 300-unit home at about 2.5 kW, generating roughly 4 units per kW per day", () => {
    const s = sizeSystem({ monthlyIrradiance: mumbai, monthlyUsageKwh: 300, panelAccess: open(40) });
    expect(s.systemKw).toBeGreaterThan(2);
    expect(s.systemKw).toBeLessThan(3);
    expect(s.limitedBy).toBe("usage");
    expect(s.coverage).toBe(1);
    expect(s.annualKwh / s.systemKw / 365).toBeCloseTo(4, 0);
    // The monsoon months generate least.
    expect(Math.min(...s.monthlyKwh)).toBe(s.monthlyKwh[6]);
  });

  it("stops at the positions that exist and reports partial coverage", () => {
    const s = sizeSystem({ monthlyIrradiance: mumbai, monthlyUsageKwh: 300, panelAccess: open(2) });
    expect(s.panels).toBe(2);
    expect(s.systemKw).toBeCloseTo(2 * PANEL_KW, 5);
    expect(s.limitedBy).toBe("roof");
    expect(s.coverage).toBeLessThan(0.6);
  });

  it("needs more panels where the positions are partly shaded", () => {
    const base = { monthlyIrradiance: mumbai, monthlyUsageKwh: 300 };
    expect(sizeSystem({ ...base, panelAccess: open(40, 0.85) }).panels).toBeGreaterThan(
      sizeSystem({ ...base, panelAccess: open(40) }).panels,
    );
  });

  it("counts each panel at its own sunlight, sunniest first", () => {
    const full = sizeSystem({ monthlyIrradiance: mumbai, monthlyUsageKwh: 100_000, panelAccess: [1, 1] });
    const mixed = sizeSystem({ monthlyIrradiance: mumbai, monthlyUsageKwh: 100_000, panelAccess: [1, 0.9] });
    expect(mixed.annualKwh / full.annualKwh).toBeCloseTo(0.95, 5);
  });
});
