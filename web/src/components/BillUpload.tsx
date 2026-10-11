"use client";

import { useRef, useState } from "react";
import { readBill, type BillReading } from "@/lib/api";
import { useStore } from "@/lib/store";
import { fmt, rupees, secondary } from "./ui";

const MAX_SIDE = 1800;

/** Shrink a photo to a size the bill reader accepts, as base64 JPEG. */
async function toJpeg(file: File): Promise<string> {
  const bitmap = await createImageBitmap(file);
  const scale = Math.min(1, MAX_SIDE / Math.max(bitmap.width, bitmap.height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(bitmap.width * scale);
  canvas.height = Math.round(bitmap.height * scale);
  canvas.getContext("2d")!.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL("image/jpeg", 0.85).split(",")[1];
}

/** Fill in units, bill amount and electricity company from a photo of the bill. */
export default function BillUpload() {
  const input = useRef<HTMLInputElement>(null);
  const [state, setState] = useState<"idle" | "reading" | { error: string } | { read: BillReading }>("idle");

  const onFile = async (file: File | undefined) => {
    if (!file) return;
    setState("reading");
    try {
      const read = await readBill(await toJpeg(file));
      const { setMonthlyUnits, setMoney } = useStore.getState();
      if (read.units_per_month) setMonthlyUnits(read.units_per_month);
      setMoney({
        ...(read.bill_per_month ? { monthlyBill: read.bill_per_month } : {}),
        ...(read.discom_id ? { discomId: read.discom_id } : {}),
        ...(read.sanctioned_load_kw ? { sanctionedLoadKw: read.sanctioned_load_kw } : {}),
      });
      setState({ read });
    } catch (err) {
      setState({ error: err instanceof Error ? err.message : "The bill could not be read." });
    } finally {
      if (input.current) input.current.value = "";
    }
  };

  const read = typeof state === "object" && "read" in state ? state.read : null;
  return (
    <div className="md-card-outlined">
      <input
        ref={input}
        type="file"
        accept="image/*"
        className="hidden"
        aria-label="Photo of your electricity bill"
        onChange={(e) => void onFile(e.target.files?.[0])}
      />
      <button className={secondary} disabled={state === "reading"} onClick={() => input.current?.click()}>
        {state === "reading" ? "Reading your bill…" : "Fill this in from a photo of my bill"}
      </button>
      <p className="mt-2 text-xs text-on-surface-variant">
        The photo is read once and not stored. Your name, address and consumer number are not kept.
      </p>
      {typeof state === "object" && "error" in state && <p className="mt-2 text-xs text-error">{state.error}</p>}
      {read && (
        <p className="mt-2 text-xs text-on-surface">
          Read from the bill:{" "}
          {[
            read.units_per_month && `${fmt(read.units_per_month)} units a month`,
            read.bill_per_month && `${rupees(read.bill_per_month)} a month`,
            read.distributor,
            read.sanctioned_load_kw && `${fmt(read.sanctioned_load_kw, 1)} kW sanctioned load`,
          ]
            .filter(Boolean)
            .join(" · ")}
          {read.basis && ` (from ${read.basis})`}. Check these against your bill and correct anything below.
        </p>
      )}
    </div>
  );
}
