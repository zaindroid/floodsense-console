import { describe, expect, it } from "vitest";
import { headerSubtitle, replayBarView, type EventId } from "./events";
import { CITIZEN_PAGES, INSURER_PAGES, type DeskRoute } from "./route";

const routes: DeskRoute[] = [
  ...CITIZEN_PAGES.map((page) => ({ role: "citizen" as const, page })),
  ...INSURER_PAGES.map((page) => ({ role: "insurer" as const, page })),
];
const events: EventId[] = ["EMSR517", "EMSR773"];

describe("header and context strip", () => {
  for (const route of routes) {
    for (const eventId of events) {
      it(`${route.role}/${route.page} on ${eventId}`, () => {
        expect(headerSubtitle()).toBe("Explainable flood risk for Europe");
        const bar = replayBarView(route, eventId, { date: "2024-10-29" }, { date: "2021-07-14" });
        if (route.page === "now") expect(bar.kind).toBe("live");
        if (bar.kind === "replay") expect(bar.text).toMatch(/^Viewing: (Valencia|Ahr) flood · .+ \(replay of a past event\)$/);
        if (bar.kind === "none") expect(bar.text).toBe("");
        expect(bar.text).not.toMatch(/EMSR|VAL\d|AHR\d|Paused/);
      });
    }
  }
});
