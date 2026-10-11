"use client";

import type { ReactNode } from "react";
import type { MeasuredSun } from "@/lib/api";
import { centroid, localFrame, polygonArea } from "@/lib/geo/local";
import { AREA_PER_KW_M2, USABLE_ACCESS, type ShadingResult } from "@/lib/solar/shading";
import { PANEL_KW, PERFORMANCE_RATIO } from "@/lib/solar/sizing";
import { useStore } from "@/lib/store";
import type { Money } from "@/lib/useMoney";
import { fmt, rupees, Stat } from "./ui";

const SQFT_PER_M2 = 10.7639;
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** One group of results: what the numbers are, then the numbers, then how they were worked out. */
function Group({ title, description, children }: { title: string; description: string; children: ReactNode }) {
  return (
    <section className="border-b border-outline-variant px-4 py-5">
      <h2 className="md-title">{title}</h2>
      <p className="md-body mb-4 mt-1">{description}</p>
      {children}
    </section>
  );
}

const Notes = ({ children }: { children: ReactNode }) => (
  <ul className="md-supporting mt-3 list-disc space-y-1.5 pl-4">{children}</ul>
);

function Plan({ money, isLand }: { money: Money; isLand: boolean }) {
  const { sizing, finance: f } = money;
  if (!sizing) return null;
  if (sizing.panels === 0) {
    return (
      <section className="m-4 rounded-lg bg-error-container p-4 text-on-error-container">
        <p className="md-title text-on-error-container">
          The sunny part of this {isLand ? "land" : "roof"} is too small for even one panel.
        </p>
      </section>
    );
  }
  return (
    <section className="m-4 rounded-lg bg-primary-container p-4 text-on-primary-container">
      <p className="md-label text-on-primary-container">YOUR SOLAR PLAN</p>
      <p className="md-headline mt-1 text-on-primary-container">
        {fmt(sizing.systemKw, 1)} kW, {sizing.panels} panels
      </p>
      <p className="mt-1 text-sm">
        Covers {fmt(sizing.coverage * 100)}% of your electricity, making about {fmt(sizing.annualKwh / 12)} units a month.
        {sizing.limitedBy === "roof" && " That is all the sunny area can hold."}
      </p>
      {f ? (
        <dl className="mt-4 grid grid-cols-3 gap-2 text-center">
          {[
            [rupees(f.net_cost), `you pay, after ${rupees(f.subsidy)} subsidy`],
            [rupees(f.first_year_savings), "saved in the first year"],
            [f.payback_years === null ? "25+ yrs" : `${fmt(f.payback_years, 1)} yrs`, "to pay for itself"],
          ].map(([value, label]) => (
            <div key={label} className="rounded-md bg-surface-container-lowest/70 px-2 py-3">
              <dd className="text-lg font-medium">{value}</dd>
              <dt className="mt-0.5 text-xs leading-4">{label}</dt>
            </div>
          ))}
        </dl>
      ) : (
        <p className="mt-3 text-xs">
          {money.error ?? "Choose your electricity company or enter your bill under “Cost details” to see the money figures."}
        </p>
      )}
    </section>
  );
}

function Property({ analysis, google }: { analysis: ShadingResult | null; google: MeasuredSun | null }) {
  const { roof, floors, autoFound } = useStore();
  if (!roof) return null;
  const frame = localFrame(centroid(roof));
  const area = analysis?.roofAreaM2 ?? polygonArea(roof.map(frame.toXY));
  const measured = google?.available ? google : null;
  const isLand = measured?.surface === "ground";
  const upFloors = measured?.floors ?? floors;

  return (
    <Group
      title={isLand ? "Open land" : "Your roof"}
      description={
        isLand
          ? "This area is at ground level, so it is treated as open land for ground-mounted panels."
          : "The surface panels would sit on, and how high it is."
      }
    >
      <div className="grid grid-cols-2 gap-2">
        <Stat label="Area" value={`${fmt(area)} m²`} sub={`${fmt(area * SQFT_PER_M2)} sq ft`} />
        {!isLand && (
          <Stat
            label="Height"
            value={measured?.roof_height_m != null ? `${fmt(measured.roof_height_m)} m` : `≈ ${floors * 3} m`}
            sub={`about ${upFloors} floor${upFloors === 1 ? "" : "s"} up`}
          />
        )}
      </div>
      <Notes>
        {measured ? (
          <>
            <li>
              {autoFound ? "Outlined and measured" : "Measured"} from Google&apos;s 3D survey of this spot
              {measured.imagery_date ? `, using imagery dated ${measured.imagery_date}` : ""}.
            </li>
            {measured.structures_m2 >= 2 && (
              <li>
                {fmt(measured.structures_m2)} m² inside the outline stands higher (
                {isLand ? "buildings" : "stair rooms, tanks"}) and is left out of the area.
              </li>
            )}
          </>
        ) : (
          <li>
            {google && !google.available ? google.reason : "Checking for a 3D survey of this spot…"} The area is from the
            outline, and the height from the number of floors.
          </li>
        )}
      </Notes>
    </Group>
  );
}

