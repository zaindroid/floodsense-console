import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { NEXT_48H_QUESTION } from "../api/ask";
import { fetchGaugeLevels, fetchHazardNow, type HazardNowResult } from "../api/now";
import { useConsole } from "../context/ConsoleContext";
import { latestPastStamp, relativeTime, sparkSeries, summariseAll, type GaugeLevelRow, type PointNow, type Trend } from "../lib/now";
import { pointById } from "../lib/series";
import { Sparkline } from "./Sparkline";

const REFRESH_MS = 5 * 60_000;
const MODEL_NOTE = "Modelled (GloFAS via Open-Meteo), not an official warning";
const ATTRIBUTION = "Weather data by Open-Meteo.com";

type Load =
  | { state: "loading" }
  | { state: "error"; detail: string }
  | { state: "ready"; data: HazardNowResult; fetchedAt: number };

type Gauges = { state: "loading" } | { state: "error" } | { state: "ready"; rows: GaugeLevelRow[] };

function localTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

function fmt(value: number | null, digits = 1): string {
  return value === null ? "–" : value.toFixed(digits);
}

const TREND_TEXT: Record<Trend, { arrow: string; label: string }> = {
  up: { arrow: "↑", label: "rising vs 24 h ago" },
  down: { arrow: "↓", label: "falling vs 24 h ago" },
  flat: { arrow: "→", label: "steady vs 24 h ago" },
  unknown: { arrow: "·", label: "no 24 h comparison" },
};

/** Live hourly view of the eight Valencia points. Its own fetch; never falls back to the replay fixture. */
export function NowPage() {
  const { points, openAsk } = useConsole();
  const [load, setLoad] = useState<Load>({ state: "loading" });
  const [gauges, setGauges] = useState<Gauges>({ state: "loading" });
  const [clock, setClock] = useState(() => Date.now());
  const controller = useRef<AbortController | null>(null);

  const refresh = useCallback(() => {
    controller.current?.abort();
    const ctrl = new AbortController();
    controller.current = ctrl;
    setLoad((prev) => (prev.state === "ready" ? prev : { state: "loading" }));
    fetchHazardNow(ctrl.signal)
      .then((data) => {
        if (!ctrl.signal.aborted) setLoad({ state: "ready", data, fetchedAt: Date.now() });
      })
      .catch((error: unknown) => {
        if (ctrl.signal.aborted) return;
        setLoad({ state: "error", detail: error instanceof Error ? error.message : "request failed" });
      });
    fetchGaugeLevels(ctrl.signal)
      .then((rows) => {
        if (!ctrl.signal.aborted) setGauges({ state: "ready", rows });
      })
      .catch(() => {
        if (!ctrl.signal.aborted) setGauges({ state: "error" });
      });
  }, []);

  useEffect(() => {
    refresh();
    let timer: number | undefined;
    const schedule = () => {
      window.clearInterval(timer);
      if (document.visibilityState === "visible") timer = window.setInterval(refresh, REFRESH_MS);
    };
    const onVisibility = () => {
      if (document.visibilityState === "visible") refresh();
      schedule();
    };
    schedule();
    document.addEventListener("visibilitychange", onVisibility);
    const tick = window.setInterval(() => setClock(Date.now()), 30_000);
    return () => {
      window.clearInterval(timer);
      window.clearInterval(tick);
      document.removeEventListener("visibilitychange", onVisibility);
      controller.current?.abort();
    };
  }, [refresh]);

  const summaries = useMemo(() => (load.state === "ready" ? summariseAll(load.data.rows) : []), [load]);
  const stamp = load.state === "ready" ? latestPastStamp(load.data.rows) : null;

  return (
    <div className="now-page">
      <header className="now-head">
        <div>
          <h2 className="now-title">Right now{stamp ? ` · ${localTime(stamp)}` : ""}</h2>
          {load.state === "ready" && (
            <p className="now-meta" aria-live="polite">
              <span className="now-live-tag">Live data · Zetaris</span> Updated {relativeTime(load.fetchedAt, clock)}
              {load.data.queryId ? ` · Zetaris query ${load.data.queryId.slice(0, 8)}` : ""}
              {load.data.dropped > 0 ? ` · ${load.data.dropped} rows dropped` : ""}
              {load.data.truncated ? " · truncated" : ""}
            </p>
          )}
        </div>
        <div className="button-row">
          <button type="button" className="now-refresh" onClick={() => openAsk(NEXT_48H_QUESTION)}>
            Ask about the next 48 hours
          </button>
          <button type="button" className="now-refresh" onClick={refresh}>
            Refresh
          </button>
        </div>
      </header>
      <p className="now-note">{MODEL_NOTE}. Dashed line and “forecast” values are model forecasts.</p>

      {load.state === "loading" && (
        <p className="now-status" aria-live="polite">
          Loading live data…
        </p>
      )}
      {load.state === "error" && (
        <div className="now-error" role="alert">
          <p>Could not load live data.</p>
          <p className="now-detail">{load.detail}</p>
          <button type="button" className="now-refresh" onClick={refresh}>
            Retry
          </button>
        </div>
      )}
      {load.state === "ready" && summaries.length === 0 && <p className="now-status">No live rows returned.</p>}
      {load.state === "ready" && summaries.length > 0 && (
        <div className="now-grid">
          {summaries.map((summary) => (
            <PointCard key={summary.point_id} summary={summary} name={pointById(points, summary.point_id)?.name} />
          ))}
        </div>
      )}

      <section className="now-gauges">
        <h3 className="now-subtitle">Water levels (Rhine, PEGELONLINE)</h3>
        {gauges.state === "loading" && <p className="now-status">Loading gauge readings…</p>}
        {gauges.state === "error" && <p className="now-status">Could not load gauge readings.</p>}
        {gauges.state === "ready" && gauges.rows.length === 0 && <p className="now-status">No live gauge readings yet.</p>}
        {gauges.state === "ready" && gauges.rows.length > 0 && (
          <ul className="now-gauge-list">
            {gauges.rows.map((row, index) => (
              <li key={`${row.station}-${row.ts_utc ?? index}`}>
                <strong>{row.station}</strong>
                {row.water ? ` (${row.water})` : ""}: {row.level_cm === null ? "no reading" : `${fmt(row.level_cm, 0)} cm`}
                {row.ts_utc ? ` · ${localTime(row.ts_utc)}` : ""}
              </li>
            ))}
          </ul>
        )}
        <p className="now-source">Quelle: WSV, PEGELONLINE</p>
      </section>
      <p className="now-source">{ATTRIBUTION}</p>
    </div>
  );
}

