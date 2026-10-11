"use client";

import { useEffect, useRef, useState } from "react";
import type { LngLat } from "@/lib/geo/local";
import {
  cameraDirection,
  emptyHorizon,
  horizonCoverage,
  withSample,
  type HorizonProfile,
} from "@/lib/solar/horizon";
import type { SunPosition } from "@/lib/solar/sun";
import { useStore } from "@/lib/store";
import HorizonChart from "./HorizonChart";

const COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];
const SENSOR_TIMEOUT_MS = 2500;
/** Share of each new reading blended in; steadies compass jitter. */
const SMOOTHING = 0.35;

type Phase = "intro" | "scanning" | "no-sensor" | "denied";

interface CompassEvent extends DeviceOrientationEvent {
  webkitCompassHeading?: number;
}
type OrientationPermission = { requestPermission?: () => Promise<"granted" | "denied"> };

/** North-referenced alpha from an orientation event, or null if it has no compass. */
function absoluteAlpha(e: CompassEvent): number | null {
  if (typeof e.webkitCompassHeading === "number") return 360 - e.webkitCompassHeading;
  if (e.absolute && e.alpha !== null) return e.alpha;
  return null;
}

/** Blend two directions through their unit vectors so bearings wrap cleanly at north. */
function smooth(previous: SunPosition | null, next: SunPosition): SunPosition {
  if (!previous) return next;
  const rad = Math.PI / 180;
  const vec = (d: SunPosition) => [
    Math.cos(d.elevation * rad) * Math.sin(d.azimuth * rad),
    Math.cos(d.elevation * rad) * Math.cos(d.azimuth * rad),
    Math.sin(d.elevation * rad),
  ];
  const [a, b] = [vec(previous), vec(next)];
  const v = a.map((x, i) => x * (1 - SMOOTHING) + b[i] * SMOOTHING);
  const length = Math.hypot(v[0], v[1], v[2]) || 1;
  return {
    azimuth: (Math.atan2(v[0], v[1]) / rad + 360) % 360,
    elevation: Math.asin(v[2] / length) / rad,
  };
}