function Sun({ analysis, google, isLand }: { analysis: ShadingResult; google: MeasuredSun | null; isLand: boolean }) {
  const obstructions = useStore((s) => s.obstructions);
  const measured = Boolean(google?.available);
  const unmeasured = obstructions.filter((o) => !o.heightM).length;
  return (
    <Group
      title={isLand ? "Sun on this land" : "Sun on your roof"}
      description="How much of it gets full sun over a year, and how much is lost to shade."
    >
      <div className="grid grid-cols-2 gap-2">
        <Stat label="Share of full sun" value={`${fmt(analysis.meanAccess * 100)}%`} sub="averaged over the area" />
        <Stat label="Room for up to" value={`${fmt(analysis.capacityKw, 1)} kW`} sub="of panels" />
        <Stat
          label="Good for panels"
          value={`${fmt(analysis.usableAreaM2)} m²`}
          sub={`${fmt(analysis.usableAreaM2 * SQFT_PER_M2)} sq ft`}
        />
        <Stat
          label="Lost to shade"
          value={`${fmt(Math.max(0, Math.round(analysis.roofAreaM2 - analysis.usableAreaM2)))} m²`}
        />
      </div>
      <div className="mt-4">
        <div className="h-2.5 rounded-full bg-gradient-to-r from-[#3b0764] via-[#c2410c] via-60% to-[#fef9c3]" />
        <div className="md-supporting mt-1 flex justify-between">
          <span>Mostly shaded</span>
          <span>Full sun all year</span>
        </div>
      </div>
      <Notes>
        <li>
          {measured
            ? "Shade from surrounding buildings and trees is measured, from Google's 3D model of the area."
            : "Shade is estimated from the obstructions you marked and the skyline scan, if you did one."}
        </li>
        <li>
          An area counts as good for panels when it gets at least {USABLE_ACCESS * 100}% of full sun. Each kW needs about{" "}
          {AREA_PER_KW_M2} m², including the gaps between panels.
        </li>
        {unmeasured > 0 && !measured && (
          <li className="text-error">
            {unmeasured} obstruction{unmeasured > 1 ? "s have" : " has"} no height yet and{" "}
            {unmeasured > 1 ? "are" : "is"} left out.
          </li>
        )}
      </Notes>
    </Group>
  );
}

function System({ analysis, money }: { analysis: ShadingResult; money: Money }) {
  const { sizing } = money;
  if (!sizing || sizing.panels === 0) return null;
  const lowest = sizing.monthlyKwh.indexOf(Math.min(...sizing.monthlyKwh));
  const highest = sizing.monthlyKwh.indexOf(Math.max(...sizing.monthlyKwh));
  return (
    <Group title="The system you need" description="Sized to make as much electricity in a year as you use.">
      <div className="grid grid-cols-2 gap-2">
        <Stat label="System size" value={`${fmt(sizing.systemKw, 1)} kW`} sub={`${sizing.panels} panels`} />
        <Stat label="Covers" value={`${fmt(sizing.coverage * 100)}%`} sub="of your yearly usage" />
        <Stat label="Generates" value={`${fmt(sizing.annualKwh / 12)} units`} sub="a month on average" />
        <Stat
          label="Space needed"
          value={`${fmt(sizing.systemKw * AREA_PER_KW_M2)} m²`}
          sub={`of ${fmt(analysis.usableAreaM2)} m² available`}
        />
      </div>
      <Notes>
        <li>
          Expect about {fmt(sizing.monthlyKwh[highest])} units in {MONTHS[highest]} and {fmt(sizing.monthlyKwh[lowest])}{" "}
          in {MONTHS[lowest]}.
          {sizing.limitedBy === "roof" && " The sunny area is the limit here: a bigger system would not fit."}
        </li>
        <li>
          Uses 25 years of NASA sunlight records for this spot, {PANEL_KW * 1000} W panels, and{" "}
          {PERFORMANCE_RATIO * 100}% of that sunlight reaching your meter after heat, dust and wiring losses.
        </li>
      </Notes>
    </Group>
  );
}

