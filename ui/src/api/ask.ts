import { apiBaseUrl } from "./config";
import { adoptRunBody, type RecordedRun } from "./replay";
import type { LlmProvider } from "../lib/llmProvider";

export const DEFAULT_EVENT_ID = "EMSR773";

export interface AskInput {
  question: string;
  eventId?: string;
  provider: LlmProvider;
  /** Providers GET /config listed. The provider is sent only when it is one of them. */
  allowedProviders: readonly string[];
  threadId?: string | null;
}

const THREAD_ID = /^[A-Za-z0-9_-]{1,64}$/;

/** Pure: the thread a follow-up continues. Only a live run's own, well-formed thread_id; never a replay's or cache hit's. */
export function followUpThreadId(previous: Pick<RecordedRun, "servedFrom" | "threadId"> | null): string | null {
  if (!previous || previous.servedFrom !== "live" || !previous.threadId) return null;
  return THREAD_ID.test(previous.threadId) ? previous.threadId : null;
}

export const MAX_TURNS = 20;

/** Pure: the conversation capped to the newest MAX_TURNS. */
export function capTurns<T>(turns: T[], max = MAX_TURNS): T[] {
  return turns.length > max ? turns.slice(turns.length - max) : turns;
}

/** Pure: the POST /runs body. */
export function buildRunRequest(input: AskInput): Record<string, string> {
  const question = input.question.trim();
  const body: Record<string, string> = {
    question,
    event_id: input.eventId || DEFAULT_EVENT_ID,
    doc_query: question,
  };
  if (input.allowedProviders.includes(input.provider)) body.llm_provider = input.provider;
  if (input.threadId) body.thread_id = input.threadId;
  return body;
}

export type AskResult =
  | { ok: true; run: RecordedRun }
  | { ok: false; kind: "rate_limited" | "provider" | "server" | "bad_response" | "network" | "aborted"; message: string };

const detailOf = (body: unknown): string | null => {
  const d = (body as { detail?: unknown } | null)?.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) return d.map((x) => (x as { msg?: unknown })?.msg).filter((m) => typeof m === "string").join("; ") || null;
  return null;
};

/** Pure: map an HTTP answer to a result the popup shows. */
export function mapRunResponse(status: number, body: unknown, retryAfter: string | null): AskResult {
  if (status === 429) {
    const secs = retryAfter && /^\d+$/.test(retryAfter.trim()) ? Number(retryAfter.trim()) : null;
    return {
      ok: false,
      kind: "rate_limited",
      message: secs !== null ? `Too many questions. Try again in ${secs} s.` : "Too many questions. Try again shortly.",
    };
  }
  if (status === 422) {
    return { ok: false, kind: "provider", message: `Request refused: ${detailOf(body) ?? "this model provider is not allowed here."}` };
  }
  if (status >= 500) {
    return { ok: false, kind: "server", message: `The service failed (${status})${detailOf(body) ? `: ${detailOf(body)}` : ""}.` };
  }
  if (status < 200 || status >= 300) {
    return { ok: false, kind: "server", message: `Request failed (${status})${detailOf(body) ? `: ${detailOf(body)}` : ""}.` };
  }
  const rec = body && typeof body === "object" && !Array.isArray(body) ? (body as Record<string, unknown>) : null;
  const runId = rec && typeof rec.run_id === "string" ? rec.run_id : "";
  const run = rec ? adoptRunBody(rec, runId) : null;
  if (!run) return { ok: false, kind: "bad_response", message: "The answer came back without a usable summary or label." };
  return { ok: true, run };
}

/** Badge text for an adopted run. A replay or cache hit is never called live. */
export function runBadge(run: RecordedRun): string {
  if (run.servedFrom === "live") {
    const model = run.modelIds[run.modelIds.length - 1];
    return model ? `Live · ${model}` : "Live";
  }
  if (run.servedFrom === "cache") return run.label || "Cached answer · not live";
  return run.label || `Replay · recorded run ${run.runId} · not live`;
}

/** POST /runs. Synchronous on the API side: it returns when the run reaches the approval interrupt. */
export async function askFloodSense(input: AskInput, signal?: AbortSignal, base = apiBaseUrl()): Promise<AskResult> {
  let response: Response;
  try {
    response = await fetch(`${base}/runs`, {
      method: "POST",
      credentials: "omit",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(buildRunRequest(input)),
      signal,
    });
  } catch (error) {
    if (signal?.aborted) return { ok: false, kind: "aborted", message: "Cancelled." };
    return { ok: false, kind: "network", message: `Could not reach the API (${(error as Error)?.message ?? "network error"}). The run may still have started; check the Approvals page.` };
  }
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  return mapRunResponse(response.status, body, response.headers.get("Retry-After"));
}
