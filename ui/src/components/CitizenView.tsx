import { useId, useMemo, useState } from "react";
import { useConsole } from "../context/ConsoleContext";
import { useGaugeLevels } from "../hooks/useGaugeLevels";
import { summariseGauges } from "../lib/gauges";
import { plainLanguage } from "../lib/plain";
import { GaugeList, GaugeMap } from "./GaugeMap";
import { BAND_ELEVATED_M3S, BAND_TYPICAL_M3S, SIMULATED_ALERT_M3S } from "../config/scenario";
import { citationsById, citationsForClaim, type NumberedCitation } from "../lib/citations";
import { actionsVisibleToCitizen } from "../lib/decision";
import { formatDay, formatHour, formatM3s, formatMm, servingLabel } from "../lib/format";
import { statusLabel } from "../lib/origin";
import { routeHref } from "../lib/route";
import {
  dischargeBand,
  glofasDischargeNote,
  hazardOnDate,
  peakRow,
  pointById,
  provenanceForSource,
  rainSummary,
  rowAt,
  seriesFor,
  sourceExplanation,
} from "../lib/series";
import type { DischargeBand } from "../types/ui";
import { CitationList, ProvenanceList } from "./EvidenceDrawer";
import { MapPanel } from "./MapPanel";
import { Sparkline } from "./Sparkline";

/** Map-band words. Bands are this screen's marker colours, not warning levels. */
const BAND_WORDS: Record<DischargeBand, { word: string; range: string }> = {
  low: { word: "Low", range: `under ${BAND_TYPICAL_M3S} m³/s` },
  typical: { word: "Typical", range: `${BAND_TYPICAL_M3S}–${BAND_ELEVATED_M3S} m³/s` },
  elevated: { word: "Elevated", range: `${BAND_ELEVATED_M3S}–${SIMULATED_ALERT_M3S} m³/s` },
  peak: { word: "Peak", range: `${SIMULATED_ALERT_M3S} m³/s or more` },
};

const WHY_CLAIMS = 3;

/** Marker band to the risk colour scale. Colour only; the word stays the band's own. */
const BAND_TONE: Record<DischargeBand, "low" | "moderate" | "high" | "severe"> = {
  low: "low",
  typical: "low",
  elevated: "high",
  peak: "severe",
};

function PlacePicker() {
  const desk = useConsole();
  const [query, setQuery] = useState("");
  const inputId = useId();
  const needle = query.trim().toLowerCase();
  const matches = desk.points.filter((p) => `${p.name} ${p.municipality}`.toLowerCase().includes(needle));
  return (
    <div className="location-picker">
      <label htmlFor={inputId} className="sr-only">
        Search a place
      </label>
      <input
        id={inputId}
        type="search"
        placeholder="Search a place, e.g. Paiporta"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
      />
      <div className="location-picker__options" role="group" aria-label="Places">
        {matches.map((p) => (
          <button
            key={p.point_id}
            type="button"
            aria-pressed={p.point_id === desk.pointId}
            className={`location-option${p.point_id === desk.pointId ? " is-selected" : ""}`}
            onClick={() => desk.setPointId(p.point_id)}
          >
            <strong>{p.name}</strong>
            <span>{p.municipality}</span>
          </button>
        ))}
        {matches.length === 0 && <p className="note">No place matches “{query}”.</p>}
      </div>
    </div>
  );
}

function CiteChips({ items }: { items: NumberedCitation[] }) {
  if (items.length === 0) return <span className="uncited">uncited</span>;
  return (
    <span className="citation-markers">
      {items.map((item) => (
        <a
          key={item.citation.citation_id}
          className="citation-marker"
          href={routeHref("citizen", "evidence")}
          title={`${item.citation.title} · ${item.citation.publisher}`}
          aria-label={`Source ${item.n}: ${item.citation.title}`}
        >
          {item.n}
        </a>
      ))}
    </span>
  );
}

