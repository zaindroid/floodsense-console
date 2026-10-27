import { useId, useMemo, useState } from "react";
import { useConsole } from "../context/ConsoleContext";
import { useLiveWatch, type LiveWatch } from "../hooks/useLiveWatch";
import { plainLanguage } from "../lib/plain";
import { citationsById, citationsForClaim, type NumberedCitation } from "../lib/citations";
import { actionsVisibleToCitizen } from "../lib/decision";
import { formatDay, formatHour, formatM3s, formatMm } from "../lib/format";
import { statusLabel } from "../lib/origin";
import { routeHref } from "../lib/route";
import {
  CITIZEN_ADVICE,
  CITIZEN_ADVICE_SOURCE,
  EMERGENCY_LINE,
  GATE_LINE,
  SAFETY_HEADLINE,
  WARNING_LINKS,
  warningCountriesForCountry,
  type WarningCountry,
} from "../lib/safety";
import { SafeLink } from "./SafeLink";
import { SourceBadges, SourceLegend } from "./SourceBadges";
import { answerEventId, sourceFromCitation } from "../lib/sources";
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
import { ahrDischarge, ahrMapPoints, EVENT_META } from "../lib/events";
import {
  basisLabel,
  buildPlaces,
  calmSentence,
  countryName,
  headlineCounts,
  headlineText,
  plainOf,
  questionForPlace,
  quickPlaces,
  searchPlaces,
  worstFirst,
  type Place,
  type StatusView,
} from "../lib/places";
import { evidenceForSource, GAUGE_PIPELINE, GLOFAS_PIPELINE, HAZARD_NOW_PIPELINE } from "../lib/liveEvidence";
import type { DischargeBand } from "../types/ui";
import { CitationList, ProvenanceList } from "./EvidenceDrawer";
import { MapPanel } from "./MapPanel";
import { Sparkline } from "./Sparkline";
import { LiveSourceBadge } from "./LiveSources";
import { evidenceFor, metaFor, PlaceRow, PlacesToWatch, sourceTitle, StatusChip, timeText } from "./PlacesToWatch";
import { EuWatchMap } from "./EuWatch";

const WHY_CLAIMS = 3;
const MAX_MATCHES = 12;

/** A replay day's discharge band in plain words (FloodSense demo cuts, never an official level; never red). */
const BAND_VIEW: Record<DischargeBand, StatusView> = {
  low: { word: "Normal flow", tone: "normal", rank: 8 },
  typical: { word: "Normal flow", tone: "normal", rank: 8 },
  elevated: { word: "Above 20 m³/s demo line", tone: "neutral", rank: 5 },
  peak: { word: "Above 80 m³/s demo line", tone: "elevated", rank: 4 },
};
const NO_READING: StatusView = { word: "No reading", tone: "unknown", rank: 9 };

/** The live views, the place list and the chosen place, shared by every citizen page. */
function useCitizenPlace(): { live: LiveWatch; places: Place[]; place: Place | null; choose: (p: Place | null) => void } {
  const desk = useConsole();
  const live = useLiveWatch();
  const ahr = useMemo(() => ahrMapPoints(), []);
  const places = useMemo(() => buildPlaces(live.sources, desk.points, ahr), [live.sources, desk.points, ahr]);
  const place = places.find((p) => p.id === desk.placeId) ?? null;
  const { setPlaceId, setPointId, setAhrPointId } = desk;
  const choose = (p: Place | null) => {
    setPlaceId(p ? p.id : null);
    if (p?.eventId === "EMSR773" && p.pointId) setPointId(p.pointId);
    if (p?.eventId === "EMSR517" && p.pointId) setAhrPointId(p.pointId);
  };
  return { live, places, place, choose };
}

function placeLabel(p: Place): string {
  if (p.kind === "replay") return `${p.name} · ${p.eventId ? EVENT_META[p.eventId].short : ""} replay`;
  return p.river ? `${p.river} · ${p.name}` : p.name;
}

