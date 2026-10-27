import { describe, expect, it } from "vitest";
import { boxStatuses, feedsMode } from "./howItWorks";
import { parseSystem } from "./system";

const config = {
  kind: "ok" as const,
  body: {
    flags: { FF_LIVE_DATA: false, FF_HMEM: true, FF_RAG_DOCS: true, FF_HITL: true },
    lanes: { fast: "nvidia/nemotron-3.5-lightning-30b-a3b", deep: "nvidia/nemotron-3.5-lightning-30b-a3b" },
  },
};

/** The api/app/system.py shape. */
const system = parseSystem({
  memory: { ok: true, count: 3, seeded: 3, latest: [] },
  cache: { backend: "redis", semantic_cache: true, hits: 1, misses: 2 },
  rate_limit: { runs_per_min_per_client: 6, max_concurrent_runs: 2, in_flight: 0 },
  engines: { configured: true, ok: true },
  world_model: { run_id: "r1", hypotheses: 2, by_status: { supported: 2 } },
  models: { ok: true, lanes: { fast: "nvidia/x", deep: "nvidia/y" }, llm_providers: ["nightshift"] },
  rag: { enabled: true, documents: null, passages: null },
});

describe("boxStatuses", () => {
  it("reads the real /system shape", () => {
    const s = boxStatuses(config, system);
    expect(s).toMatchObject({ agents: "ok", nightshift: "ok", memory: "ok", rag: "ok", redis: "ok", human: "ok", feeds: "off" });
  });

  it("shows engines down as memory down, and an in-process cache as off", () => {
    const down = parseSystem({ memory: { ok: false }, engines: { configured: true, ok: false }, cache: { backend: "memory" }, models: { ok: true } });
    const s = boxStatuses(config, down);
    expect(s.memory).toBe("down");
    expect(s.redis).toBe("off");
  });

  it("without /system (404) falls back to /config, never red", () => {
    const s = boxStatuses(config, null);
    expect(s.agents).toBe("ok");
    expect(s.nightshift).toBe("ok");
    expect(s.memory).toBe("ok");
    expect(s.redis).toBe("unknown");
    expect(Object.values(s)).not.toContain("down");
  });

  it("marks the agents unreachable when the API is down", () => {
    const s = boxStatuses({ kind: "down" }, null);
    expect(s.agents).toBe("down");
    expect(s.human).toBe("unknown");
  });

  it("names seed data or live feeds", () => {
    expect(feedsMode(config)).toBe("seed data");
    expect(feedsMode({ kind: "ok", body: { flags: { FF_LIVE_DATA: true } } })).toBe("live feeds");
    expect(feedsMode({ kind: "down" })).toBeNull();
  });
});
