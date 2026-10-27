import type { SystemStatus } from "./system";

/** Status dot on a How it works box. */
export type DotState = "ok" | "off" | "down" | "unknown";

export const DOT_TEXT: Record<DotState, string> = {
  ok: "running",
  off: "switched off",
  down: "not reachable",
  unknown: "status unknown",
};

export type BoxId = "router" | "agents" | "zetaris" | "feeds" | "nightshift" | "memory" | "rag" | "redis" | "human";

/** GET /config result: the body, or "down" when the API could not be read. */
export type ConfigProbe = { kind: "ok"; body: unknown } | { kind: "down" };

const rec = (v: unknown): Record<string, unknown> | null =>
  v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : null;

/** The agents' /config body (the API passes it through, possibly in a `data` envelope). */
function configBody(p: ConfigProbe): Record<string, unknown> | null {
  if (p.kind !== "ok") return null;
  const body = rec(p.body);
  return rec(body?.data) ?? body;
}

function flag(config: Record<string, unknown> | null, name: string): DotState {
  const v = rec(config?.flags)?.[name];
  if (v === true) return "ok";
  if (v === false) return "off";
  return "unknown";
}

/**
 * Pure: every box's dot from GET /config and GET /system (api/app/system.py, parsed by `parseSystem`).
 * `system` is null when /system could not be read (404 on an older API, or down): those boxes fall back
 * to /config or stay unknown, never red.
 */
export function boxStatuses(config: ConfigProbe, system: SystemStatus | null): Record<BoxId, DotState> {
  const cfg = configBody(config);
  const agentsUp: DotState = cfg ? "ok" : "down";
  const lanes = system ? system.models.lanes : (rec(cfg?.lanes) as Record<string, unknown> | null);
  const hasLanes = Boolean(lanes && Object.values(lanes).some((v) => typeof v === "string" && v));
  return {
    router: agentsUp,
    agents: system ? (system.models.ok ? "ok" : "down") : agentsUp,
    // No Zetaris health is exposed; the agents read it on every run.
    zetaris: "unknown",
    feeds: cfg ? (rec(cfg.flags)?.FF_LIVE_DATA === true ? "ok" : "off") : "unknown",
    nightshift: hasLanes ? "ok" : system && !system.models.ok ? "down" : "unknown",
    memory: system
      ? system.memory.ok && (!system.engines.configured || system.engines.ok)
        ? "ok"
        : "down"
      : flag(cfg, "FF_HMEM"),
    rag: system && system.rag.enabled !== null ? (system.rag.enabled ? "ok" : "off") : flag(cfg, "FF_RAG_DOCS"),
    redis: system ? (system.cache.backend === "redis" ? "ok" : system.cache.backend === "unknown" ? "unknown" : "off") : "unknown",
    human: flag(cfg, "FF_HITL"),
  };
}

/** The approval box, by desk: insurers approve outbound alerts; a citizen's answers are not held back. */
export function humanBox(role: "citizen" | "insurer"): { title: string; line: string } {
  return role === "citizen"
    ? {
        title: "A person checks insurer alerts",
        line: "Insurer alerts are checked by a person before they're sent. Your answers aren't held back.",
      }
    : { title: "Human approval", line: "A person approves, edits or rejects the advice. Nothing is sent before that." };
}

/** "live feeds" or "seed data" for the data box, from FF_LIVE_DATA. */
export function feedsMode(config: ConfigProbe): "live feeds" | "seed data" | null {
  const cfg = configBody(config);
  if (!cfg) return null;
  return rec(cfg.flags)?.FF_LIVE_DATA === true ? "live feeds" : "seed data";
}