function MoneyResults({ money }: { money: Money }) {
  const { sizing, finance: f, policy, discom } = money;
  const monthlyBill = useStore((s) => s.monthlyBill);
  if (!sizing || sizing.panels === 0) return null;
  const netMetering = discom ? policy?.discoms[discom]?.net_metering : null;

  return (
    <Group title="Cost and savings" description="What it costs, what the government pays, and what your bill drops to.">
      {!f && (
        <p className="text-sm text-on-surface">
          {money.error ??
            (!discom && !monthlyBill
              ? "We don't have tariff data for your electricity company yet. Enter your typical monthly bill under “Cost details”."
              : "Working out the figures…")}
        </p>
      )}
      {f && (
        <>
          <div className="grid grid-cols-2 gap-2">
            <Stat
              label={f.cost_is_quote ? "Your quote" : "Likely price"}
              value={rupees(f.gross_cost)}
              sub={`usual range ${rupees(f.gross_cost_range[0])}–${rupees(f.gross_cost_range[1])}`}
            />
            <Stat label="Subsidy" value={`− ${rupees(f.subsidy)}`} sub="PM Surya Ghar" />
            <Stat label="You pay" value={rupees(f.net_cost)} sub="after subsidy" />
            <Stat
              label="Pays for itself in"
              value={f.payback_years === null ? "25+ years" : `${fmt(f.payback_years, 1)} years`}
            />
            <Stat label="Yearly bill" value={rupees(f.bill_after)} sub={`down from ${rupees(f.bill_before)}`} />
            <Stat label="Saved in 25 years" value={rupees(f.lifetime_savings)} sub="after paying for the system" />
          </div>
          {f.cost_is_quote && (f.gross_cost < f.gross_cost_range[0] || f.gross_cost > f.gross_cost_range[1]) && (
            <p className="mt-3 rounded-md bg-error-container p-3 text-sm text-on-error-container">
              This quote is {f.gross_cost > f.gross_cost_range[1] ? "above" : "below"} the usual range for a{" "}
              {fmt(sizing.systemKw, 1)} kW system. Ask the vendor what it includes, such as panel brand, structure height
              and warranty.
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
              Assumes electricity prices rise 2% a year and panels lose 0.5% of output a year. Leaves out maintenance and
              a replacement inverter, usually needed once in 25 years.
            </li>
            {policy && (
              <li>
                Subsidy rules as checked on {policy.as_of}.{" "}
                <a
                  href={policy.central_subsidy.apply_at}
                  target="_blank"
                  rel="noreferrer"
                  className="text-primary underline"
                >
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
  if (chat.turns.length === 0 && !chat.error) return null;
  return (
    <Group title="Answers" description="From homesol's advisor, using the figures above.">
      <div className="space-y-3">
        {chat.turns.map((turn, i) => (
          <p
            key={i}
            className={`whitespace-pre-wrap text-sm ${
              turn.role === "user"
                ? "ml-8 rounded-lg rounded-br-xs bg-primary px-4 py-2 text-on-primary"
                : "mr-4 rounded-lg rounded-bl-xs bg-surface-container-high px-4 py-3 text-on-surface"
            }`}
          >
            {turn.text}
          </p>
        ))}
        {chat.waiting && <p className="md-supporting">Checking your figures and the rules…</p>}
        {chat.error && <p className="text-xs text-error">{chat.error}</p>}
      </div>
    </Group>
  );
}

function Shared() {
  const shared = useStore((s) => s.shared);
  if (!shared) return null;
  return (
    <Group title="Your saved link" description="Opens this survey on any device for the next 90 days.">
      <div className="flex items-start gap-3">
        {/* eslint-disable-next-line @next/next/no-img-element -- a generated data URL, nothing to optimise */}
        <img src={shared.qr} alt="QR code that opens this survey" className="h-28 w-28 rounded-md bg-white p-1" />
        <div className="min-w-0 space-y-2">
          <p className="md-supporting">Scan with your phone camera, or copy the link.</p>
          <p className="break-all text-xs text-on-surface">{shared.url}</p>
          <button className="md-text h-8" onClick={() => void navigator.clipboard.writeText(shared.url)}>
            Copy link
          </button>
        </div>
      </div>
    </Group>
  );
}

/** Right panel: every number and what it means. Nothing here is an input. */
export default function ResultsPanel({
  analysis,
  google,
  money,
}: {
  analysis: ShadingResult | null;
  google: MeasuredSun | null;
  money: Money;
}) {
  const roof = useStore((s) => s.roof);
  const monthlyUnits = useStore((s) => s.monthlyUnits);
  const isLand = google?.available ? google.surface === "ground" : false;

  return (
    <aside className="w-full shrink-0 overflow-y-auto bg-surface lg:h-full lg:w-[380px] lg:border-l lg:border-outline-variant">
      {!roof && (
        <div className="px-4 py-6">
          <h2 className="md-title">Your results will appear here</h2>
          <p className="md-body mt-2">Once you pick your property on the map, this side shows:</p>
          <ul className="md-body mt-3 list-disc space-y-2 pl-5">
            <li>the size and height of your roof</li>
            <li>how much of it gets full sun</li>
            <li>the system size that matches your electricity use</li>
            <li>the price, subsidy, savings and payback</li>
          </ul>
        </div>
      )}
      {roof && monthlyUnits && analysis && <Plan money={money} isLand={isLand} />}
      {roof && <Property analysis={analysis} google={google} />}
      {roof && analysis && <Sun analysis={analysis} google={google} isLand={isLand} />}
      {roof && analysis && !monthlyUnits && (
        <div className="px-4 py-5">
          <p className="md-body">
            Add your electricity use on the left to see the system you need and what it costs and saves.
          </p>
        </div>
      )}
      {roof && analysis && monthlyUnits && <System analysis={analysis} money={money} />}
      {roof && analysis && monthlyUnits && <MoneyResults money={money} />}
      <Answers />
      <Shared />
    </aside>
  );
}
