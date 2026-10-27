import { useMemo } from "react";
import { SIMULATED_ALERT_M3S } from "../config/scenario";
import { useConsole } from "../context/ConsoleContext";
import { formatDay, formatEur } from "../lib/format";
import { exposureStats, rowsOnDate } from "../lib/series";
import { EVENT_META } from "../lib/events";
import { OriginList } from "./Banners";

/** Book KPIs (moved from the map card) and the in-footprint split by segment. */
export function Portfolio() {
  const desk = useConsole();
  const stats = useMemo(() => exposureStats(desk.exposure.rows), [desk.exposure.rows]);
  const peakCount = rowsOnDate(desk.discharge.rows, desk.date).filter(
    (row) => row.discharge_m3s >= SIMULATED_ALERT_M3S,
  ).length;
  const largest = stats.segments[0]?.sum ?? 0;

  if (desk.eventId !== "EMSR773") {
    return (
      <div className="page-stack">
        <section className="card" aria-label="Exposure">
          <p className="section-label">Exposure · {EVENT_META[desk.eventId].short} · {desk.eventId}</p>
          <h2>No insured book for this event</h2>
          <p className="note">
            The synthetic portfolio (exposure_join) is joined to the EMSR773 Valencia footprint only. There are no policies or
            footprint rows for {desk.eventId}, so there is nothing to total here.
          </p>
          <div className="button-row">
            <button type="button" className="button" onClick={() => desk.setEventId("EMSR773")}>
              Show the Valencia book
            </button>
          </div>
        </section>
      </div>
    );
  }

  return (
    <div className="page-stack">
      <section className="card" aria-label="Exposure">
        <p className="section-label">Exposure on {formatDay(desk.date)}</p>
        <h2>Synthetic book against the EMSR773 footprint</h2>
        <dl className="kpis">
          <div>
            <dt>Points</dt>
            <dd>{desk.points.length}</dd>
          </div>
          <div>
            <dt>Peak band</dt>
            <dd>{peakCount}</dd>
          </div>
          <div>
            <dt>in_footprint</dt>
            <dd>
              {stats.inFootprint} / {stats.policies}
            </dd>
          </div>
          <div>
            <dt>Sum insured</dt>
            <dd>{formatEur(stats.sumInsured)}</dd>
          </div>
        </dl>
      </section>
      <section className="card" aria-label="In footprint by segment">
        <p className="section-label">By segment</p>
        <h2>Sum insured inside the footprint</h2>
        {stats.segments.length === 0 ? (
          <p className="note">No policies inside the footprint in the loaded rows.</p>
        ) : (
          <ul className="bars">
            {stats.segments.map((segment) => (
              <li key={segment.segment}>
                <span className="bar-label">{segment.segment}</span>
                <span className="bar-track" aria-hidden="true">
                  <span style={{ width: `${largest > 0 ? (segment.sum / largest) * 100 : 0}%` }} />
                </span>
                <span className="bar-value">
                  {formatEur(segment.sum)} · {segment.count} {segment.count === 1 ? "policy" : "policies"}
                </span>
              </li>
            ))}
          </ul>
        )}
        <p className="note">Portfolio rows are synthetic. exposure_join.in_footprint marks them against the footprint.</p>
      </section>
      <details className="card disclosure">
        <summary>Data origin</summary>
        <OriginList />
      </details>
    </div>
  );
}
