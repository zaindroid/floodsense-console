import ahr from "../fixtures/ahr_2021.json";
import type { DischargeDailyRow, ValenciaPoint } from "../types/views";
import type { DisasterEvent } from "./disasterReplay";
import type { AskContext } from "./askContext";
import type { DeskRoute } from "./route";

export type EventId = DisasterEvent["eventId"];

/** The event the console opens on: Ahr first, as the Replay page always did (Germany-first demo). */
export const DEFAULT_EVENT_ID: EventId = "EMSR517";

export const EVENT_META: Record<EventId, { short: string; region: string }> = {
  EMSR517: { short: "Ahr 2021", region: "Germany · Ahr valley" },
  EMSR773: { short: "Valencia 2024", region: "Spain · Valencia" },
};

/** Header subtitle: a short product tagline, the same on every page. Page context lives in the context strip. */
export const PRODUCT_TAGLINE = "Explainable flood risk for Europe";

export function headerSubtitle(): string {
  return PRODUCT_TAGLINE;
}

/** The Now page's own subtitle (#78 live-watch wording), shown in the context strip on Now. */
export const NOW_SUBTITLE = "Live · Europe live watch";

/** One map point with real coordinates from the seed rows. */
export interface MapPoint {
  point_id: string;
  name: string;
  /** Short permanent map label, e.g. "Paiporta" or "Dernau". */
  label: string;
  lat: number;
  lon: number;
}

/** Valencia: municipality from the prep CSV (valencia_points). */
export function valenciaMapPoints(points: readonly ValenciaPoint[]): MapPoint[] {
  return points.map((p) => ({
    point_id: p.point_id,
    name: p.name,
    label: p.municipality || p.name.replace(/ centre$/i, ""),
    lat: p.lat,
    lon: p.lon,
  }));
}

/** Ahr: the AHR01–AHR04 points of ingestion/prep/ahr_hazard.py, the same rows as floodsense_seed (migrations 051/052). */
export function ahrMapPoints(): MapPoint[] {
  return ahr.points.map((p) => ({ point_id: p.point_id, name: p.name, label: p.name, lat: p.lat, lon: p.lon }));
}

/** Ahr daily GloFAS discharge, from the same seed rows. */
export function ahrDischarge(): DischargeDailyRow[] {
  return ahr.discharge_daily.map((r) => ({ ...r })) as DischargeDailyRow[];
}

/** Popup / tooltip text for one point on one day. */
export function pointPopupText(point: MapPoint, m3s: number | null, day: string): string {
  const value = m3s === null ? "no discharge row" : `${m3s.toFixed(1)} m³/s`;
  return `${point.point_id} · ${point.name} · ${value} on ${day}`;
}

/** Ahr opens on the GloFAS peak day of the replay window. */
export const AHR_DEFAULT_DATE = "2021-07-14";

/** [[south, west], [north, east]] around the points, or null with none. */
export function boundsOf(points: readonly { lat: number; lon: number }[]): [[number, number], [number, number]] | null {
  if (points.length === 0) return null;
  const lats = points.map((p) => p.lat);
  const lons = points.map((p) => p.lon);
  return [
    [Math.min(...lats), Math.min(...lons)],
    [Math.max(...lats), Math.max(...lons)],
  ];
}

/** The selected point and replay date of the active event, for the Ask `context`. */
export function activeEventSelection(
  eventId: EventId,
  valencia: { date: string; pointId: string; points: readonly { point_id: string; name: string }[] },
  ahrSel: { date: string; pointId: string },
): { event_id: EventId; replay_date: string; point_id: string; place?: string } {
  if (eventId === "EMSR517") {
    const point = ahrMapPoints().find((p) => p.point_id === ahrSel.pointId);
    return { event_id: eventId, replay_date: ahrSel.date, point_id: ahrSel.pointId, place: point?.name };
  }
  const point = valencia.points.find((p) => p.point_id === valencia.pointId);
  return { event_id: eventId, replay_date: valencia.date, point_id: valencia.pointId, place: point?.name };
}

