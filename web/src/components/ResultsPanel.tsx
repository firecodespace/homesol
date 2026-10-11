"use client";

import type { ReactNode } from "react";
import type { Analysis } from "@/lib/site/analysis";
import { PANEL_LONG_M, PANEL_SHORT_M, PANEL_WATTS } from "@/lib/site/panels";
import { PERFORMANCE_RATIO } from "@/lib/solar/sizing";
import { useStore } from "@/lib/store";
import { clockIn } from "@/lib/time";
import type { Money } from "@/lib/useMoney";
import { fmt, Icon, money as cash, Stat } from "./ui";

const SQFT_PER_M2 = 10.7639;
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const COMPASS = ["north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west"];
const compass = (bearing: number) => COMPASS[Math.round((((bearing % 360) + 360) % 360) / 45) % 8];

const SURFACE_NAMES = {
  roof: "Flat roof",
  sloped_roof: "Sloped roof",
  ground: "Open land",
  sloped_ground: "Sloping land",
} as const;

/** One group of results: what the numbers are, then the numbers, then how they were worked out. */
function Group({ icon, title, description, children }: { icon: string; title: string; description: string; children: ReactNode }) {
  return (
    <section className="rounded-lg bg-surface p-4">
      <div className="flex items-center gap-3">
        <Icon name={icon} className="text-primary" />
        <h2 className="md-title">{title}</h2>
      </div>
      <p className="md-body mt-2">{description}</p>
      <div className="mt-4">{children}</div>
    </section>
  );
}

const Stats = ({ children }: { children: ReactNode }) => <div className="grid grid-cols-2 gap-2">{children}</div>;
const Notes = ({ children }: { children: ReactNode }) => (
  <ul className="md-supporting mt-4 list-disc space-y-1.5 pl-4">{children}</ul>
);
const SubHeading = ({ children }: { children: ReactNode }) => <h3 className="md-label mb-2 mt-5 uppercase">{children}</h3>;

function Plan({ money, land }: { money: Money; land: boolean }) {
  const { sizing, finance: f } = money;
  if (!sizing) return null;
  if (sizing.panels === 0) {
    return (
      <section className="rounded-lg bg-error-container p-4 text-on-error-container">
        <p className="md-title text-on-error-container">
          No part of this {land ? "land" : "roof"} gets enough sun for a panel.
        </p>
      </section>
    );
  }
  const tiles: [string, string][] = f
    ? [
        [f.net_cost === null ? "—" : cash(f.net_cost, f.currency), f.subsidy ? `you pay, after ${cash(f.subsidy, f.currency)} subsidy` : "you pay"],
        [cash(f.first_year_savings, f.currency), "saved in the first year"],
        [f.payback_years === null ? (f.net_cost === null ? "—" : "25+ yrs") : `${fmt(f.payback_years, 1)} yrs`, "to pay for itself"],
      ]
    : [];
  return (
    <section className="rounded-lg bg-primary-container p-4 text-on-primary-container">
      <p className="md-label text-on-primary-container">YOUR SOLAR PLAN</p>
      <p className="mt-1 text-[28px] leading-9">
        {fmt(sizing.systemKw, 1)} kW · {sizing.panels} panels
      </p>
      <p className="mt-1 text-sm leading-5">
        Covers {fmt(sizing.coverage * 100)}% of your electricity, making about {fmt(sizing.annualKwh / 12)} units a month.
        {sizing.limitedBy === "roof" && " That is every sunny position there is."}
      </p>
      {f ? (
        <dl className="mt-4 grid grid-cols-3 gap-2">
          {tiles.map(([value, label]) => (
            <div key={label} className="flex flex-col rounded-md bg-surface/70 p-3">
              <dd className="text-lg leading-6 font-medium">{value}</dd>
              <dt className="mt-1 text-xs leading-4">{label}</dt>
            </div>
          ))}
        </dl>
      ) : (
        <p className="mt-3 text-sm">
          {money.error ??
            (money.hasPolicyData
              ? "Choose your electricity company or enter your bill under “Cost details” to see the money figures."
              : "Enter your typical monthly bill under “Cost details” to see savings.")}
        </p>
      )}
      {f && f.net_cost === null && (
        <p className="mt-3 text-xs">Enter a vendor&apos;s quote under “Cost details” to see the price and payback.</p>
      )}
    </section>
  );
}