function PlacePicker({ places, place, choose, live }: ReturnType<typeof useCitizenPlace>) {
  const [query, setQuery] = useState("");
  const inputId = useId();
  const matches = query.trim() ? searchPlaces(places, query).slice(0, MAX_MATCHES) : [];
  const quick = useMemo(() => quickPlaces(places, live.sources, place?.id ?? null), [live.sources, places, place?.id]);
  const list = query.trim() ? matches : quick;
  return (
    <div className="location-picker">
      <label htmlFor={inputId} className="sr-only">
        Search a place, river or country
      </label>
      <input
        id={inputId}
        type="search"
        placeholder="Search a place, river or country, e.g. Köln, Danube, Paiporta"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
      />
      <div className="location-picker__options" role="group" aria-label="Places">
        <button
          type="button"
          aria-pressed={place === null}
          className={`location-option${place === null ? " is-selected" : ""}`}
          onClick={() => choose(null)}
        >
          <strong>Anywhere in our watch</strong>
          <span>{live.sources.length} live places</span>
        </button>
        {list.map((p) => (
          <button
            key={p.id}
            type="button"
            aria-pressed={p.id === place?.id}
            className={`location-option${p.id === place?.id ? " is-selected" : ""}`}
            onClick={() => choose(p)}
          >
            <strong>{placeLabel(p)}</strong>
            <span>
              {countryName(p.country)}
              {p.source ? ` · ${plainOf(p.source).word}` : " · past flood"}
            </span>
          </button>
        ))}
        {query.trim() && matches.length === 0 && <p className="note">No place matches “{query}”.</p>}
      </div>
    </div>
  );
}

function CiteChips({ items }: { items: NumberedCitation[] }) {
  const { answer } = useConsole();
  const eventId = answerEventId(answer);
  return <SourceBadges items={items.map((item) => ({ n: item.n, detail: sourceFromCitation(item.citation, eventId) }))} />;
}

/** Warning-service groups for the chosen place; with no place, all three (Germany, Spain, Europe). */
function warningGroups(place: Place | null): WarningCountry[] {
  return place ? warningCountriesForCountry(place.country, place.name) : ["de", "es", "eu"];
}

/**
 * The bundled reviewed answer (`fixtures/answer.json`) is the Valencia EMSR773 replay, so its agent-written
 * playbook step (and its review status) belongs only to a Valencia replay place, never to a live place.
 */
const REVIEWED_ANSWER_EVENT = "EMSR773";
function showsReviewedAnswer(place: Place | null): boolean {
  return place?.eventId === REVIEWED_ANSWER_EVENT;
}

