export const fmt = (n: number, digits = 0) => n.toLocaleString("en-IN", { maximumFractionDigits: digits });
/** An amount of money in its own currency, without decimals; Indian digit grouping for rupees. */
export const money = (n: number, currency = "INR") =>
  new Intl.NumberFormat(currency === "INR" ? "en-IN" : "en", { style: "currency", currency, maximumFractionDigits: 0 }).format(n);

/** A Material Symbols icon, by its ligature name. Decorative unless given a label by its parent. */
export function Icon({ name, className = "" }: { name: string; className?: string }) {
  return (
    <span className={`material-symbols-outlined select-none leading-none ${className}`} aria-hidden>
      {name}
    </span>
  );
}

export const primary = "md-filled";
export const secondary = "md-tonal";
export const outlined = "md-outlined";
export const textButton = "md-text";
export const field = "md-field-dense";

export function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="md-card h-full">
      <p className="md-label">{label}</p>
      <p className="mt-1 text-xl leading-7 text-on-surface">{value}</p>
      {sub && <p className="md-supporting mt-0.5">{sub}</p>}
    </div>
  );
}
