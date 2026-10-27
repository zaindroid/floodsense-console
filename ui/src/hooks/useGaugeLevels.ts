import { useEffect, useState } from "react";
import { fetchGaugeLevels, type GaugeLoad } from "../api/gauges";

export type GaugeState = GaugeLoad | { state: "loading"; rows: []; detail: string };

/** PEGELONLINE updates most gauges every 15 minutes; the view's is_stale threshold is 30. */
export const GAUGE_REFRESH_MS = 5 * 60 * 1000;

let shared: { at: number; request: Promise<GaugeLoad> } | null = null;

/** Shared between widgets for GAUGE_REFRESH_MS. A failed or empty load is not reused. */
function load(now: number): Promise<GaugeLoad> {
  if (!shared || now - shared.at >= GAUGE_REFRESH_MS) {
    const request = fetchGaugeLevels();
    shared = { at: now, request };
    void request.then((result) => {
      if (result.state !== "rows" && shared?.request === request) shared = null;
    });
  }
  return shared.request;
}

export function useGaugeLevels(): GaugeState {
  const [state, setState] = useState<GaugeState>({ state: "loading", rows: [], detail: "" });
  useEffect(() => {
    let alive = true;
    const run = () =>
      void load(Date.now()).then((result) => {
        if (alive) setState(result);
      });
    run();
    const timer = setInterval(run, GAUGE_REFRESH_MS);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, []);
  return state;
}
