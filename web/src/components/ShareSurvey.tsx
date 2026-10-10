"use client";

import { useState } from "react";
import QRCode from "qrcode";
import { saveSurvey } from "@/lib/api";
import { useStore } from "@/lib/store";
import { secondary } from "./ui";

/** Save the survey and show a link and QR code that open it on another device. */
export default function ShareSurvey() {
  const [shared, setShared] = useState<{ url: string; qr: string } | null>(null);
  const [state, setState] = useState<"idle" | "saving" | { error: string }>("idle");

  const share = async () => {
    setState("saving");
    try {
      const { roof, floors, obstructions, horizon, monthlyUnits, monthlyBill, quotedCost, discomId, sanctionedLoadKw } =
        useStore.getState();
      const { code } = await saveSurvey({
        roof,
        floors,
        obstructions,
        horizon,
        monthlyUnits,
        monthlyBill,
        quotedCost,
        discomId,
        sanctionedLoadKw,
      });
      const url = `${window.location.origin}${window.location.pathname}?s=${code}`;
      setShared({ url, qr: await QRCode.toDataURL(url, { margin: 1, width: 180 }) });
      setState("idle");
    } catch (err) {
      setState({ error: err instanceof Error ? err.message : "Couldn't save the survey." });
    }
  };

  return (
    <div className="space-y-3">
      <p className="text-sm text-slate-400">
        Save this survey to open it on your phone for the rooftop scan, or to send to family or an installer.
      </p>
      <button className={secondary} disabled={state === "saving"} onClick={share}>
        {state === "saving" ? "Saving…" : shared ? "Save again with latest changes" : "Save and get a link"}
      </button>
      {typeof state === "object" && <p className="text-xs text-rose-300">{state.error}</p>}
      {shared && (
        <div className="flex items-start gap-3">
          {/* eslint-disable-next-line @next/next/no-img-element -- a generated data URL, nothing to optimise */}
          <img src={shared.qr} alt="QR code that opens this survey" className="h-28 w-28 rounded-lg bg-white p-1" />
          <div className="min-w-0 space-y-2 text-xs text-slate-400">
            <p>Scan with your phone camera, or copy the link. It works for 90 days.</p>
            <p className="break-all text-slate-200">{shared.url}</p>
            <button className={secondary} onClick={() => void navigator.clipboard.writeText(shared.url)}>
              Copy link
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
