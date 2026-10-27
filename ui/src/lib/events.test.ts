import { describe, expect, it } from "vitest";
import valencia from "../fixtures/valencia_points.json";
import type { ValenciaPoint } from "../types/views";
import {
  activeEventSelection,
  screenContextFor,
  ahrDischarge,
  ahrMapPoints,
  boundsOf,
  DEFAULT_EVENT_ID,
  headerSubtitle,
  pointPopupText,
  valenciaMapPoints,
} from "./events";
import { ahrFixture } from "./replaySource";

describe("headerSubtitle", () => {
  it("is the product tagline, not an event id", () => {
    expect(headerSubtitle()).toBe("Explainable flood risk for Europe");
    expect(headerSubtitle()).not.toMatch(/EMSR|replay/i);
  });
  it("defaults to Ahr, as Replay always opened", () => {
    expect(DEFAULT_EVENT_ID).toBe("EMSR517");
  });
  it("the Ask selection follows the active event", () => {
    const val = { date: "2024-10-29", pointId: "VAL01", points: [{ point_id: "VAL01", name: "Paiporta centre" }] };
    const ahrSel = { date: "2021-07-14", pointId: "AHR04" };
    expect(activeEventSelection("EMSR517", val, ahrSel)).toEqual({
      event_id: "EMSR517",
      replay_date: "2021-07-14",
      point_id: "AHR04",
      place: "Dernau",
    });
    expect(activeEventSelection("EMSR773", val, ahrSel)).toEqual({
      event_id: "EMSR773",
      replay_date: "2024-10-29",
      point_id: "VAL01",
      place: "Paiporta centre",
    });
  });
});

describe("event map points", () => {
  it("Ahr points are the seed AHR01-AHR04 with real coordinates, AHR04 labelled Dernau", () => {
    const points = ahrMapPoints();
    expect(points.map((p) => p.point_id)).toEqual(["AHR01", "AHR02", "AHR03", "AHR04"]);
    const dernau = points.find((p) => p.point_id === "AHR04");
    expect(dernau?.label).toBe("Dernau");
    expect(dernau?.lat).toBeCloseTo(50.53, 3);
    expect(dernau?.lon).toBeCloseTo(7.05, 3);
    for (const p of points) {
      expect(p.lat).toBeGreaterThan(50.4);
      expect(p.lat).toBeLessThan(50.6);
    }
  });

  it("Ahr discharge holds every point on the peak day", () => {
    const peak = ahrDischarge().filter((r) => r.date === "2021-07-14");
    expect(peak.map((r) => r.point_id).sort()).toEqual(["AHR01", "AHR02", "AHR03", "AHR04"]);
  });

  it("the replay fixture names AHR04 Dernau too", () => {
    expect(ahrFixture().points.find((p) => p.point_id === "AHR04")?.name).toBe("Dernau");
  });

  it("Valencia labels are the municipality, not the code", () => {
    const points = valenciaMapPoints(valencia as ValenciaPoint[]);
    expect(points.find((p) => p.point_id === "VAL01")?.label).toBe("Paiporta");
    expect(points.every((p) => !/^\d+$/.test(p.label))).toBe(true);
  });

  it("bounds wrap every point, null with none", () => {
    expect(boundsOf([])).toBeNull();
    expect(boundsOf([{ lat: 1, lon: 5 }, { lat: 3, lon: 2 }])).toEqual([
      [1, 2],
      [3, 5],
    ]);
  });

  it("popup text carries the code and the value", () => {
    const [p] = ahrMapPoints();
    expect(pointPopupText(p, 249.61, "14 Jul")).toBe("AHR01 · Altenahr · 249.6 m³/s on 14 Jul");
    expect(pointPopupText(p, null, "14 Jul")).toContain("no discharge row");
  });
});

describe("screenContextFor", () => {
  const val = { date: "2024-10-29", pointId: "VAL01", points: [{ point_id: "VAL01", name: "Paiporta centre" }] };
  const ahrSel = { date: "2021-07-14", pointId: "AHR04" };
  const plain = (role: string, page: string) => ({ role, page, point_id: "VAL01", place: "Paiporta centre" });

  it.each(["now", "approvals", "alerts", "review"] as const)("insurer %s carries no event fields", (page) => {
    for (const ev of ["EMSR517", "EMSR773"] as const) {
      expect(screenContextFor({ role: "insurer", page }, ev, val, ahrSel)).toEqual(plain("insurer", page));
    }
  });

  it.each(["now", "replay", "overview", "area", "actions", "evidence"] as const)("citizen %s carries no event fields", (page) => {
    expect(screenContextFor({ role: "citizen", page }, "EMSR517", val, ahrSel)).toEqual(plain("citizen", page));
  });

  it.each(["replay", "sites"] as const)("insurer %s carries the active event", (page) => {
    expect(screenContextFor({ role: "insurer", page }, "EMSR517", val, ahrSel)).toEqual({
      role: "insurer",
      page,
      event_id: "EMSR517",
      replay_date: "2021-07-14",
      point_id: "AHR04",
      place: "Dernau",
    });
    expect(screenContextFor({ role: "insurer", page }, "EMSR773", val, ahrSel).event_id).toBe("EMSR773");
  });

  it("portfolio carries the event only when it has a book", () => {
    expect(screenContextFor({ role: "insurer", page: "portfolio" }, "EMSR517", val, ahrSel)).toEqual(plain("insurer", "portfolio"));
    expect(screenContextFor({ role: "insurer", page: "portfolio" }, "EMSR773", val, ahrSel)).toEqual({
      role: "insurer",
      page: "portfolio",
      event_id: "EMSR773",
      replay_date: "2024-10-29",
      point_id: "VAL01",
      place: "Paiporta centre",
    });
  });
});
