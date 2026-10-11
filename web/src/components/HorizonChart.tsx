"use client";

import { useMemo } from "react";
import type { LngLat } from "@/lib/geo/local";
import { HORIZON_BIN_DEG, type HorizonProfile } from "@/lib/solar/horizon";
import { istDate, sunAt, type SunPosition } from "@/lib/solar/sun";

const W = 360;
const H = 120;
const MAX_ELEVATION = 90;
const SUN_PATHS = [
  { month: 6, label: "Jun", color: "#fde047" },
  { month: 3, label: "Mar", color: "#fb923c" },
  { month: 12, label: "Dec", color: "#f87171" },
];

const y = (elevation: number) => H - (Math.min(MAX_ELEVATION, Math.max(0, elevation)) / MAX_ELEVATION) * H;

/** One day's sun track as SVG path segments, split where it wraps past north. */
function sunPath(month: number, at: LngLat): string {
  let d = "";
  let previous: number | null = null;
  for (let minutes = 4 * 60; minutes <= 20 * 60; minutes += 10) {
    const sun = sunAt(istDate(2026, month, 21, 0, minutes), at);
    if (sun.elevation < 0) {
      previous = null;
      continue;
    }
    const wrapped = previous !== null && Math.abs(sun.azimuth - previous) > 180;
    d += `${previous === null || wrapped ? "M" : "L"}${sun.azimuth.toFixed(1)},${y(sun.elevation).toFixed(1)}`;
    previous = sun.azimuth;
  }
  return d;
}

interface Props {
  profile: HorizonProfile;
  at: LngLat;
  /** Where the phone is pointing right now, while scanning. */
  pointer?: SunPosition | null;
}

/** Skyline against the sun's summer, equinox and winter tracks. North is at both edges. */
export default function HorizonChart({ profile, at, pointer }: Props) {
  const paths = useMemo(() => SUN_PATHS.map((p) => ({ ...p, d: sunPath(p.month, at) })), [at]);

  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full rounded-lg bg-sky-950" role="img" aria-label="Scanned skyline and sun paths">
        {[30, 60].map((e) => (
          <line key={e} x1={0} x2={W} y1={y(e)} y2={y(e)} stroke="#1e3a5f" strokeWidth={0.5} />
        ))}
        {paths.map((p) => (
          <path key={p.month} d={p.d} fill="none" stroke={p.color} strokeWidth={1.5} />
        ))}
        {profile.map((elevation, bin) => {
          const x = bin * HORIZON_BIN_DEG - HORIZON_BIN_DEG / 2;
          return elevation === null ? (
            <rect key={bin} x={x} y={H - 2} width={HORIZON_BIN_DEG} height={2} fill="#475569" />
          ) : (
            <rect key={bin} x={x} y={y(elevation)} width={HORIZON_BIN_DEG} height={H - y(elevation) + 0.5} fill="#0f172a" stroke="#38bdf8" strokeWidth={0.4} />
          );
        })}
        {pointer && (
          <circle cx={pointer.azimuth} cy={y(pointer.elevation)} r={4} fill="none" stroke="#ffffff" strokeWidth={1.5} />
        )}
      </svg>
      <div className="mt-1 flex justify-between text-[10px] text-on-surface-variant">
        {["N", "E", "S", "W", "N"].map((label, i) => (
          <span key={i}>{label}</span>
        ))}
      </div>
      <div className="mt-1 flex gap-3 text-[10px] text-on-surface-variant">
        {SUN_PATHS.map((p) => (
          <span key={p.month} className="flex items-center gap-1">
            <span className="inline-block h-0.5 w-3" style={{ background: p.color }} />
            Sun in {p.label}
          </span>
        ))}
        <span className="flex items-center gap-1">
          <span className="inline-block h-2 w-3 border border-secondary bg-surface-container" />
          Blocked sky
        </span>
      </div>
    </div>
  );
}
