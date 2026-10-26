import { useConsole } from "../context/ConsoleContext";
import { BAND_ELEVATED_M3S, BAND_TYPICAL_M3S, SIMULATED_ALERT_M3S } from "../config/scenario";
import { citationMarks, citationsById, citationsForClaim } from "../lib/citations";
import { actionsVisibleToCitizen } from "../lib/decision";
import { formatDay, formatHour, formatM3s, formatMm } from "../lib/format";
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

export function CitizenOverview() {
  const desk = useConsole();
  const point = pointById(desk.points, desk.pointId);
  const row = rowAt(desk.discharge.rows, desk.pointId, desk.date);
  const band = row ? dischargeBand(row.discharge_m3s) : null;
  const claims = desk.answer.claims.slice(0, WHY_CLAIMS);

  return (
    <div className="page-stack">
      <section className="card risk-card" aria-label="Risk for this area">
        <p className="section-label">Your area · {formatDay(desk.date)}</p>
        <h2>{point ? point.name : desk.pointId}</h2>
        {band ? (
          <>
            <p className="risk-badge" data-band={band}>
              {BAND_WORDS[band].word} river flow
            </p>
            <p className="figure">{formatM3s(row?.discharge_m3s ?? 0)}</p>
            <p className="figure-unit">
              m³/s · {statusLabel(desk.discharge.origin)} · band {BAND_WORDS[band].range}
            </p>
          </>
        ) : (
          <p className="note">No discharge row for this point on this date.</p>
        )}
        <p className="note">Replay of October 2024. Not an official warning.</p>
        <div className="button-row">
          <a className="button primary" href={routeHref("citizen", "actions")}>
            What to do
          </a>
          <a className="button" href={routeHref("citizen", "area")}>
            See my area
          </a>
          <button type="button" className="button ghost" onClick={desk.openAsk}>
            See the reviewed answer
          </button>
        </div>
      </section>
      <section className="card" aria-label="Why">
        <p className="section-label">Why</p>
        <h2>What the reviewed answer found</h2>
        <ul className="why-list">
          {claims.map((claim) => {
            const marks = citationMarks(citationsForClaim(desk.answer, claim.claim_id));
            return (
              <li key={claim.claim_id}>
                {claim.text}{" "}
                {marks && (
                  <a className="cite-marks" href={routeHref("citizen", "evidence")}>
                    {marks}
                  </a>
                )}
              </li>
            );
          })}
        </ul>
      </section>
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
        <p className="figure-caption">{origin}</p>
        <p className="figure">{row ? formatM3s(row.discharge_m3s) : "—"}</p>
        <p className="figure-unit">m³/s discharge</p>
        <Sparkline
          values={series.map((item) => item.discharge_m3s)}
          activeIndex={activeIndex}
          label={`Discharge series for ${desk.pointId}`}
        />
        <p>
          {row && point
            ? `On ${formatDay(desk.date)}, ${point.name} shows ${formatM3s(row.discharge_m3s)} m³/s in the loaded discharge series. The source column is ${row.source}. ${modelled ? `${modelled} ` : ""}Not an official warning.`
            : `No discharge row for ${desk.pointId} on ${formatDay(desk.date)}.`}
          {peak && row && peak.date === row.date ? " This is the highest day in the loaded series for this point." : ""}
        </p>
        <details className="disclosure">
          <summary>Rain on this date</summary>
          {rain.peak ? (
            <p className="note">
              Hourly rain on this date sums to {formatMm(rain.sum)} mm, with a max hour of {formatMm(rain.peak.rain_mm)} mm
              at {formatHour(rain.peak.ts_utc)}. warning_level is{" "}
              {rain.peak.warning_level === null ? "null" : rain.peak.warning_level}.
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
  const status = desk.approval.status;
  const actions = actionsVisibleToCitizen(status) ? (desk.answer.playbook_actions ?? []) : [];

  return (
    <div className="page-stack">
      <section className="card" aria-label="What to do">
        <p className="section-label">What to do</p>
        <h2>Follow official warnings first</h2>
        <p>This is a replay of October 2024, not a warning. Steps from the reviewed answer appear here once a person has approved them.</p>
        {status === "pending" ? (
          <p className="status-note" role="status">
            Pending human review. No suggested action is shown until an insurer approves it.
          </p>
        ) : status === "rejected" ? (
          <p className="status-note" role="status">
            The reviewer rejected the suggested action. Nothing to show.
          </p>
        ) : actions.length === 0 ? (
          <p className="note">The reviewed answer has no suggested actions.</p>
        ) : (
          <ol className="action-list">
            {actions.map((action) => {
              const marks = citationMarks(citationsById(desk.answer, action.citation_ids));
              return (
                <li key={action.action_id}>
                  <h3>{action.title}</h3>
                  <p>
                    {action.detail}{" "}
                    {marks && (
                      <a className="cite-marks" href={routeHref("citizen", "evidence")}>
                        {marks}
                      </a>
                    )}
                  </p>
                </li>
              );
            })}
          </ol>
        )}
        {status === "edited" && desk.approval.note && <p className="note">Reviewer's edit: {desk.approval.note}</p>}
        <p className="note">
          Review status <strong>{status}</strong>. <a href={routeHref("citizen", "evidence")}>See the evidence</a>.
        </p>
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
