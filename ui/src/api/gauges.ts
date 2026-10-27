import { asGaugeRow, type GaugeLevelRow } from "../lib/gauges";
import { parseRows } from "../lib/validate";
import { apiBaseUrl, apiTimeoutMs } from "./config";

export const GAUGE_LEVELS_PATH = "/views/gauge_levels";

export interface GaugeLoad {
  rows: GaugeLevelRow[];
  /**
   * "rows" means the API answered with rows that match the view columns. It says nothing about liveness:
   * each row's origin and is_stale decide that (see isLiveGauge).
   */
  state: "rows" | "empty" | "unavailable";
  detail: string;
}

/** Gauge readings through the Zetaris-backed API. The browser never calls PEGELONLINE. */
export async function fetchGaugeLevels(signal?: AbortSignal, fetcher: typeof fetch = fetch): Promise<GaugeLoad> {
  const base = apiBaseUrl();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), apiTimeoutMs());
  const onAbort = () => controller.abort();
  signal?.addEventListener("abort", onAbort, { once: true });
  try {
    const response = await fetcher(`${base}${GAUGE_LEVELS_PATH}`, { credentials: "omit", signal: controller.signal });
    if (!response.ok) return { rows: [], state: "unavailable", detail: `GET ${GAUGE_LEVELS_PATH} returned ${response.status}` };
    const body: unknown = await response.json();
    const rows = parseRows(body, asGaugeRow);
    if (rows === null) return { rows: [], state: "unavailable", detail: `${GAUGE_LEVELS_PATH} did not match the view columns` };
    if (rows.length === 0) return { rows: [], state: "empty", detail: `GET ${GAUGE_LEVELS_PATH} returned no rows` };
    return { rows, state: "rows", detail: `GET ${base}${GAUGE_LEVELS_PATH}` };
  } catch {
    return { rows: [], state: "unavailable", detail: `GET ${GAUGE_LEVELS_PATH} failed` };
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", onAbort);
  }
}
