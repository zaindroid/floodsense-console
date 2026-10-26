/**
 * Test-only LLM provider switch. Nightshift (NVIDIA Nemotron) is the default and
 * what the demo runs. The agents list "anthropic" in GET /config `llm_providers`
 * only when LLM_PROVIDER_SWITCH is on and a key is set; otherwise the select stays hidden.
 */
import { apiBaseUrl, apiTimeoutMs } from "../api/config";

export type LlmProvider = "nightshift" | "anthropic";

export const DEFAULT_PROVIDER: LlmProvider = "nightshift";
const STORAGE_KEY = "floodsense.llmProvider";

export const PROVIDER_LABELS: Record<LlmProvider, string> = {
  nightshift: "Nightshift (NVIDIA)",
  anthropic: "Anthropic (test)",
};

/** Known providers from a /config body; always at least Nightshift. */
export function parseProviders(config: unknown): LlmProvider[] {
  const raw = (config as { llm_providers?: unknown } | null)?.llm_providers;
  const list = Array.isArray(raw)
    ? raw.filter((p): p is LlmProvider => p === "nightshift" || p === "anthropic")
    : [];
  return list.includes("nightshift") ? list : [DEFAULT_PROVIDER, ...list];
}

/** The select shows only when there is a real choice. */
export function showProviderSelect(providers: readonly string[]): boolean {
  return providers.length > 1;
}

/** A stored choice is honoured only if the deployment still offers it. */
export function effectiveProvider(stored: string | null, providers: readonly string[]): LlmProvider {
  return stored === "anthropic" && providers.includes("anthropic") ? "anthropic" : DEFAULT_PROVIDER;
}

export function readStoredProvider(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

export function storeProvider(provider: LlmProvider): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, provider);
  } catch {
    // storage blocked: the choice lasts for this page only
  }
}

export async function loadProviders(): Promise<LlmProvider[]> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), apiTimeoutMs());
  try {
    const r = await fetch(`${apiBaseUrl()}/config`, { signal: ctrl.signal });
    if (!r.ok) return [DEFAULT_PROVIDER];
    return parseProviders(await r.json());
  } catch {
    return [DEFAULT_PROVIDER];
  } finally {
    clearTimeout(timer);
  }
}
