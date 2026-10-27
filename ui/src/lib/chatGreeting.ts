import { NEXT_48H_QUESTION } from "../api/ask";
import { EVENT_META, type EventId } from "./events";
import type { DeskRoute } from "./route";

export interface ChatGreeting {
  text: string;
  /** Three questions that fit the page. A click sends one as typed. */
  suggestions: readonly string[];
}

const CITIZEN_TEXT = "Hi! I'm FloodSense. Ask me about flood risk where you are — every answer cites its sources.";
const INSURER_TEXT = "Hi! I'm FloodSense. Ask me about your portfolio's flood exposure — every answer cites its sources.";

const CITIZEN_SUGGESTIONS = [
  "Is Paiporta at risk of flooding right now?",
  "How high is the Rhine at Köln today?",
  "What happened in the Ahr valley in July 2021?",
] as const;

const INSURER_SUGGESTIONS = [
  "Which of our insured sites are exposed in Valencia?",
  "How much insured value sits inside the flood footprint?",
  "Which sites should we review first?",
] as const;

const INSURER_AHR_SUGGESTIONS = [
  "Which of our sites lie in the Ahr valley flood footprint?",
  "How high did the Ahr rise at Altenahr on 14 July 2021?",
  "What happened in the Ahr valley in July 2021?",
] as const;

/**
 * Pure: the opening message for a role and page. `shownEvent` is the event the page shows
 * (`shownEventId`), so an Ahr page never suggests a Valencia exposure question.
 */
export function greetingFor(route: DeskRoute, shownEvent: EventId = "EMSR773"): ChatGreeting {
  if (route.role === "insurer")
    return {
      text: INSURER_TEXT,
      suggestions: route.page !== "now" && shownEvent === "EMSR517" ? INSURER_AHR_SUGGESTIONS : INSURER_SUGGESTIONS,
    };
  if (route.page === "now")
    return {
      text: CITIZEN_TEXT,
      suggestions: [NEXT_48H_QUESTION, CITIZEN_SUGGESTIONS[1], "Is Paiporta at risk in the next 48 hours?"],
    };
  return { text: CITIZEN_TEXT, suggestions: CITIZEN_SUGGESTIONS };
}

/** Pure: the label of the button that re-asks a declined question on the event that holds it. */
export function switchEventLabel(eventId: string): string | null {
  const meta = EVENT_META[eventId as EventId];
  return meta ? `Ask about ${meta.short} instead` : null;
}

/** Pure: the event a declined run's switch button re-asks on, or null when no button shows. */
export function switchTarget(run: { status: string | null; elsewhere?: string | null }): string | null {
  if (run.status !== "out_of_scope" || !run.elsewhere) return null;
  return switchEventLabel(run.elsewhere) ? run.elsewhere : null;
}
