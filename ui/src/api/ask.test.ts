import { afterEach, describe, expect, it, vi } from "vitest";
import { askFloodSense, buildRunRequest, capTurns, followUpThreadId, mapRunResponse, runBadge } from "./ask";

const runBody = (over: Record<string, unknown> = {}) => ({
  run_id: "r1",
  thread_id: "t1",
  status: "awaiting_approval",
  served_from: "live",
  label: { live: true, kind: "live", text: null },
  model_ids: ["nvidia/nemotron", "claude-sonnet-x"],
  summary: "Discharge peaked.",
  claims: [{ claim_id: "C1", text: "Peak 471 m3/s.", citations: [{ citation_id: "a", layer: "a", title: "hazard" }] }],
  trace: [{ seq: 1, node: "scope", summary: "ok" }],
  ...over,
});

describe("buildRunRequest", () => {
  it("sends the provider only when /config listed it", () => {
    const base = { question: " Where? ", provider: "anthropic" as const };
    expect(buildRunRequest({ ...base, allowedProviders: ["nightshift"] })).toEqual({
      question: "Where?",
      doc_query: "Where?",
    });
    expect(buildRunRequest({ ...base, allowedProviders: ["nightshift", "anthropic"] }).llm_provider).toBe("anthropic");
  });
  it("carries thread_id and the event", () => {
    const body = buildRunRequest({
      question: "and Paiporta?",
      eventId: "EMSR517",
      provider: "nightshift",
      allowedProviders: ["nightshift"],
      threadId: "t1",
    });
    expect(body.thread_id).toBe("t1");
    expect(body.event_id).toBe("EMSR517");
    expect(buildRunRequest({ question: "q", provider: "nightshift", allowedProviders: [], threadId: null })).not.toHaveProperty(
      "thread_id",
    );
  });
});

describe("mapRunResponse", () => {
  it("adopts a live run with the model id", () => {
    const result = mapRunResponse(201, runBody(), null);
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.run.servedFrom).toBe("live");
    expect(result.run.threadId).toBe("t1");
    expect(result.run.status).toBe("awaiting_approval");
    expect(runBadge(result.run)).toBe("Live · claude-sonnet-x");
  });
  it("never calls a replay or cache hit live", () => {
    const replay = mapRunResponse(
      200,
      runBody({ served_from: "replay", label: { text: "Replay of a recorded run from 10:00 · not live" } }),
      null,
    );
    expect(replay.ok && runBadge(replay.run)).toBe("Replay of a recorded run from 10:00 · not live");
    const cache = mapRunResponse(200, runBody({ served_from: "cache", label: {} }), null);
    expect(cache.ok && runBadge(cache.run)).toMatch(/^Cached answer · not live/);
    expect(cache.ok && runBadge(cache.run)).not.toMatch(/Live/);
  });
  it("refuses a body with no served_from", () => {
    expect(mapRunResponse(201, runBody({ served_from: undefined }), null).ok).toBe(false);
  });
  it("maps 429 with Retry-After", () => {
    const r = mapRunResponse(429, { detail: "slow down" }, "30");
    expect(r).toMatchObject({ ok: false, kind: "rate_limited" });
    expect(!r.ok && r.message).toContain("30 s");
  });
  it("maps 422 and 5xx", () => {
    expect(mapRunResponse(422, { detail: "llm_provider anthropic is not enabled" }, null)).toMatchObject({
      ok: false,
      kind: "provider",
    });
    const s = mapRunResponse(503, { detail: "agents unreachable" }, null);
    expect(s).toMatchObject({ ok: false, kind: "server" });
    expect(!s.ok && s.message).toContain("agents unreachable");
  });
});

describe("followUpThreadId", () => {
  it("continues only a live run's well-formed thread", () => {
    expect(followUpThreadId({ servedFrom: "live", threadId: "c491ba68840c" })).toBe("c491ba68840c");
    expect(followUpThreadId({ servedFrom: "replay", threadId: "abc" })).toBeNull();
    expect(followUpThreadId({ servedFrom: "cache", threadId: "abc" })).toBeNull();
    expect(followUpThreadId({ servedFrom: "live", threadId: null })).toBeNull();
    expect(followUpThreadId({ servedFrom: "live", threadId: "../x" })).toBeNull();
    expect(followUpThreadId({ servedFrom: "live", threadId: "a".repeat(65) })).toBeNull();
    expect(followUpThreadId(null)).toBeNull();
  });
  it("caps the conversation to the newest turns", () => {
    expect(capTurns([1, 2, 3], 2)).toEqual([2, 3]);
    expect(capTurns([1], 2)).toEqual([1]);
  });
});

describe("askFloodSense", () => {
  afterEach(() => vi.unstubAllGlobals());
  it("posts JSON and reads Retry-After", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ detail: "x" }), { status: 429, headers: { "Retry-After": "12" } }));
    vi.stubGlobal("fetch", fetchMock);
    const r = await askFloodSense({ question: "q", provider: "nightshift", allowedProviders: ["nightshift"] }, undefined, "http://api");
    expect(!r.ok && r.message).toContain("12 s");
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("http://api/runs");
    expect(JSON.parse(init.body as string)).toMatchObject({ question: "q", llm_provider: "nightshift" });
  });
});