function Property({ analysis }: { analysis: Analysis }) {
  const { model } = analysis;
  const s = model.surface;
  const land = s.kind.includes("ground");
  const sloped = s.kind.startsWith("sloped");
  return (
    <Group
      icon={land ? "landscape" : "roofing"}
      title="Your property"
      description={
        land
          ? "This area is at ground level, so it is planned as open land with ground-mounted panels."
          : "The surface panels would sit on."
      }
    >
      <Stats>
        <Stat label="Surface" value={SURFACE_NAMES[s.kind]} sub={s.found_by === "tap" ? "found from your tap" : "from your outline"} />
        <Stat label="Area" value={`${fmt(analysis.areaM2)} m²`} sub={`${fmt(analysis.areaM2 * SQFT_PER_M2)} sq ft`} />
        {!land && (
          <Stat label="Height" value={`${fmt(s.height_m)} m`} sub={`about ${s.floors} floor${s.floors === 1 ? "" : "s"} up`} />
        )}
        {sloped && <Stat label="Slope" value={`${fmt(s.tilt_deg)}°`} sub={`facing ${s.faces}`} />}
      </Stats>
      <Notes>
        {model.measured ? (
          <li>
            Measured from Google&apos;s 3D survey{model.imageryDate ? `, imagery dated ${model.imageryDate}` : ""}. Anything
            built or grown since then is not in it.
          </li>
        ) : (
          <li>Estimated from your outline and the number of floors, because no 3D survey exists here.</li>
        )}
        {model.measured && model.obstructions.some((o) => o.on_surface) && (
          <li>Structures standing on it, such as stair rooms and tanks, are left out of the area.</li>
        )}
      </Notes>
    </Group>
  );
}

function Sun({ analysis, zone }: { analysis: Analysis; zone: string }) {
  const { model, shade, panelShade } = analysis;
  const names = useStore((s) => s.names);
  const land = model.surface.kind.includes("ground");
  const word = land ? "land" : "roof";
  const northern = analysis.at[1] >= 0;
  const seasons: [string, number][] = [
    ["Winter", northern ? 12 : 6],
    ["Spring and autumn", 3],
    ["Summer", northern ? 6 : 12],
  ];
  const causes = shade
    ? [
        ...model.obstructions.map((o) => ({ name: names[o.id]?.name ?? o.name, detail: o.on_surface ? `on the ${word}, ${o.height_above_m} m tall` : `${Math.round(o.distance_m)} m to the ${o.direction}, ${o.height_above_m} m above the ${word}`, share: shade.blame.get(o.id) ?? 0, onSurface: o.on_surface, kind: o.kind })),
        { name: land ? "The lie of the land" : "Steps and edges of the roof itself", detail: "low sun catches on its uneven parts", share: shade.blame.get(1) ?? 0, onSurface: true, kind: "self" },
        { name: "Smaller things nearby", detail: "parapets, low walls and neighbours only a little taller", share: shade.blame.get(0) ?? 0, onSurface: false, kind: "other" },
      ]
        .filter((c) => c.share >= 0.03)
        .sort((a, b) => b.share - a.share)
        .slice(0, 5)
    : [];

  return (
    <Group icon="wb_sunny" title="Sun and shade" description={`How much sun the ${word} gets over a year, what blocks it, and when.`}>
      <Stats>
        <Stat label="Share of full sun" value={`${fmt(analysis.meanAccess * 100)}%`} sub={`averaged over the ${word}`} />
        <Stat label="In good sun" value={`${fmt(analysis.sunnyAreaM2)} m²`} sub={`of ${fmt(analysis.areaM2)} m²`} />
      </Stats>
      <div className="mt-3">
        <div className="h-2 rounded-full bg-gradient-to-r from-[#3b0764] via-[#c2410c] via-50% to-[#fef9c3]" />
        <div className="md-supporting mt-1 flex justify-between">
          <span>Mostly shaded</span>
          <span>Full sun all year</span>
        </div>
      </div>

      {shade && (
        <>
          <SubHeading>What shades it</SubHeading>
          {causes.length === 0 ? (
            <p className="text-sm text-on-surface">Almost nothing. No building, tree or structure blocks a meaningful share of its sun.</p>
          ) : (
            <ul className="space-y-3">
              {causes.map((c) => (
                <li key={c.name + c.detail}>
                  <div className="flex items-baseline justify-between gap-3">
                    <span className="text-sm text-on-surface">{c.name}</span>
                    <span className="text-sm font-medium text-on-surface">{fmt(c.share * 100)}%</span>
                  </div>
                  <div className="mt-1 h-1 rounded-full bg-surface-container-highest">
                    <div
                      className="h-full rounded-full"
                      style={{ width: `${Math.round(c.share * 100)}%`, background: c.kind === "tree" ? "#16a34a" : c.onSurface ? "#dc2626" : "#2563eb" }}
                    />
                  </div>
                  <p className="md-supporting mt-1">{c.detail}</p>
                </li>
              ))}
            </ul>
          )}

          <SubHeading>When the panel positions are clear of shadows</SubHeading>
          <dl className="divide-y divide-outline-variant rounded-md border border-outline-variant">
            {seasons.map(([season, month]) => {
              const day = (panelShade ?? shade).fullSun[month - 1];
              return (
                <div key={season} className="flex items-baseline justify-between gap-3 px-3 py-2">
                  <dt className="text-sm text-on-surface">
                    {season} <span className="md-supporting">(21 {MONTHS[month - 1]})</span>
                  </dt>
                  <dd className="text-sm font-medium text-on-surface">
                    {day.from && day.to ? `${clockIn(zone, day.from)} – ${clockIn(zone, day.to)}` : "Never fully clear"}
                  </dd>
                </div>
              );
            })}
          </dl>
        </>
      )}

      <Notes>
        {model.measured ? (
          <>
            <li>The share of full sun is Google&apos;s yearly sunlight measurement, which includes clouds and shade from everything around.</li>
            <li>
              What shades it, and when, comes from simulating the sun every half hour across the year over the measured heights
              within about 60 m. That simulation loses {fmt(shade ? shade.lost * 100 : 0)}% of the direct sun, against{" "}
              {fmt((1 - analysis.meanAccess) * 100)}% in Google&apos;s measurement. Pick “Shadows” on the map to watch it.
            </li>
          </>
        ) : (
          <li>Estimated from the obstructions you marked and the skyline scan, if you did one.</li>
        )}
      </Notes>
    </Group>
  );
}

