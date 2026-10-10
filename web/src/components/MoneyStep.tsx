"use client";

import { useEffect, useState } from "react";
import { fetchFinance, fetchPolicy, stateAt, type Finance, type PolicyOverview } from "@/lib/api";
import { centroid } from "@/lib/geo/local";
import type { ShadingResult } from "@/lib/solar/shading";
import { useStore } from "@/lib/store";
import { useSizing } from "@/lib/useSizing";
import { field, fmt, rupees, Stat } from "./ui";

const OTHER = "other";

function NumberField(props: { label: string; hint: string; value: number | null; onChange: (v: number | null) => void }) {
  return (
    <label className="flex items-center justify-between gap-3 text-sm text-slate-300">
      <span>
        {props.label}
        <span className="block text-xs text-slate-500">{props.hint}</span>
      </span>
      <span className="flex items-center gap-1">
        <span className="text-slate-500">₹</span>
        <input
          type="number"
          min={0}
          value={props.value ?? ""}
          placeholder="optional"
          onChange={(e) => props.onChange(e.target.value === "" ? null : Math.max(0, Number(e.target.value)))}
          className={`${field} w-28 text-right`}
        />
      </span>
    </label>
  );
}

export default function MoneyStep({ analysis }: { analysis: ShadingResult }) {
  const { roof, monthlyUnits, monthlyBill, quotedCost, discomId, setMoney } = useStore();
  const { sizing } = useSizing(analysis);
  const [policy, setPolicy] = useState<PolicyOverview | null>(null);
  const [result, setResult] = useState<{ finance: Finance } | { error: string } | null>(null);

  // Match the roof's state to a distributor once, unless the user already chose.
  useEffect(() => {
    if (!roof) return;
    let current = true;
    stateAt(centroid(roof))
      .then(fetchPolicy)
      .then((overview) => {
        if (!current) return;
        setPolicy(overview);
        if (useStore.getState().discomId === null) setMoney({ discomId: overview.matched ?? OTHER });
      })
      .catch((err: Error) => current && setResult({ error: err.message }));
    return () => {
      current = false;
    };
  }, [roof, setMoney]);

  const discom = discomId && discomId !== OTHER ? discomId : null;
  const ready = sizing && sizing.panels > 0 && monthlyUnits && (discom || monthlyBill);

  useEffect(() => {
    if (!ready || !sizing || !monthlyUnits) return;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      fetchFinance(
        {
          system_kw: sizing.systemKw,
          monthly_generation: sizing.monthlyKwh,
          monthly_usage: monthlyUnits,
          discom_id: discom,
          monthly_bill: monthlyBill,
          quoted_cost: quotedCost,
        },
        controller.signal,
      )
        .then((finance) => setResult({ finance }))
        .catch((err: Error) => {
          if (err.name !== "AbortError") setResult({ error: err.message });
        });
    }, 300);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [ready, sizing, monthlyUnits, discom, monthlyBill, quotedCost]);

  if (!monthlyUnits) return <p className="text-sm text-slate-400">Enter your monthly units in step 4 first.</p>;

  const f = ready && result && "finance" in result ? result.finance : null;
  const netMetering = discom ? policy?.discoms[discom]?.net_metering : null;

  return (
    <div className="space-y-4">
      <label className="flex items-center justify-between gap-3 text-sm text-slate-300">
        Electricity company
        <select value={discomId ?? OTHER} onChange={(e) => setMoney({ discomId: e.target.value })} className={`${field} max-w-[210px]`}>
          {Object.entries(policy?.discoms ?? {}).map(([id, d]) => (
            <option key={id} value={id}>
              {d.name}
            </option>
          ))}
          <option value={OTHER}>Another company</option>
        </select>
      </label>
      <NumberField
        label="Typical monthly bill"
        hint="Makes savings match what you really pay"
        value={monthlyBill}
        onChange={(v) => setMoney({ monthlyBill: v })}
      />
      <NumberField
        label="A vendor's quote"
        hint="Before subsidy, if you have one"
        value={quotedCost}
        onChange={(v) => setMoney({ quotedCost: v })}
      />

      {!discom && !monthlyBill && (
        <p className="text-sm text-amber-300">
          We don&apos;t have tariff data for your electricity company yet. Enter your typical monthly bill to see savings.
        </p>
      )}
      {result && "error" in result && <p className="text-xs text-rose-300">{result.error}</p>}

      {f && sizing && (
        <>
          <div className="grid grid-cols-2 gap-2">
            <Stat
              label={f.cost_is_quote ? "Your quote" : "Likely system cost"}
              value={rupees(f.gross_cost)}
              sub={
                f.cost_is_quote
                  ? `typical range ${rupees(f.gross_cost_range[0])}–${rupees(f.gross_cost_range[1])}`
                  : `could be ${rupees(f.gross_cost_range[0])}–${rupees(f.gross_cost_range[1])}`
              }
            />
            <Stat label="Government subsidy" value={`− ${rupees(f.subsidy)}`} sub="PM Surya Ghar" />
            <Stat label="You pay" value={rupees(f.net_cost)} sub="after subsidy" />
            <Stat
              label="Pays for itself in"
              value={f.payback_years === null ? "25+ years" : `${fmt(f.payback_years, 1)} years`}
            />
            <Stat
              label="Yearly bill"
              value={rupees(f.bill_after)}
              sub={`down from ${rupees(f.bill_before)}`}
            />
            <Stat label="Saved over 25 years" value={rupees(f.lifetime_savings)} sub="after paying for the system" />
          </div>

          {f.cost_is_quote && (f.gross_cost < f.gross_cost_range[0] || f.gross_cost > f.gross_cost_range[1]) && (
            <p className="text-xs text-amber-300">
              This quote is {f.gross_cost > f.gross_cost_range[1] ? "above" : "below"} the usual range for a{" "}
              {fmt(sizing.systemKw, 1)} kW system. Ask the vendor what it includes, such as panel brand, structure
              height and warranty.
            </p>
          )}
          {netMetering && (
            <p className="text-xs text-slate-400">
              {netMetering.summary}{" "}
              <a href={netMetering.source} target="_blank" rel="noreferrer" className="text-sky-400 underline">
                Source
              </a>
              {!netMetering.verified && " (not yet confirmed against the regulator's order)"}
            </p>
          )}
          <ul className="space-y-1 text-xs text-slate-500">
            {f.notes.map((note) => (
              <li key={note}>{note}</li>
            ))}
            <li>
              Assumes electricity prices rise 2% a year and panels lose 0.5% of output a year. Leaves out
              maintenance and a replacement inverter, usually needed once in 25 years.
            </li>
            {policy && (
              <li>
                Subsidy rules as of {policy.as_of}.{" "}
                <a href={policy.central_subsidy.apply_at} target="_blank" rel="noreferrer" className="text-sky-400 underline">
                  Apply on the national portal
                </a>
              </li>
            )}
          </ul>
        </>
      )}
    </div>
  );
}