/** Whether a page shows the selected event, so its Ask `context` may name it. Insurer only; the citizen side routes by question. */
export function pageShowsEvent(route: DeskRoute, eventId: EventId): boolean {
  if (route.role !== "insurer") return false;
  if (route.page === "replay" || route.page === "sites") return true;
  // Portfolio shows an event only when it has an insured book (EMSR773).
  return route.page === "portfolio" && eventId === "EMSR773";
}

/** The event a page shows: the selected one where `pageShowsEvent`, else Valencia (EMSR773). */
export function shownEventId(route: DeskRoute, eventId: EventId): EventId {
  return pageShowsEvent(route, eventId) ? eventId : "EMSR773";
}

/** Pure: the Ask `context` for the page. Event fields only where the page shows that event. */
export function screenContextFor(
  route: DeskRoute,
  eventId: EventId,
  valencia: { date: string; pointId: string; points: readonly { point_id: string; name: string }[] },
  ahrSel: { date: string; pointId: string },
): AskContext {
  if (pageShowsEvent(route, eventId)) {
    return { role: route.role, page: route.page, ...activeEventSelection(eventId, valencia, ahrSel) };
  }
  const point = valencia.points.find((p) => p.point_id === valencia.pointId);
  return { role: route.role, page: route.page, point_id: valencia.pointId, place: point?.name };
}

/** Pages that show a replayed past event: Replay on both desks and insurer Sites. Citizen pages are live-first. */
export function pageShowsReplay(route: DeskRoute): boolean {
  if (route.page === "replay") return true;
  return route.role === "insurer" && route.page === "sites";
}

/** Citizen pages that follow the chosen place: "Live data", or the replay strip when the place is a past flood. */
export const CITIZEN_LIVE_PAGES: readonly string[] = ["overview", "area", "actions", "evidence"];
export const CITIZEN_LIVE_TEXT = "Live data";

const EVENT_NAME: Record<EventId, string> = { EMSR517: "Ahr", EMSR773: "Valencia" };

export type ContextStrip =
  | { kind: "live"; text: string }
  | { kind: "replay"; text: string; eventId: EventId; date: string }
  | { kind: "none"; text: "" };

function plainDay(day: string): string {
  const d = new Date(`${day}T00:00:00Z`);
  if (Number.isNaN(d.getTime())) return day;
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
}

/**
 * Pure: the context strip under the header. "Live data" on Now; a plain "Viewing: ... (replay of a past event)"
 * on pages that show a replayed event; nothing elsewhere. Replay and Sites follow the selected event (Replay on
 * both desks); citizen Overview and My area always show Valencia 2024.
 */
export function replayBarView(
  route: DeskRoute,
  eventId: EventId,
  valencia: { date: string },
  ahrSel: { date: string },
  /** Citizen live pages: the replay event of the chosen place, or null for a live place (or none chosen). */
  citizenReplay: EventId | null = null,
): ContextStrip {
  if (route.page === "now") return { kind: "live", text: NOW_SUBTITLE };
  if (route.role === "citizen" && CITIZEN_LIVE_PAGES.includes(route.page)) {
    if (!citizenReplay) return { kind: "live", text: CITIZEN_LIVE_TEXT };
  } else if (!pageShowsReplay(route)) return { kind: "none", text: "" };
  const shown: EventId =
    route.role === "citizen" && route.page !== "replay" ? (citizenReplay ?? "EMSR773") : route.page === "replay" || route.page === "sites" ? eventId : "EMSR773";
  const date = shown === "EMSR517" ? ahrSel.date : valencia.date;
  return {
    kind: "replay",
    eventId: shown,
    date,
    text: `Viewing: ${EVENT_NAME[shown]} flood · ${plainDay(date)} (replay of a past event)`,
  };
}