export default function HorizonScan({ at }: { at: LngLat }) {
  const saved = useStore((s) => s.horizon);
  const setHorizon = useStore((s) => s.setHorizon);
  const setScanOpen = useStore((s) => s.setScanOpen);

  const [phase, setPhase] = useState<Phase>("intro");
  const [profile, setProfile] = useState<HorizonProfile>(() => saved ?? emptyHorizon());
  const [pointer, setPointer] = useState<SunPosition | null>(null);
  const [tracing, setTracing] = useState(false);
  const tracingRef = useRef(false);
  const pointerRef = useRef<SunPosition | null>(null);
  const video = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    if (phase !== "scanning") return;

    let gotReading = false;
    const onOrientation = (e: CompassEvent) => {
      const alpha = absoluteAlpha(e);
      if (alpha === null || e.beta === null || e.gamma === null) return;
      gotReading = true;
      const direction = smooth(pointerRef.current, cameraDirection(alpha, e.beta, e.gamma));
      pointerRef.current = direction;
      setPointer(direction);
      if (tracingRef.current) setProfile((p) => withSample(p, direction));
    };
    window.addEventListener("deviceorientationabsolute", onOrientation as EventListener);
    window.addEventListener("deviceorientation", onOrientation as EventListener);
    const timeout = setTimeout(() => {
      if (!gotReading) setPhase("no-sensor");
    }, SENSOR_TIMEOUT_MS);

    let stream: MediaStream | null = null;
    let cancelled = false;
    navigator.mediaDevices
      ?.getUserMedia({ video: { facingMode: "environment" }, audio: false })
      .then((s) => {
        if (cancelled) return s.getTracks().forEach((t) => t.stop());
        stream = s;
        if (video.current) video.current.srcObject = s;
      })
      // The scan still works without a viewfinder.
      .catch(() => {});

    return () => {
      cancelled = true;
      clearTimeout(timeout);
      window.removeEventListener("deviceorientationabsolute", onOrientation as EventListener);
      window.removeEventListener("deviceorientation", onOrientation as EventListener);
      stream?.getTracks().forEach((t) => t.stop());
    };
  }, [phase]);

  const start = async () => {
    // iOS only hands out motion data after an explicit prompt from a tap.
    const sensor = DeviceOrientationEvent as unknown as OrientationPermission;
    if (sensor.requestPermission) {
      const result = await sensor.requestPermission().catch(() => "denied" as const);
      if (result !== "granted") return setPhase("denied");
    }
    setPhase("scanning");
  };

  const setTrace = (on: boolean) => {
    tracingRef.current = on;
    setTracing(on);
  };

  const coverage = horizonCoverage(profile);
  const close = () => setScanOpen(false);

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-surface text-on-surface" role="dialog" aria-label="Rooftop skyline scan">
      <header className="flex items-center justify-between px-5 py-3">
        <h2 className="text-base font-semibold">Scan the skyline from your roof</h2>
        <button className="text-sm text-on-surface-variant hover:text-on-surface" onClick={close}>
          Close
        </button>
      </header>

      {phase === "intro" && (
        <div className="mx-auto max-w-md flex-1 space-y-4 overflow-y-auto px-5 py-4 text-sm text-on-surface">
          <p>Stand on the roof where the panels would go and hold your phone upright, like taking a photo.</p>
          <ol className="list-decimal space-y-2 pl-5">
            <li>Aim the crosshair at the top edge of whatever blocks the sky: a neighbour&apos;s wall, a tree, a tank.</li>
            <li>Press and hold the button, then turn slowly, following the top edge with the crosshair.</li>
            <li>Let go wherever the sky is open down to the horizon. Go over a stretch again to correct it.</li>
          </ol>
          <p className="text-on-surface-variant">
            Keep away from metal railings and tanks while scanning, since they pull the compass off.
          </p>
          <button className="w-full rounded-lg bg-primary px-4 py-3 font-medium text-on-primary" onClick={start}>
            Start scanning
          </button>
        </div>
      )}

      {phase === "no-sensor" && (
        <div className="mx-auto max-w-md flex-1 space-y-3 px-5 py-4 text-sm text-on-surface">
          <p className="text-base text-on-surface">This device has no compass or tilt sensor.</p>
          <p>Open homesol on your phone, outline the same roof there, and run the scan from the rooftop.</p>
        </div>
      )}

      {phase === "denied" && (
        <div className="mx-auto max-w-md flex-1 space-y-3 px-5 py-4 text-sm text-on-surface">
          <p className="text-base text-on-surface">Motion access was declined.</p>
          <p>The scan needs your phone&apos;s compass and tilt. Allow motion access for this site, then try again.</p>
          <button className="rounded-lg border border-outline-variant px-4 py-2" onClick={() => setPhase("intro")}>
            Back
          </button>
        </div>
      )}

      {phase === "scanning" && (
        <>
          <div className="relative min-h-0 flex-1 overflow-hidden bg-black">
            <video ref={video} autoPlay playsInline muted className="h-full w-full object-cover" />
            <div className="pointer-events-none absolute inset-0 grid place-items-center">
              <div className={`h-14 w-14 rounded-full border-2 ${tracing ? "border-primary" : "border-white/80"}`}>
                <div className="mx-auto mt-[26px] h-0.5 w-6 bg-current" />
              </div>
            </div>
            <p className="absolute left-0 right-0 top-3 text-center text-sm font-medium drop-shadow">
              {pointer
                ? `Facing ${COMPASS[Math.round(pointer.azimuth / 45) % 8]} ${Math.round(pointer.azimuth)}° · ${
                    pointer.elevation >= 0 ? "up" : "down"
                  } ${Math.abs(Math.round(pointer.elevation))}°`
                : "Waiting for the compass…"}
            </p>
          </div>

          <div className="mx-auto w-full max-w-md space-y-3 px-5 py-4">
            <HorizonChart profile={profile} at={at} pointer={pointer} />
            <button
              className={`w-full touch-none select-none rounded-lg px-4 py-4 font-medium ${
                tracing ? "bg-primary text-on-primary" : "bg-primary text-on-primary"
              }`}
              onPointerDown={() => setTrace(true)}
              onPointerUp={() => setTrace(false)}
              onPointerLeave={() => setTrace(false)}
              onPointerCancel={() => setTrace(false)}
              onContextMenu={(e) => e.preventDefault()}
            >
              {tracing ? "Tracing… follow the top edge" : "Hold to trace the skyline"}
            </button>
            <div className="flex items-center gap-2">
              <span className="flex-1 text-xs text-on-surface-variant">{Math.round(coverage * 100)}% of the compass traced</span>
              <button className="rounded-lg border border-outline-variant px-3 py-2 text-sm" onClick={() => setProfile(emptyHorizon())}>
                Reset
              </button>
              <button
                className="rounded-lg bg-primary px-3 py-2 text-sm font-medium text-on-primary disabled:opacity-40"
                disabled={coverage === 0}
                onClick={() => {
                  setHorizon(profile);
                  close();
                }}
              >
                Use this scan
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