function Panels({ analysis, money }: { analysis: Analysis; money: Money }) {
  const { layout } = analysis;
  const chosen = money.sizing?.panels ?? 0;
  const land = analysis.model.surface.kind.includes("ground");
  return (
    <Group
      icon="solar_power"
      title="Where the panels go"
      description="Each rectangle on the map is one panel, drawn to size in a place it fits and gets good sun."
    >
      <Stats>
        <Stat label="Room for" value={`${layout.good} panels`} sub={`${fmt(analysis.capacityKw, 1)} kW in good sun`} />
        <Stat
          label="In your plan"
          value={money.sizing ? `${chosen} panels` : "—"}
          sub={money.sizing ? "the sunniest positions" : "add your electricity use"}
        />
      </Stats>
      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-on-surface-variant">
        <span className="flex items-center gap-2">
          <span className="inline-block h-3 w-5 rounded-[2px] border border-white bg-[#0b2a6f]" /> In your plan
        </span>
        <span className="flex items-center gap-2">
          <span className="inline-block h-3 w-5 rounded-[2px] border border-on-surface-variant bg-[#0b2a6f]/20" /> Room for more
        </span>
      </div>
      <Notes>
        <li>
          {layout.mounting === "tilted rows"
            ? `Panels stand in rows tilted ${layout.tiltDeg}° and facing ${compass(layout.facingDeg)}, ${fmt(layout.rowPitchM, 1)} m from one row to the next so a row does not shade the one behind it in winter.`
            : `Panels lie flat against the slope, tilted ${fmt(layout.tiltDeg)}° and facing ${compass(layout.facingDeg)}.`}
        </li>
        <li>
          Each panel is {PANEL_WATTS} W and {PANEL_LONG_M.toFixed(2)} m × {PANEL_SHORT_M.toFixed(2)} m. A half-metre strip is kept clear
          along every edge{land ? "" : " and around rooftop structures"}.
        </li>
        <li>An installer will adjust the exact positions on site; use this to judge what fits and where.</li>
      </Notes>
    </Group>
  );
}