/** General, sourced guidance first (no gate), then the reviewed step for the matching past event, and Ask. */
function ActionCards({ place }: { place: Place | null }) {
  const desk = useConsole();
  return (
    <>
      <div className="safety-guidance">
        <p>
          <strong>{SAFETY_HEADLINE}.</strong> {CITIZEN_ADVICE}
        </p>
        <p className="note">{CITIZEN_ADVICE_SOURCE}. FloodSense is not an official warning.</p>
        <p>
          <strong>{EMERGENCY_LINE}</strong>
        </p>
        {warningGroups(place).map((c) => (
          <div key={c}>
            <p className="menu-title">Official warnings · {WARNING_LINKS[c].title}</p>
            <ul className="safety-links">
              {WARNING_LINKS[c].links.map((link) => (
                <li key={link.url}>
                  <SafeLink href={link.url}>{link.label}</SafeLink>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
      {showsReviewedAnswer(place) && <ReviewedSteps />}
      <div className="button-row">
        <button
          type="button"
          className="button"
          onClick={() => (place ? desk.openAsk(questionForPlace(place), { place: place.name }) : desk.openAsk())}
        >
          Ask FloodSense
        </button>
      </div>
    </>
  );
}

/** Reviewed playbook actions, in the answer's order, shown only once a person approved them. */
function ReviewedSteps() {
  const desk = useConsole();
  const status = desk.approval.status;
  const actions = actionsVisibleToCitizen(status) ? (desk.answer.playbook_actions ?? []) : [];
  if (status === "pending")
    return (
      <p className="note gate-note" role="status">
        {GATE_LINE}
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

/** Replay place: the replay day's discharge, as a plain status, labelled a past flood. */
function replayReading(place: Place, desk: ReturnType<typeof useConsole>): { view: StatusView; m3s: number | null; day: string } {
  if (place.eventId === "EMSR517") {
    const row = ahrDischarge().find((r) => r.point_id === place.pointId && r.date === desk.ahrDate);
    return { view: row ? BAND_VIEW[dischargeBand(row.discharge_m3s)] : NO_READING, m3s: row?.discharge_m3s ?? null, day: desk.ahrDate };
  }
  const row = rowAt(desk.discharge.rows, place.pointId ?? "", desk.date);
  return { view: row ? BAND_VIEW[dischargeBand(row.discharge_m3s)] : NO_READING, m3s: row?.discharge_m3s ?? null, day: desk.date };
}

const TONE_CARD: Record<StatusView["tone"], string> = {
  warning: "severe",
  elevated: "moderate",
  watch: "moderate",
  neutral: "low",
  normal: "low",
  unknown: "low",
};

/** "Risk right now" for the chosen place, or the whole watch when none is chosen. */
function RiskCard({ ctx }: { ctx: ReturnType<typeof useCitizenPlace> }) {
  const desk = useConsole();
  const { place, live, choose } = ctx;
  if (!place) {
    const lead = worstFirst(live.sources)[0];
    return (
      <div className="risk-summary">
        <p className="eyebrow">Right now, anywhere in our watch</p>
        {!lead ? (
          <p className="note" role="status">
            {live.gauges.state === "loading" || live.euWatch.state === "loading" || live.hazard.state === "loading"
              ? "Loading live readings…"
              : "No live readings right now: the live views did not answer. Try again in a few minutes."}
          </p>
        ) : (
          <>
            <p className="risk-summary__plain">
              <strong>{headlineText(headlineCounts(live.sources))}.</strong>
            </p>
            <PlacesToWatch live={live} limit={3} title="Most notable first" />
          </>
        )}
        <p className="note">Choose a place below for its own reading. Not an official warning.</p>
      </div>
    );
  }
  if (place.kind === "replay") {
    const r = replayReading(place, desk);
    return (
      <div className={`risk-summary risk-summary--${TONE_CARD[r.view.tone]}`}>
        <p className="eyebrow">
          {place.name} · past flood, {formatDay(r.day)}
        </p>
        <p className="risk-summary__plain">
          <StatusChip view={r.view} />{" "}
          <strong>This is a replay of a past flood, not today's situation.</strong>
        </p>
        <details className="disclosure">
          <summary>Details</summary>
          <p className="note">
            {r.m3s === null ? "No river-flow reading for this day." : `${formatM3s(r.m3s)} m³/s modelled river flow (GloFAS) on ${formatDay(r.day)}.`}{" "}
            Status uses FloodSense demo lines, not an official threshold.
          </p>
        </details>
        <div className="button-row">
          <a className="button" href={routeHref("citizen", "replay")}>
            See what happened
          </a>
          <button type="button" className="button ghost" onClick={() => choose(null)}>
            Back to right now
          </button>
        </div>
      </div>
    );
  }
  const s = place.source!;
  const view = plainOf(s);
  return (
    <div className={`risk-summary risk-summary--${TONE_CARD[view.tone]}`}>
      <p className="eyebrow">
        {sourceTitle(s)} · {countryName(s.country)}
      </p>
      <p className="risk-summary__plain">
        <StatusChip view={view} large /> <span className="muted small">{basisLabel(s.kind)}</span>
      </p>
      <p>
        {calmSentence(s.kind, s.status, s.river, s.name)} <LiveSourceBadge n={1} evidence={evidenceFor(live, s)} />
      </p>
      <p className="note">
        {timeText(s.kind, s.measuredAt)}
        {s.live ? " · live" : " · not a fresh live reading"}
      </p>
      <details className="disclosure">
        <summary>Details</summary>
        <p className="note">{s.value}</p>
      </details>
    </div>
  );
}

/** The 2024 Valencia replay, small: the reviewed answer's first sentences with their sources, and a link to Replay. */
function PastFloods() {
  const desk = useConsole();
  const claims = desk.answer.claims.slice(0, WHY_CLAIMS);
  return (
    <section className="card" aria-label="Learn from past floods">
      <header className="card__header">
        <h2 className="card__title">Learn from past floods</h2>
      </header>
      <div className="card__body">
        <p>See how the Ahr flood (July 2021) and the Valencia flood (October 2024) unfolded, moment by moment.</p>
        <div className="button-row">
          <a className="button" href={routeHref("citizen", "replay")}>
            Open Replay
          </a>
        </div>
        <details className="disclosure">
          <summary>What our agents found about Valencia 2024</summary>
          <SourceLegend />
          <ul className="claims">
            {claims.map((claim) => (
              <li key={claim.claim_id}>
                {plainLanguage(claim.text)} <CiteChips items={citationsForClaim(desk.answer, claim.claim_id)} />
              </li>
            ))}
          </ul>
          <p className="note">Replay of October 2024. Not an official warning.</p>
        </details>
      </div>
    </section>
  );
}

export function CitizenOverview() {
  const desk = useConsole();
  const ctx = useCitizenPlace();
  const { place } = ctx;
  return (
    <div className="view">
      <div className="view__intro">
        <div>
          <h2 className="view__title">Is my area at risk right now?</h2>
          <p className="muted">
            Live river readings across Europe in plain words, with a source behind each one. Click a number to see where it
            comes from.
          </p>
        </div>
      </div>
      <div className="grid grid--citizen">
        <section className="card span-2" aria-label="Risk right now">
          <header className="card__header">
            <h2 className="card__title">Risk right now{place ? ` · ${place.name}` : ""}</h2>
          </header>
          <div className="card__body">
            <RiskCard ctx={ctx} />
            <PlacePicker {...ctx} />
            {place?.source && (
              <PlacesToWatch live={ctx.live} limit={3} start={2} exclude={place.id} title="Elsewhere in our watch" />
            )}
            <div className="button-row">
              <a className="button ghost" href={routeHref("citizen", "area")}>
                See my area
              </a>
              <button
                type="button"
                className="button"
                onClick={() => (place ? desk.openAsk(questionForPlace(place), { place: place.name }) : desk.openAsk())}
              >
                Ask FloodSense{place ? ` about ${place.name}` : ""}
              </button>
            </div>
          </div>
        </section>
        <section className="card" aria-label="What should I do?">
          <header className="card__header">
            <h2 className="card__title">What should I do?</h2>
          </header>
          <div className="card__body">
            <ActionCards place={place} />
          </div>
        </section>
        <PastFloods />
      </div>
    </div>
  );
}

/** Valencia replay place: the #36 Place and Rain content (map, discharge in plain language, rain under a disclosure). */
function ValenciaArea() {
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
      <MapPanel exposureDefault={false} fixedEvent="EMSR773" />
      <section className="card" aria-label="Plain-language discharge">
        <p className="section-label">My area · past flood (replay)</p>
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
      </section>
    </div>
  );
}

/** My area follows the chosen place: a live place, a replay place (Valencia or Ahr), or the whole watch. */
export function CitizenArea() {
  const ctx = useCitizenPlace();
  const { place, live } = ctx;
  if (place?.eventId === "EMSR773") return <ValenciaArea />;
  if (place?.eventId === "EMSR517") {
    return (
      <div className="citizen-grid">
        <MapPanel exposureDefault={false} fixedEvent="EMSR517" />
        <section className="card" aria-label="My area">
          <p className="section-label">My area · past flood (replay)</p>
          <h2>{place.name}</h2>
          <RiskCard ctx={ctx} />
        </section>
      </div>
    );
  }
  const same = place?.source ? live.sources.filter((s) => s.id !== place.id && s.river && s.river === place.river) : [];
  return (
    <div className="page-stack">
      <PlacePicker {...ctx} />
      <section className="card" aria-label="My area">
        <header className="card__header">
          <h2 className="card__title">{place ? `My area · ${place.name}` : "My area"}</h2>
        </header>
        <div className="card__body">
          <RiskCard ctx={ctx} />
          {place?.source && <EuWatchMap sources={[place.source, ...same]} />}
          {same.length > 0 && (
            <>
              <h3 className="section-title">Also on the {place?.river}</h3>
              <ol className="ptw-list">
                {worstFirst(same).map((s, i) => (
                  <PlaceRow key={s.id} s={s} n={i + 2} live={live} />
                ))}
              </ol>
            </>
          )}
        </div>
      </section>
    </div>
  );
}

/**
 * Official guidance and links for the chosen place's country. The agent-written playbook step of the bundled
 * Valencia 2024 answer shows only for a Valencia replay place, and only after a person approved it.
 */
export function CitizenActions() {
  const desk = useConsole();
  const { place } = useCitizenPlace();
  return (
    <div className="page-stack">
      <section className="card" aria-label="What to do">
        <header className="card__header">
          <h2 className="card__title">What should I do{place ? ` near ${place.name}` : ""}?</h2>
        </header>
        <div className="card__body">
          <p>
            Follow official warnings first.{" "}
            {place
              ? `Links below are for ${countryName(place.country)}.`
              : "Choose a place on Overview to see the warning services for its country."}{" "}
            {place?.kind === "replay" ? "This place is a replay of a past flood, not a warning." : "FloodSense is not a warning service."}
          </p>
          <ActionCards place={place} />
          <p className="note">
            {showsReviewedAnswer(place) ? `Review status of the Valencia 2024 step: ${desk.approval.status}. ` : ""}
            <a href={routeHref("citizen", "evidence")}>See the evidence</a>.
          </p>
        </div>
      </section>
    </div>
  );
}

const VIEWS = [
  { kind: "gauge" as const, view: "floodsense.gauge_levels", what: "PEGELONLINE gauges (measured)", pipeline: GAUGE_PIPELINE },
  { kind: "model" as const, view: "floodsense.eu_watch", what: "GloFAS points outside Germany (model)", pipeline: GLOFAS_PIPELINE },
  { kind: "valencia" as const, view: "floodsense.hazard_now", what: "Valencia points (model)", pipeline: HAZARD_NOW_PIPELINE },
];

function LiveViewsEvidence({ live, place }: { live: LiveWatch; place: Place | null }) {
  const { openLiveEvidence } = useConsole();
  const kinds = place?.source ? [place.source.kind] : place ? [] : VIEWS.map((v) => v.kind);
  if (kinds.length === 0) return <p className="note">This place is a past flood; it has no live view behind it.</p>;
  return (
    <ul className="live-views">
      {VIEWS.filter((v) => kinds.includes(v.kind)).map((v) => {
        const meta = metaFor(live, v.kind);
        const fetched = meta.executedAt ?? (typeof meta.fetchedAt === "number" ? new Date(meta.fetchedAt).toISOString() : null);
        const sample = place?.source ?? live.sources.find((s) => s.kind === v.kind);
        return (
          <li key={v.view} className="evidence-block">
            <h3>{v.view}</h3>
            <p className="note">
              {v.what}: {v.pipeline.join(" → ")}
            </p>
            <dl className="kv">
              <div>
                <dt>Zetaris query id</dt>
                <dd>{meta.queryId ?? "not sent by the API for this read"}</dd>
              </div>
              <div>
                <dt>Fetched</dt>
                <dd>{fetched ?? "not loaded yet"}</dd>
              </div>
              <div>
                <dt>Places</dt>
                <dd>{live.sources.filter((s) => s.kind === v.kind).length}</dd>
              </div>
            </dl>
            {sample && (
              <button type="button" className="button ghost" onClick={() => openLiveEvidence(evidenceForSource(sample, meta))}>
                Open {place?.source ? place.name : "an example"} in the evidence panel
              </button>
            )}
          </li>
        );
      })}
    </ul>
  );
}

export function CitizenEvidence() {
  const desk = useConsole();
  const ctx = useCitizenPlace();
  const point = pointById(desk.points, desk.pointId);
  const row = rowAt(desk.discharge.rows, desk.pointId, desk.date);
  const provenance = row ? provenanceForSource(row.source, desk.provenance.rows) : undefined;

  return (
    <div className="page-stack">
      <section className="card" aria-label="Live sources">
        <p className="section-label">Live sources</p>
        <h2>{ctx.place ? `Behind ${ctx.place.name}` : "Behind right now"}</h2>
        <p className="muted">The live views FloodSense reads through Zetaris, with their query ids and fetch times.</p>
        <LiveViewsEvidence live={ctx.live} place={ctx.place} />
      </section>
      <section className="card" aria-label="Why this source">
        <p className="section-label">Past event · Valencia 2024 (replay)</p>
        <h2>
          {point ? point.name : desk.pointId} on {formatDay(desk.date)}
        </h2>
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
        <h2>Sources behind the reviewed answer</h2>
        <CitationList answer={desk.answer} />
      </section>
    </div>
  );
}
