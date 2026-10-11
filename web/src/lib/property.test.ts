import { beforeAll, describe, expect, it, vi } from "vitest";
import { placeFrom } from "./api";

describe("placeFrom", () => {
  it("puts the street and neighbourhood on one line and the rest on another", () => {
    expect(
      placeFrom({
        housenumber: "42",
        street: "12th Main Road",
        district: "Indiranagar",
        city: "Bengaluru",
        county: "Bangalore North",
        state: "Karnataka",
        postcode: "560038",
        country: "India",
        countrycode: "in",
      }),
    ).toEqual({
      countryCode: "IN",
      country: "India",
      state: "Karnataka",
      currency: "INR",
      address: "42 12th Main Road, Indiranagar",
      region: "Bengaluru, Karnataka 560038, India",
    });
  });

  it("drops a name that only repeats the street", () => {
    const place = placeFrom({ name: "Waverley Street", housenumber: "525", street: "Waverley Street", city: "Palo Alto", state: "California", country: "United States", countrycode: "US" });
    expect(place?.address).toBe("525 Waverley Street");
    expect(place?.currency).toBe("USD");
  });

  it("keeps a building's own name ahead of its street", () => {
    const place = placeFrom({ name: "Sunrise Apartments", street: "Ngong Road", city: "Nairobi", country: "Kenya", countrycode: "KE" });
    expect(place?.address).toBe("Sunrise Apartments, Ngong Road");
    expect(place?.region).toBe("Nairobi, Kenya");
  });

  it("leaves out parts the region line already says", () => {
    const place = placeFrom({ district: "Jaipur", city: "Jaipur", state: "Rajasthan", country: "India", countrycode: "IN" });
    expect(place?.address).toBeNull();
    expect(place?.region).toBe("Jaipur, Rajasthan, India");
  });

  it("falls back to the county when there is no town", () => {
    expect(placeFrom({ county: "Jaisalmer", state: "Rajasthan", country: "India", countrycode: "IN" })?.region).toBe(
      "Jaisalmer, Rajasthan, India",
    );
  });

  it("knows no place without a country", () => {
    expect(placeFrom({ city: "Somewhere" })).toBeNull();
    expect(placeFrom(undefined)).toBeNull();
  });
});

describe("choosing another property", () => {
  let useStore: typeof import("./store").useStore;

  beforeAll(async () => {
    // The store saves itself to the browser's storage; an in-memory stand-in keeps it quiet here.
    const saved = new Map<string, string>();
    vi.stubGlobal("localStorage", {
      getItem: (k: string) => saved.get(k) ?? null,
      setItem: (k: string, v: string) => void saved.set(k, v),
      removeItem: (k: string) => void saved.delete(k),
    });
    ({ useStore } = await import("./store"));
  });

  it("starts with none of the last household's figures", () => {
    const fresh = useStore.getState();
    useStore.setState({
      roof: [
        [77.59, 12.97],
        [77.5901, 12.97],
        [77.5901, 12.9701],
      ],
      floors: 5,
      monthlyUnits: 349,
      monthlyBill: 3100,
      quotedCost: 180000,
      sanctionedLoadKw: 5,
      discomId: "msedcl",
      chat: { turns: [{ role: "user", text: "Is solar worth it?" }], waiting: false, error: null },
    });

    useStore.getState().clearRoof();

    const now = useStore.getState();
    expect(now.roof).toBeNull();
    expect(now.monthlyUnits).toBeNull();
    expect(now.monthlyBill).toBeNull();
    expect(now.quotedCost).toBeNull();
    expect(now.sanctionedLoadKw).toBeNull();
    expect(now.discomId).toBeNull();
    expect(now.floors).toBe(fresh.floors);
    expect(now.chat.turns).toEqual([]);
  });

  it("keeps how the map is shown", () => {
    useStore.setState({ view: "shadows", showPanels: false, preview: { month: 6, minutes: 600 } });
    useStore.getState().clearRoof();
    const now = useStore.getState();
    expect(now.view).toBe("shadows");
    expect(now.showPanels).toBe(false);
    expect(now.preview).toEqual({ month: 6, minutes: 600 });
  });
});
