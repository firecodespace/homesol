export const fmt = (n: number, digits = 0) => n.toLocaleString("en-IN", { maximumFractionDigits: digits });
export const rupees = (n: number) => `₹${fmt(Math.round(n))}`;

export const primary = "md-filled";
export const secondary = "md-tonal";
export const outlined = "md-outlined";
export const textButton = "md-text";
export const field = "md-field-dense";

export function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="md-card">
      <p className="md-label">{label}</p>
      <p className="mt-1 text-[22px] leading-7 text-on-surface">{value}</p>
      {sub && <p className="md-supporting mt-0.5">{sub}</p>}
    </div>
  );
}
