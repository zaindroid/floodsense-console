import type { DataOrigin } from "../types/views";

export type PillTone = "fixture" | "seed" | "live" | "mixed";

/** Visible status word. Green “live” is reserved for a non-seed view response. */
export function statusLabel(origin: DataOrigin): "Fixture" | "Seed" | "Live" {
  if (origin === "seed") return "Seed";
  if (origin === "live") return "Live";
  return "Fixture";
}

export function originPill(origins: DataOrigin[]): { tone: PillTone; label: string } {
  const kinds = new Set(origins);
  if (kinds.size <= 1) {
    const only = origins[0] ?? "fixture";
    return { tone: only, label: statusLabel(only) };
  }
  const order: DataOrigin[] = ["seed", "fixture", "live"];
  return {
    tone: "mixed",
    label: order
      .filter((item) => kinds.has(item))
      .map((item) => statusLabel(item))
      .join(" · "),
  };
}