function System({ money }: { money: Money }) {
  const { sizing } = money;
  if (!sizing || sizing.panels === 0) return null;
  const lowest = sizing.monthlyKwh.indexOf(Math.min(...sizing.monthlyKwh));
  const highest = sizing.monthlyKwh.indexOf(Math.max(...sizing.monthlyKwh));
  return (
    <Group icon="bolt" title="What it generates" description="Sized to make as much electricity in a year as you use.">
      <Stats>
        <Stat label="Each month" value={`${fmt(sizing.annualKwh / 12)} units`} sub="on average" />
        <Stat label="Covers" value={`${fmt(sizing.coverage * 100)}%`} sub="of your yearly use" />
        <Stat label={`Best month (${MONTHS[highest]})`} value={`${fmt(sizing.monthlyKwh[highest])} units`} />
        <Stat label={`Leanest month (${MONTHS[lowest]})`} value={`${fmt(sizing.monthlyKwh[lowest])} units`} />
      </Stats>
      <Notes>
        <li>
          Uses 25 years of NASA sunlight records for this spot, the sun each chosen panel position gets, and{" "}
          {PERFORMANCE_RATIO * 100}% of that reaching your meter after heat, dust and wiring losses.
        </li>
        {sizing.limitedBy === "roof" && <li>The sunny area is the limit: a bigger system would not fit.</li>}
      </Notes>
    </Group>
  );
}

function MoneyResults({ money }: { money: Money }) {
  const { sizing, finance: f, policy, discom } = money;
  const monthlyBill = useStore((s) => s.monthlyBill);
  if (!sizing || sizing.panels === 0) return null;
  const netMetering = discom ? policy?.discoms[discom]?.net_metering : null;
  const range = f?.gross_cost_range;

  return (
    <Group icon="payments" title="Cost and savings" description="What it costs, what any subsidy pays, and what your bill drops to.">
      {!f && (
        <p className="text-sm text-on-surface">
          {money.error ??
            (!discom && !monthlyBill
              ? money.hasPolicyData
                ? "We don't have tariff data for your electricity company yet. Enter your typical monthly bill under “Cost details”."
                : "Enter your typical monthly bill under “Cost details” to see savings."
              : "Working out the figures…")}
        </p>
      )}
      {f && (
        <>
          <Stats>
            <Stat
              label={f.cost_is_quote ? "Your quote" : "Likely price"}
              value={f.gross_cost === null ? "—" : cash(f.gross_cost, f.currency)}
              sub={range ? `usual range ${cash(range[0], f.currency)}–${cash(range[1], f.currency)}` : f.gross_cost === null ? "enter a vendor's quote" : undefined}
            />
            <Stat label="Subsidy" value={f.subsidy ? `− ${cash(f.subsidy, f.currency)}` : "—"} sub={f.subsidy ? "PM Surya Ghar" : "none included"} />
            <Stat label="You pay" value={f.net_cost === null ? "—" : cash(f.net_cost, f.currency)} sub={f.subsidy ? "after subsidy" : undefined} />
            <Stat
              label="Pays for itself in"
              value={f.payback_years === null ? (f.net_cost === null ? "—" : "25+ years") : `${fmt(f.payback_years, 1)} years`}
            />
            <Stat label="Yearly bill" value={cash(f.bill_after, f.currency)} sub={`down from ${cash(f.bill_before, f.currency)}`} />
            <Stat
              label="Saved in 25 years"
              value={f.lifetime_savings === null ? "—" : cash(f.lifetime_savings, f.currency)}
              sub={f.lifetime_savings === null ? undefined : "after paying for the system"}
            />
          </Stats>
          {f.cost_is_quote && f.gross_cost !== null && range && (f.gross_cost < range[0] || f.gross_cost > range[1]) && (
            <p className="mt-3 rounded-md bg-error-container p-3 text-sm text-on-error-container">
              This quote is {f.gross_cost > range[1] ? "above" : "below"} the usual range for a {fmt(sizing.systemKw, 1)} kW system.
              Ask the vendor what it includes, such as panel brand, structure height and warranty.
            </p>
          )}
          <Notes>
            {netMetering && (
              <li>
                {netMetering.summary}{" "}
                <a href={netMetering.source} target="_blank" rel="noreferrer" className="text-primary underline">
                  Source
                </a>
                {!netMetering.verified && " (not yet confirmed against the regulator's order)"}
              </li>
            )}
            {f.notes.map((note) => (
              <li key={note}>{note}</li>
            ))}
            <li>
              Assumes electricity prices rise 2% a year and panels lose 0.5% of output a year. Leaves out maintenance and a
              replacement inverter, usually needed once in 25 years.
            </li>
            {policy && (
              <li>
                Subsidy rules as checked on {policy.as_of}.{" "}
                <a href={policy.central_subsidy.apply_at} target="_blank" rel="noreferrer" className="text-primary underline">
                  Apply on the national portal
                </a>
              </li>
            )}
          </Notes>
        </>
      )}
    </Group>
  );
}

