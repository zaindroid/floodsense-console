import { useEffect, useState } from "react";
import { NEXT_48H_QUESTION } from "../api/ask";
import { useConsole } from "../context/ConsoleContext";
import { useLiveWatch } from "../hooks/useLiveWatch";
import type { WatchSource } from "../lib/euWatch";
import { relativeTime } from "../lib/now";
import { basisLabel, calmSentence, headlineCounts, headlineText, plainOf, worstFirst } from "../lib/places";
import { EuWatchLegend, EuWatchMap } from "./EuWatch";
import { InsurerNowPage } from "./InsurerNowPage";
import { LiveSourceBadge } from "./LiveSources";
import { evidenceFor, PlacesToWatch, sourceTitle, StatusChip, timeText } from "./PlacesToWatch";

/** Now: insurers keep the dense page; citizens get the calm, live-first one. */
export function NowPage() {
  const { route } = useConsole();
  return route === "insurer" ? <InsurerNowPage /> : <CitizenNowPage />;
}

/**
 * Citizen Now: the chosen place (or the worst place in the watch) first, in one plain sentence with its source;
 * then ONE Europe map of every live-watch source, the legend behind "How we colour the map", and "Places to watch",
 * worst first. Numbers only behind Details.
 */
function CitizenNowPage() {
  const { openAsk, placeId } = useConsole();
  const live = useLiveWatch();
  const [clock, setClock] = useState(() => Date.now());
  useEffect(() => {
    const tick = window.setInterval(() => setClock(Date.now()), 30_000);
    return () => window.clearInterval(tick);
  }, []);

  const chosen = live.sources.find((s) => s.id === placeId) ?? null;
  const lead: WatchSource | null = chosen ?? worstFirst(live.sources)[0] ?? null;
  const loading = live.gauges.state === "loading" || live.euWatch.state === "loading" || live.hazard.state === "loading";
  const ask = (s: WatchSource) => openAsk(s.question, { page: "now", place: s.name });

  return (
    <div className="now-page">
      <header className="now-head">
        <div>
          <h2 className="now-title">Right now, across our watch</h2>
          <p className="now-meta" aria-live="polite">
            <span className="now-live-tag">Live data · Zetaris</span>
            {live.updatedAt ? ` Updated ${relativeTime(live.updatedAt, clock)}` : ""}
          </p>
        </div>
        <div className="button-row">
          <button type="button" className="now-refresh" onClick={() => openAsk(NEXT_48H_QUESTION)}>
            Ask about the next 48 hours
          </button>
          <button type="button" className="now-refresh" onClick={live.refresh}>
            Refresh
          </button>
        </div>
      </header>

      {lead ? (
        <section className="now-lead" aria-label={chosen ? "Your place" : "Most notable place right now"}>
          <p className="eyebrow">{chosen ? "Your place" : "Most notable right now"}</p>
          <p>
            <StatusChip view={plainOf(lead)} large /> <strong>{sourceTitle(lead)}</strong>{" "}
            <span className="muted small">{lead.country}</span>
          </p>
          <p>
            {calmSentence(lead.kind, lead.status, lead.river, lead.name)}{" "}
            <LiveSourceBadge n={1} evidence={evidenceFor(live, lead)} />
          </p>
          <p className="note">
            {timeText(lead.kind, lead.measuredAt)} · {basisLabel(lead.kind)}
          </p>
          <p className="note">Across the watch: {headlineText(headlineCounts(live.sources))}.</p>
        </section>
      ) : (
        <p className="now-status" role="status">
          {loading ? "Loading live data…" : "No live readings right now: the live views did not answer. Try Refresh in a few minutes."}
        </p>
      )}

      <section className="now-region" aria-labelledby="now-eu">
        <div className="now-region-head">
          <h3 className="now-subtitle" id="now-eu">
            Europe · live watch
          </h3>
        </div>
        <EuWatchMap sources={live.sources} />
        <details className="disclosure">
          <summary>How we colour the map</summary>
          <p className="now-note">
            Circles are river gauges, measured, against each station's long-term mean high water (not a warning level).
            Diamonds and squares are GloFAS model points: a model, not an official warning. Faded or dashed markers are not
            a fresh live reading. Click a place to ask about it.
          </p>
          <EuWatchLegend />
          {live.euWatch.state === "unavailable" && <p className="note">GloFAS points unavailable: {live.euWatch.detail}</p>}
          {live.hazard.state === "error" && <p className="note">Valencia points unavailable: {live.hazard.detail}</p>}
          {live.gauges.state === "unavailable" && <p className="note">Gauges unavailable: {live.gauges.detail}</p>}
        </details>
        <PlacesToWatch live={live} onAsk={ask} start={2} exclude={lead?.id ?? null} />
        <p className="now-source">
          Quelle: WSV, PEGELONLINE (DL-DE-Zero-2.0) · Weather data by Open-Meteo.com (GloFAS, CC BY 4.0) · via Zetaris
        </p>
      </section>
    </div>
  );
}
