export const fmt = (n: number, digits = 0) => n.toLocaleString("en-IN", { maximumFractionDigits: digits });
export const rupees = (n: number) => `₹${fmt(Math.round(n))}`;

const button =
  "rounded-lg px-3 py-2 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-40";
export const primary = `${button} bg-amber-400 text-slate-950 hover:bg-amber-300`;
export const secondary = `${button} border border-slate-700 text-slate-200 hover:bg-slate-800`;
export const field =
  "rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-slate-100 placeholder:text-slate-600";

export function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-lg bg-slate-900 p-3">
      <p className="text-xs text-slate-500">{label}</p>
      <p className="mt-1 text-xl font-semibold text-slate-50">{value}</p>
      {sub && <p className="text-xs text-slate-500">{sub}</p>}
    </div>
  );
}