function Answers() {
  const chat = useStore((s) => s.chat);
  if (chat.turns.length === 0 && !chat.error && !chat.waiting) return null;
  return (
    <Group icon="forum" title="Answers" description="From homesol's advisor, using the figures on this page.">
      <div className="space-y-3">
        {chat.turns.map((turn, i) => (
          <p
            key={i}
            className={`whitespace-pre-wrap text-sm leading-5 ${
              turn.role === "user"
                ? "ml-8 rounded-lg rounded-br-xs bg-primary px-4 py-2 text-on-primary"
                : "mr-4 rounded-lg rounded-bl-xs bg-surface-container-high px-4 py-3 text-on-surface"
            }`}
          >
            {turn.text}
          </p>
        ))}
        {chat.waiting && <p className="md-supporting">Checking your figures and the rules…</p>}
        {chat.error && <p className="text-sm text-error">{chat.error}</p>}
      </div>
    </Group>
  );
}

function Shared() {
  const shared = useStore((s) => s.shared);
  if (!shared) return null;
  return (
    <Group icon="qr_code_2" title="Your saved link" description="Opens this survey on any device for the next 90 days.">
      <div className="grid grid-cols-[auto_1fr] items-start gap-3">
        {/* eslint-disable-next-line @next/next/no-img-element -- a generated data URL, nothing to optimise */}
        <img src={shared.qr} alt="QR code that opens this survey" className="h-28 w-28 rounded-md bg-white p-1" />
        <div className="min-w-0">
          <p className="md-supporting">Scan with your phone camera, or copy the link.</p>
          <p className="mt-2 break-all text-xs text-on-surface">{shared.url}</p>
          <button className="md-text mt-1 h-8 px-2" onClick={() => void navigator.clipboard.writeText(shared.url)}>
            Copy link
          </button>
        </div>
      </div>
    </Group>
  );
}

/** Right panel: every number and what it means. Nothing here is an input. */
export default function ResultsPanel({ analysis, money, zone }: { analysis: Analysis | null; money: Money; zone: string }) {
  const roof = useStore((s) => s.roof);
  const monthlyUnits = useStore((s) => s.monthlyUnits);
  const loading = useStore((s) => s.siteStatus.state === "loading");
  const land = analysis?.model.surface.kind.includes("ground") ?? false;

  return (
    <aside className="w-full shrink-0 overflow-x-hidden bg-surface-container-low lg:h-full lg:w-[400px] lg:overflow-y-auto">
      <div className="space-y-3 p-3">
        {!roof && (
          <section className="rounded-lg bg-surface p-4">
            <h2 className="md-title">Your results will appear here</h2>
            <p className="md-body mt-2">Once you pick your property on the map, this side shows:</p>
            <ul className="mt-3 space-y-3">
              {[
                ["roofing", "The size, height and slope of your roof or land"],
                ["wb_sunny", "How much sun it gets, what shades it, and when"],
                ["solar_power", "Exactly where panels fit, drawn on the map"],
                ["payments", "Price, subsidy, savings and payback"],
              ].map(([icon, text]) => (
                <li key={icon} className="flex items-center gap-3 text-sm text-on-surface">
                  <Icon name={icon} className="text-on-surface-variant" />
                  {text}
                </li>
              ))}
            </ul>
          </section>
        )}
        {roof && !analysis && (
          <section className="rounded-lg bg-surface p-4">
            <h2 className="md-title">{loading ? "Measuring your property…" : "Preparing…"}</h2>
            <p className="md-body mt-2">
              Building a 3D model from Google&apos;s survey: the surface, everything on and around it, and a year of sun and shadow.
              This takes a few seconds.
            </p>
          </section>
        )}
        {analysis && monthlyUnits && <Plan money={money} land={land} />}
        {analysis && <Property analysis={analysis} />}
        {analysis && <Sun analysis={analysis} zone={zone} />}
        {analysis && <Panels analysis={analysis} money={money} />}
        {analysis && !monthlyUnits && (
          <p className="md-body px-1">Add your electricity use on the left to see the system you need and what it costs and saves.</p>
        )}
        {analysis && monthlyUnits && <System money={money} />}
        {analysis && monthlyUnits && <MoneyResults money={money} />}
        <Answers />
        <Shared />
      </div>
    </aside>
  );
}
