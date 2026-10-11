"use client";

import { useEffect, useState } from "react";
import type { RateLimit } from "@/lib/api";
import { useStore } from "@/lib/store";
import { fmt, Icon } from "./ui";

/** What keeps working while a limit is in force, by which allowance ran out. */
const STILL_WORKS: Record<string, string> = {
  measure: "Measuring a new property waits until then. A property already measured keeps working: its shadows, panel layout and money figures are worked out in your browser.",
  ai: "Everything else keeps working: measuring, shadows, the panel layout and the money figures don't use AI.",
  speech: "You can still type your question.",
};

function headline(info: RateLimit): string {
  if (info.scope === "busy") return "homesol is busy right now";
  return info.scope === "everyone" ? "homesol has reached today's limit" : "You've reached this hour's limit";
}

function explanation(info: RateLimit): string {
  const count = info.limit === null ? "" : `${fmt(info.limit)} `;
  if (info.scope === "busy") return "Too many people are using it at once.";
  if (info.scope === "everyone") return `All visitors together have used today's ${count}${info.kind}. They reset at midnight UTC.`;
  return `You've used this hour's ${count}${info.kind}. Each visitor has an hourly allowance, so the public demo stays open for everyone.`;
}

function countdown(ms: number): string {
  const s = Math.max(0, Math.ceil(ms / 1000));
  if (s < 120) return `${s} s`;
  const m = Math.ceil(s / 60);
  return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${m % 60} min`;
}

/** Says plainly when a rate limit has been reached, what still works, and counts down to when it lifts. */
export default function RateLimitBanner() {
  const limit = useStore((s) => s.limit);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!limit) return;
    const tick = () => {
      const t = Date.now();
      setNow(t);
      if (t >= limit.until) useStore.setState({ limit: null });
    };
    const timer = setInterval(tick, 1000);
    return () => clearInterval(timer);
  }, [limit]);

  if (!limit) return null;
  const { info, until } = limit;
  const at = new Date(until).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  return (
    <div role="alert" className="flex shrink-0 items-start gap-3 border-b border-error/30 bg-error-container px-4 py-3 text-on-error-container">
      <Icon name="hourglass_top" className="mt-0.5 text-[22px]" />
      <div className="min-w-0 flex-1 text-sm leading-5">
        <p className="font-medium">
          {headline(info)} <span className="font-normal">· back in {countdown(until - now)}{info.scope !== "busy" && `, at ${at}`}</span>
        </p>
        <p className="mt-0.5">
          {explanation(info)} {info.id && STILL_WORKS[info.id]}
        </p>
      </div>
      <button
        className="grid h-8 w-8 shrink-0 place-items-center rounded-full hover:bg-on-error-container/10"
        aria-label="Dismiss"
        onClick={() => useStore.setState({ limit: null })}
      >
        <Icon name="close" className="text-[20px]" />
      </button>
    </div>
  );
}
