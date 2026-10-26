import { useEffect, useId, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from "react";
import { askFloodSense, capTurns, DEFAULT_EVENT_ID, followUpThreadId, runBadge } from "../api/ask";
import { fetchRecordedRun, replayRunId, type RecordedRun } from "../api/replay";
import { useConsole } from "../context/ConsoleContext";
import { citationMarks, citationsForClaim, numberedCitations } from "../lib/citations";
import { servingLabel, servingQualifier } from "../lib/format";
import { PROVIDER_LABELS } from "../lib/llmProvider";
import { routeHref } from "../lib/route";

const FOCUSABLE =
  'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), summary, [tabindex]:not([tabindex="-1"])';

interface Turn {
  id: number;
  question: string;
  run: RecordedRun | null;
  error: string | null;
}

/**
 * Gmail-style dock, bottom right. Non-modal: it never covers or pushes the page, and it never opens on a route change.
 * The first message is the recorded run (VITE_REPLAY_RUN_ID) or the fixture already on the desk. The composer posts
 * a question to POST /runs; each answer is labelled by its own served_from, so a replay is never called live.
 */
export function AskFloodSense() {
  const desk = useConsole();
  const { answer, askOpen, closeAsk, evidenceOpen, llmProvider, llmProviders } = desk;
  const panelId = useId();
  const titleId = useId();
  const panelRef = useRef<HTMLElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const launcherRef = useRef<HTMLButtonElement>(null);
  // A ref, so the drawer opening does not re-run the effect and pull focus around.
  const evidenceOpenRef = useRef(evidenceOpen);
  evidenceOpenRef.current = evidenceOpen;
  // Non-modal: hand focus back to the launcher only if it was still in the panel when it closed.
  const restoreFocusRef = useRef(false);
  const dismiss = () => {
    restoreFocusRef.current = Boolean(panelRef.current?.contains(document.activeElement));
    closeAsk();
  };
  const dismissRef = useRef(dismiss);
  dismissRef.current = dismiss;
  const serving = servingLabel(answer);
  const when = serving.kind === "cached" ? `${serving.text} UTC` : serving.text;
  const badge = serving.kind === "live" ? "Live" : servingQualifier(serving) === "cache" ? "Cached" : "Replay";
  const hasLayerC = answer.citations.some((citation) => citation.layer === "c");
  // Optional recorded run. Unset or failed keeps the fixture answer.
  const [recorded, setRecorded] = useState<RecordedRun | null>(null);
  useEffect(() => {
    const runId = replayRunId();
    if (!runId) return;
    const controller = new AbortController();
    void fetchRecordedRun(runId, undefined, controller.signal).then((run) => {
      if (!controller.signal.aborted) setRecorded(run);
    });
    return () => controller.abort();
  }, []);

  // Conversation typed in this popup. Newest at the bottom; it survives closing the popup.
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [pending, setPending] = useState<{ question: string; started: number; provider: string } | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const inflightRef = useRef<AbortController | null>(null);
  const sendingRef = useRef(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const lastTurnRef = useRef<HTMLDivElement>(null);
  const nearBottomRef = useRef(true);
  const draftRef = useRef(draft);
  draftRef.current = draft;
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  useEffect(() => () => inflightRef.current?.abort(), []);
  useEffect(() => {
    if (!pending) return;
    const tick = () => setElapsed(Math.floor((Date.now() - pending.started) / 1000));
    tick();
    const timer = window.setInterval(tick, 1000);
    return () => window.clearInterval(timer);
  }, [pending]);
  // A new answer: bring that turn's start into view.
  useEffect(() => {
    if (turns.length === 0) return;
    lastTurnRef.current?.scrollIntoView?.({ block: "start" });
  }, [turns]);
  // Anything else (pending bubble, reopening): follow the bottom only if the reader is already there.
  useEffect(() => {
    const el = scrollRef.current;
    if (el && nearBottomRef.current) el.scrollTop = el.scrollHeight;
  }, [pending, askOpen]);

  const send = async () => {
    const question = draft.trim();
    if (!question || sendingRef.current) return;
    sendingRef.current = true;
    const controller = new AbortController();
    inflightRef.current = controller;
    const allowed = llmProviders.includes(llmProvider);
    // Follow-ups continue the thread of the newest answered run.
    const previous = [...turns].reverse().find((t) => t.run)?.run ?? null;
    setDraft("");
    setPending({ question, started: Date.now(), provider: allowed ? PROVIDER_LABELS[llmProvider] : "default provider" });
    const result = await askFloodSense(
      {
        question,
        eventId: DEFAULT_EVENT_ID,
        provider: llmProvider,
        allowedProviders: llmProviders,
        threadId: followUpThreadId(previous),
      },
      controller.signal,
    );
    if (controller.signal.aborted) return;
    sendingRef.current = false;
    inflightRef.current = null;
    setPending(null);
    const id = Date.now();
    setTurns((prev) =>
      capTurns([
        ...prev,
        result.ok ? { id, question, run: result.run, error: null } : { id, question, run: null, error: result.message },
      ]),
    );
  };
  const cancel = () => {
    inflightRef.current?.abort();
    inflightRef.current = null;
    sendingRef.current = false;
    setPending(null);
  };
  const onComposerKey = (event: ReactKeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      void send();
    }
  };

  useEffect(() => {
    if (!askOpen) return;
    closeRef.current?.focus();
    const launcher = launcherRef.current;
    restoreFocusRef.current = false;
    const onKey = (event: KeyboardEvent) => {
      const root = panelRef.current;
      if (!root) return;
      // The Evidence drawer is modal and handles its own Escape. Another open menu
      // (chip, bell, account) keeps its own Escape, so only dismiss from inside the panel.
      const active = document.activeElement;
      const inside =
        active === null ||
        active === document.body ||
        active === launcherRef.current ||
        (active instanceof Node && root.contains(active));
      if (event.key === "Escape" && event.isComposing) return;
      if (event.key === "Escape" && !evidenceOpenRef.current && inside && !event.defaultPrevented) {
        event.preventDefault();
        // First Esc in a non-empty composer clears the draft; the next one closes.
        if (active === textareaRef.current && draftRef.current !== "") {
          setDraft("");
          return;
        }
        dismissRef.current();
        return;
      }
      if (event.key !== "Tab") return;
      if (!(active instanceof Node) || !root.contains(active)) return;
      const nodes = [...root.querySelectorAll<HTMLElement>(FOCUSABLE)];
      if (nodes.length === 0) return;
      const first = nodes[0];
      const last = nodes[nodes.length - 1];
      if (event.shiftKey && active === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && active === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      if (restoreFocusRef.current) launcher?.focus();
    };
  }, [askOpen, closeAsk]);

  return (
    <div className="ask-dock">
      {askOpen && (
        <section className="ask-panel" id={panelId} role="dialog" aria-modal="false" aria-labelledby={titleId} ref={panelRef}>
          <header className="ask-head">
            <div>
              <h2 id={titleId}>Ask FloodSense</h2>
              {recorded ? (
                <p className="ask-badge ask-badge-replay">Recorded run · not live</p>
              ) : (
                <p className={`ask-badge ask-badge-${serving.kind}`}>
                  {badge} · {when}
                </p>
              )}
            </div>
            <button ref={closeRef} type="button" className="icon-button" aria-label="Close Ask FloodSense" onClick={dismiss}>
              <CloseIcon />
            </button>
          </header>
          <div
            className="ask-body"
            ref={scrollRef}
            onScroll={(event) => {
              const el = event.currentTarget;
              nearBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 48;
            }}
          >
            <div className="ask-turn">
              {recorded ? (
                <RecordedAnswer run={recorded} badge={`Recorded run · not live · ${recorded.runId}`} />
              ) : (
                <>
                  <p className="note">
                    Reviewed answer, {servingQualifier(serving)}, run {serving.runId}. Not live.
                  </p>
                  <p className="ask-question">{answer.question}</p>
                  <ul className="ask-claims">
                    {answer.claims.map((claim) => (
                      <li key={claim.claim_id}>
                        {claim.text} <span className="cite-marks">{citationMarks(citationsForClaim(answer, claim.claim_id))}</span>
                      </li>
                    ))}
                  </ul>
                  <ol className="ask-citations">
                    {numberedCitations(answer).map(({ n, citation }) => (
                      <li key={citation.citation_id}>
                        [{n}] {citation.title} · {citation.publisher}
                      </li>
                    ))}
                  </ol>
                  <details className="disclosure">
                    <summary>How I got this</summary>
                    <ol className="ask-trace">
                      {answer.evidence.map((evidence) => (
                        <li key={evidence.query_id}>
                          <p className="menu-title">{evidence.view}</p>
                          <p className="note">
                            {evidence.query_id} · {evidence.row_count} row{evidence.row_count === 1 ? "" : "s"} ·{" "}
                            {evidence.executed_at_utc}
                          </p>
                          <pre className="sql">{evidence.sql}</pre>
                        </li>
                      ))}
                    </ol>
                    <p className="note">Fixture SQL, packed with the answer.</p>
                    {!hasLayerC && <p className="note">This answer has no layer (c) document citations.</p>}
                  </details>
                </>
              )}
              <div className="button-row">
                <button
                  type="button"
                  className="button"
                  onClick={() => {
                    // Move focus out first, so the drawer records the launcher as its opener.
                    launcherRef.current?.focus();
                    dismiss();
                    desk.openEvidence("discharge");
                  }}
                >
                  Open evidence
                </button>
              </div>
            </div>
            {turns.map((turn, i) => (
              <div
                key={turn.id}
                className="ask-turn"
                ref={i === turns.length - 1 ? lastTurnRef : undefined}
                aria-live={i === turns.length - 1 ? "polite" : undefined}
              >
                <p className="ask-bubble">{turn.question}</p>
                {turn.run ? (
                  <RecordedAnswer run={turn.run} badge={runBadge(turn.run)} />
                ) : (
                  <p className="ask-error">
                    {turn.error}
                  </p>
                )}
              </div>
            ))}
            {pending && (
              <div className="ask-turn">
                <p className="ask-bubble">{pending.question}</p>
                <p className="ask-working">
                  <span role="status">Working on your question</span>
                  <span aria-hidden="true"> · {elapsed} s</span> · {pending.provider}. The answer arrives when the run
                  reaches review.{" "}
                  <button type="button" className="ask-link" onClick={cancel}>
                    Cancel
                  </button>
                </p>
              </div>
            )}
          </div>
          <form
            className="ask-composer"
            onSubmit={(event) => {
              event.preventDefault();
              void send();
            }}
          >
            <textarea
              ref={textareaRef}
              aria-label="Your question"
              rows={2}
              value={draft}
              placeholder="Ask about flood risk, exposure, or a place…"
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={onComposerKey}
            />
            <button type="submit" className="button" disabled={pending !== null || draft.trim() === ""}>
              Send
            </button>
          </form>
        </section>
      )}
      <button
        ref={launcherRef}
        type="button"
        className="ask-launcher"
        aria-expanded={askOpen}
        aria-controls={askOpen ? panelId : undefined}
        onClick={() => (askOpen ? dismiss() : desk.openAsk())}
      >
        Ask FloodSense
      </button>
    </div>
  );
}

/** An agent run, labelled by its own served_from: live, cache or replay. */
function RecordedAnswer({ run, badge }: { run: RecordedRun; badge: string }) {
  const kind = run.servedFrom === "live" ? "live" : run.servedFrom === "cache" ? "cached" : "replay";
  return (
    <>
      <p className={`ask-badge ask-badge-${kind}`}>{badge}</p>
      {run.servedFrom !== "live" && run.label !== badge && <p className="note">{run.label}</p>}
      {run.status === "awaiting_approval" && (
        <p className="note ask-approval">
          Pending your approval on the <a href={routeHref("insurer", "approvals")}>Approvals page</a> · run {run.runId}
        </p>
      )}
      <p className="ask-question">{run.summary}</p>
      <ul className="ask-claims">
        {run.claims.map((claim) => (
          <li key={claim.id}>
            {claim.text}{" "}
            {run.flaggedClaimIds.includes(claim.id) && <strong className="note">[Flagged by Judge] </strong>}
            {claim.citations.map((citation) => (
              <span key={citation.id} className="cite-marks" title={citation.quote ?? citation.title}>
                [{citation.layer}: {citation.title}
                {citation.page !== null ? `, p. ${citation.page}` : ""}]{" "}
              </span>
            ))}
            {claim.citations
              .filter((citation) => citation.layer === "c" && citation.quote)
              .map((citation) => (
                <blockquote key={`${citation.id}-q`} className="note ask-quote">
                  “{citation.quote}” {citation.publisher ?? ""}
                  {citation.licence ? ` · ${citation.licence}` : ""}
                </blockquote>
              ))}
            {/* One attribution line per source, not one per quote. */}
            {[
              ...new Set(
                claim.citations
                  .filter((citation) => citation.layer === "c" && citation.quote && citation.attribution)
                  .map((citation) => citation.attribution as string),
              ),
            ].map((attribution) => (
              <p key={attribution} className="note">
                {attribution}
              </p>
            ))}
          </li>
        ))}
      </ul>
      {run.judgeOverall !== null && (
        <p className="note">
          Judge score {run.judgeOverall.toFixed(2)}
          {run.judgePasses === null ? "" : run.judgePasses ? " · passes" : " · does not pass"}
          {run.hallucinationRate === null ? "" : ` · hallucination ${Math.round(run.hallucinationRate * 100)} %`}
        </p>
      )}
      <details className="disclosure">
        <summary>How I got this</summary>
        <ol className="ask-trace">
          {run.trace.map((step, i) => (
            <li key={`${step.seq}-${i}`}>
              <p className="menu-title">{step.node}</p>
              <p className="note">{step.summary}</p>
            </li>
          ))}
        </ol>
        <p className="note">Trace recorded with run {run.runId}.</p>
      </details>
    </>
  );
}

function CloseIcon() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
      <path d="M6 6l12 12M18 6L6 18" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}