/** Reviewed playbook actions, in the answer's order, shown only once a person approved them. */
function ActionCards() {
  const desk = useConsole();
  const status = desk.approval.status;
  const actions = actionsVisibleToCitizen(status) ? (desk.answer.playbook_actions ?? []) : [];
  if (status === "pending")
    return (
      <p className="status-note" role="status">
        Pending human review. No suggested step is shown until an insurer approves it. Follow official warnings meanwhile.
      </p>
    );
  if (status === "rejected")
    return (
      <p className="status-note" role="status">
        The reviewer rejected the suggested step. Nothing to show.
      </p>
    );
  if (actions.length === 0) return <p className="note">The reviewed answer has no suggested steps.</p>;
  return (
    <>
      <ol className="actions">
        {actions.map((action, index) => (
          <li key={action.action_id} className="action">
            <span className="action__urgency">Step {index + 1}</span>
            <div>
              <strong>{action.title}</strong>
              <p>
                {action.detail} <CiteChips items={citationsById(desk.answer, action.citation_ids)} />
              </p>
            </div>
          </li>
        ))}
      </ol>
      {status === "edited" && desk.approval.note && <p className="note">Reviewer's edit: {desk.approval.note}</p>}
    </>
  );
}

export function CitizenOverview() {
  const desk = useConsole();
  const point = pointById(desk.points, desk.pointId);
  const row = rowAt(desk.discharge.rows, desk.pointId, desk.date);
  const band = row ? dischargeBand(row.discharge_m3s) : null;
  const claims = desk.answer.claims.slice(0, WHY_CLAIMS);
  const serving = servingLabel(desk.answer);
  const judge = desk.answer.judge?.overall_score;
  const gauges = useGaugeLevels();
  const summaries = useMemo(() => summariseGauges(gauges.rows), [gauges.rows]);
  const place = point ? point.name : desk.pointId;

  return (
    <div className="view">
      <div className="view__intro">
        <div>
          <h2 className="view__title">Is my area at risk, and why?</h2>
          <p className="muted">
            Plain-language flood risk with a source behind every sentence. Click a number to see the evidence.
          </p>
        </div>
      </div>
      <PlacePicker />
      <div className="grid grid--citizen">
        <section className="card span-2" aria-label="Risk right now">
          <header className="card__header">
            <h2 className="card__title">Risk right now</h2>
          </header>
          <div className="card__body">
            <div className={`risk-summary risk-summary--${band ? BAND_TONE[band] : "low"}`}>
              <div className="risk-summary__top">
                <div>
                  <p className="eyebrow">
                    River flow · {formatDay(desk.date)} · {place}
                  </p>
                  {band ? (
                    <div className="risk-summary__level">
                      <span className={`risk-badge risk-badge--lg risk-badge--${BAND_TONE[band]}`} data-band={band}>
                        {BAND_WORDS[band].word}
                      </span>
                      <span className="risk-summary__score" title="River discharge on this day">
                        {formatM3s(row?.discharge_m3s ?? 0)}
                        <small> m³/s</small>
                      </span>
                    </div>
                  ) : (
                    <p className="note">No river-flow reading for this place on this date.</p>
                  )}
                </div>
                <div className="risk-summary__meta">
                  <span className={`cache-label cache-label--${serving.kind === "live" ? "live" : "cached"}`}>
                    {serving.kind === "live" && <span className="dot" aria-hidden="true" />}
                    {serving.kind === "cached" ? `${serving.text} UTC` : serving.text}
                  </span>
                  {typeof judge === "number" && (
                    <span className="judge__pill" title="Judge overall score of the reviewed answer, 0 to 1">
                      Judge {judge.toFixed(2)}
                    </span>
                  )}
                </div>
              </div>
              <p className="risk-summary__headline">
                {band ? `${BAND_WORDS[band].word} river flow (${BAND_WORDS[band].range}).` : "No reading."} Replay of October
                2024. Not an official warning.
              </p>
              <h3 className="section-title">Why?</h3>
              <ul className="claims">
                {claims.map((claim) => (
                  <li key={claim.claim_id}>
                    {plainLanguage(claim.text)} <CiteChips items={citationsForClaim(desk.answer, claim.claim_id)} />
                  </li>
                ))}
              </ul>
              <details className="disclosure">
                <summary>Technical detail</summary>
                <ul className="note">
                  {claims.map((claim) => (
                    <li key={claim.claim_id}>
                      <code>{claim.claim_id}</code> {claim.text}
                    </li>
                  ))}
                </ul>
              </details>
              <div className="button-row">
                <a className="button" href={routeHref("citizen", "area")}>
                  See my area
                </a>
                <button type="button" className="button ghost" onClick={() => desk.openAsk()}>
                  Ask a question
                </button>
              </div>
            </div>
          </div>
        </section>
        <section className="card" aria-label="What should I do?">
          <header className="card__header">
            <h2 className="card__title">What should I do?</h2>
          </header>
          <div className="card__body">
            <ActionCards />
          </div>
        </section>
        <section className="card span-2" aria-label="River gauges map">
          <header className="card__header">
            <h2 className="card__title">River gauges map</h2>
          </header>
          <div className="card__body">
            <GaugeMap load={gauges} gauges={summaries} />
          </div>
        </section>
        <section className="card" aria-label="River gauges (Rhine, Mosel)">
          <header className="card__header">
            <h2 className="card__title">River gauges (Rhine, Mosel)</h2>
          </header>
          <div className="card__body">
            <GaugeList load={gauges} gauges={summaries} />
          </div>
        </section>
      </div>
    </div>
  );
}

/** The #36 Place and Rain content: map, point, discharge in plain language, rain under a disclosure. */
export function CitizenArea() {
  const desk = useConsole();
  const point = pointById(desk.points, desk.pointId);
  const series = seriesFor(desk.discharge.rows, desk.pointId);
  const row = rowAt(desk.discharge.rows, desk.pointId, desk.date);
  const activeIndex = series.findIndex((item) => item.date === desk.date);
  const peak = peakRow(series);
  const rain = rainSummary(hazardOnDate(desk.hazard.rows, desk.pointId, desk.date));
  const provenance = row ? provenanceForSource(row.source, desk.provenance.rows) : undefined;
  const origin = statusLabel(desk.discharge.origin);
  const modelled = row ? glofasDischargeNote(row.source) : null;

  return (
    <div className="citizen-grid">
      <MapPanel exposureDefault={false} />
      <section className="card" aria-label="Plain-language discharge">
        <p className="section-label">My area</p>
        <h2>{point ? point.name : desk.pointId}</h2>
        <p className="figure-caption">
          Source: {origin}
          {row ? ` · ${row.source}` : ""}
        </p>
        <p className="figure">{row ? formatM3s(row.discharge_m3s) : "—"}</p>
        <p className="figure-unit">m³/s discharge</p>
        <Sparkline
          values={series.map((item) => item.discharge_m3s)}
          activeIndex={activeIndex}
          label={`Discharge series for ${desk.pointId}`}
        />
        <p>
          {row && point
            ? `On ${formatDay(desk.date)}, ${point.name} shows ${formatM3s(row.discharge_m3s)} m³/s in the loaded discharge series. ${modelled ? `${modelled} ` : ""}Not an official warning.`
            : `No discharge row for ${desk.pointId} on ${formatDay(desk.date)}.`}
          {peak && row && peak.date === row.date ? " This is the highest day in the loaded series for this point." : ""}
        </p>
        <details className="disclosure">
          <summary>Rain on this date</summary>
          {rain.peak ? (
            <p className="note">
              Hourly rain on this date sums to {formatMm(rain.sum)} mm, with a max hour of {formatMm(rain.peak.rain_mm)} mm
              at {formatHour(rain.peak.ts_utc)}.
              {rain.peak.warning_level === null ? " No official warning level is attached." : ` Warning level ${rain.peak.warning_level}.`}
            </p>
          ) : (
            <p className="note">No hourly rain rows for this point on this date.</p>
          )}
        </details>
        {provenance && (
          <p className="note">
            {provenance.attribution}. {provenance.licence}.
          </p>
        )}
        <p>
          <a href="#/insurer">Open the insurer desk</a> for the cited chain, Skeptic notes, and approval.
        </p>
      </section>
    </div>
  );
}

/**
 * Playbook actions from the reviewed answer, in the answer's order. The answer carries no severity field yet.
 * Shown only after an insurer approved them on Approvals, so a citizen never sees an action no human reviewed.
 */
export function CitizenActions() {
  const desk = useConsole();
  return (
    <div className="page-stack">
      <section className="card" aria-label="What to do">
        <header className="card__header">
          <h2 className="card__title">What should I do?</h2>
        </header>
        <div className="card__body">
          <p>
            Follow official warnings first. This is a replay of October 2024, not a warning. Steps from the reviewed answer
            appear here once a person has approved them.
          </p>
          <ActionCards />
          <p className="note">
            Review status: {desk.approval.status}. <a href={routeHref("citizen", "evidence")}>See the evidence</a>.
          </p>
        </div>
      </section>
    </div>
  );
}

export function CitizenEvidence() {
  const desk = useConsole();
  const point = pointById(desk.points, desk.pointId);
  const row = rowAt(desk.discharge.rows, desk.pointId, desk.date);
  const provenance = row ? provenanceForSource(row.source, desk.provenance.rows) : undefined;

  return (
    <div className="page-stack">
      <section className="card" aria-label="Why this source">
        <p className="section-label">Why this source</p>
        <h2>{point ? point.name : desk.pointId} on {formatDay(desk.date)}</h2>
        <p>
          {row
            ? `${formatM3s(row.discharge_m3s)} m³/s. ${provenance ? `${provenance.publisher}, ${provenance.licence}.` : ""} ${glofasDischargeNote(row.source) ?? ""}`
            : "No discharge row is selected."}
        </p>
        <details className="disclosure">
          <summary>Technical detail</summary>
          {row && <p className="note">{sourceExplanation(row.source, desk.discharge.origin)}</p>}
          {provenance ? <ProvenanceList row={provenance} /> : <p className="note">No provenance row matched this source.</p>}
        </details>
        <div className="button-row">
          <button type="button" className="button" onClick={() => desk.openEvidence("discharge")}>
            Open full evidence
          </button>
        </div>
      </section>
      <section className="card" aria-label="Citations">
        <p className="section-label">Citations</p>
        <h2>Sources behind the answer</h2>
        <CitationList answer={desk.answer} />
      </section>
    </div>
  );
}
