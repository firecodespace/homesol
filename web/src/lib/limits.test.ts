import { afterEach, describe, expect, it, vi } from "vitest";
import { askAdvisor, fetchFinance, fetchSite, onRateLimit, RateLimitError, type RateLimit } from "./api";

function respond(status: number, body: unknown, headers: Record<string, string> = {}) {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(body), { status, headers })));
}

afterEach(() => vi.unstubAllGlobals());

describe("a request refused for a rate limit", () => {
  it("becomes a RateLimitError carrying what the API said, and tells the page", async () => {
    respond(429, {
      detail: {
        message: "You've used this hour's 60 live measurements. You can carry on in 23 minutes.",
        id: "measure",
        scope: "visitor",
        kind: "live measurements",
        limit: 60,
        window: "hour",
        retry_after: 1380,
      },
    });
    const heard: RateLimit[] = [];
    const stop = onRateLimit((l) => heard.push(l));
    const err = await fetchSite({ point: [76.77, 30.72] }).catch((e: unknown) => e);
    stop();
    expect(err).toBeInstanceOf(RateLimitError);
    expect((err as Error).message).toBe("You've used this hour's 60 live measurements. You can carry on in 23 minutes.");
    expect(heard).toEqual([
      { message: (err as Error).message, scope: "visitor", id: "measure", kind: "live measurements", limit: 60, retryAfterS: 1380 },
    ]);
  });

  it("knows the daily cap for everyone from a visitor's own allowance", async () => {
    respond(429, { detail: { message: "homesol has used today's 600 AI answers and readings for all visitors.", id: "ai", scope: "everyone", kind: "AI answers and readings", limit: 600, retry_after: 7200 } });
    const err = (await askAdvisor("Is it worth it?", {}, []).catch((e: unknown) => e)) as RateLimitError;
    expect(err.limit.scope).toBe("everyone");
    expect(err.limit.retryAfterS).toBe(7200);
  });

  it("reads the Lambda's own concurrency cap as busy, waiting as long as it asks", async () => {
    respond(429, { Message: "Rate Exceeded." }, { "Retry-After": "30" });
    const err = (await fetchSite({ point: [0, 0] }).catch((e: unknown) => e)) as RateLimitError;
    expect(err.limit.scope).toBe("busy");
    expect(err.limit.retryAfterS).toBe(30);
    expect(err.message).toMatch(/busy/);
  });

  it("leaves other errors as they were", async () => {
    respond(404, { detail: "No data for distributor 'x'." });
    const err = await fetchFinance({ system_kw: 3, monthly_generation: Array(12).fill(1), monthly_usage: 300, discom_id: "x", monthly_bill: null, quoted_cost: null, sanctioned_load_kw: null, country_code: "IN", currency: "INR" }).catch((e: unknown) => e);
    expect(err).not.toBeInstanceOf(RateLimitError);
    expect((err as Error).message).toBe("No data for distributor 'x'.");
  });
});