function PointCard({ summary, name }: { summary: PointNow; name?: string }) {
  const trend = TREND_TEXT[summary.trend];
  const { values, split } = sparkSeries(summary);
  return (
    <article className="now-card">
      <h3 className="now-card-title">
        {name ?? summary.point_id} <span className="now-id">{summary.point_id}</span>
      </h3>
      {summary.latest ? (
        <dl className="now-stats">
          <div>
            <dt>Discharge</dt>
            <dd>
              {fmt(summary.latest.discharge_m3s)} m³/s{" "}
              <span className={`now-trend now-trend-${summary.trend}`} title={trend.label} aria-hidden="true">
                {trend.arrow}
              </span>
              <span className="sr-only">{trend.label}</span>
            </dd>
          </div>
          <div>
            <dt>Rain last hour</dt>
            <dd>{fmt(summary.rainLastHour)} mm</dd>
          </div>
          <div>
            <dt>Rain last 24 h</dt>
            <dd>{fmt(summary.rain24h)} mm</dd>
          </div>
        </dl>
      ) : (
        <p className="now-status">No past rows for this point.</p>
      )}
      <p className="now-forecast">
        {summary.forecastMax
          ? `Forecast max next 48 h: ${fmt(summary.forecastMax.discharge_m3s)} m³/s at ${localTime(summary.forecastMax.ts_utc)}`
          : "No forecast rows."}
      </p>
      {values.length > 1 && (
        <Sparkline
          values={values}
          activeIndex={split ?? values.length - 1}
          splitIndex={split}
          label={`${name ?? summary.point_id} discharge, past 72 h and forecast 48 h (dashed)`}
        />
      )}
    </article>
  );
}
