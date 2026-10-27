import { useCallback, useEffect, useId, useState } from "react";
import { useConsole } from "../context/ConsoleContext";
import { fetchApproval, postApproval } from "../api/liveRun";
import { apiBaseUrl } from "../api/config";
import { plainLanguage } from "../lib/plain";
import { routeHref } from "../lib/route";
import { getAwaitingRunId, onAwaitingRunId, setAwaitingRunId } from "../lib/lastRun";
import {
  actionChip,
  adoptPlaybook,
  buildApprovalBody,
  cardStatus,
  decisionStatusLine,
  errorDetail,
  reviewEvidence,
  shortTitle,
  sitesLine,
  type ApprovalBody,
  type CardStatus,
  type PlaybookItem,
  type ReviewEvidence,
} from "../lib/hitl";
import "../styles/hitl.css";

export interface QueueSource {
  /** null: the packed fixture, decided locally. */
  runId: string | null;
  summary: string;
  items: PlaybookItem[];
  judgeScore: number | null;
  judgePasses: boolean | null;
  status: CardStatus;
  note: string | null;
  evidence: ReviewEvidence;
}

const rec = (v: unknown): Record<string, unknown> | null => (v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : null);

/** Pure: the queue for a GET /runs/{id}/approval body. */
export function queueFromApproval(runId: string, body: Record<string, unknown>): QueueSource {
  const js = rec(body.judge_summary);
  const approval = rec(body.approval);
  return {
    runId,
    summary: typeof body.summary === "string" ? body.summary : "",
    items: adoptPlaybook(body.playbook),
    judgeScore: typeof js?.overall === "number" ? js.overall : null,
    judgePasses: typeof js?.passes === "boolean" ? js.passes : null,
    status: cardStatus(typeof body.status === "string" ? body.status : null, typeof approval?.status === "string" ? approval.status : null),
    note: null,
    evidence: reviewEvidence(body),
  };
}

/** Pure: the edit drafts, starting from every outbound action's current draft. */
export function initialDrafts(items: readonly PlaybookItem[]): Record<string, string> {
  return Object.fromEntries(items.filter((i) => i.outbound).map((i) => [i.actionId, i.draftMessage ?? ""]));
}

/** The HITL home. One card per proposed action; one decision covers the whole run. Nothing is sent from here. */
export function Approvals() {
  const desk = useConsole();
  const [runId, setRunId] = useState<string | null>(() => getAwaitingRunId());
  const [live, setLive] = useState<QueueSource | null>(null);
  const [loadNote, setLoadNote] = useState<string | null>(null);
  useEffect(() => onAwaitingRunId(setRunId), []);
  useEffect(() => {
    if (!runId) {
      setLive(null);
      return;
    }
    let gone = false;
    void fetchApproval(runId)
      .then(({ status, body }) => {
        if (gone) return;
        if (status === 200 && body) {
          setLive(queueFromApproval(runId, body));
          setLoadNote(null);
        } else {
          setLive(null);
          setLoadNote(
            status === 409
              ? `Run ${runId} is no longer waiting for a decision. Showing the packed example.`
              : `Run ${runId} could not be loaded (${status}${errorDetail(body) ? `: ${errorDetail(body)}` : ""}). Showing the packed example.`,
          );
          if (status === 404 || status === 409) setAwaitingRunId(null);
        }
      })
      .catch(() => {
        if (!gone) setLoadNote("The API could not be reached. Showing the packed example.");
      });
    return () => {
      gone = true;
    };
  }, [runId]);

  const answer = desk.answer;
  const fixture: QueueSource = {
    runId: null,
    summary: answer.question,
    items: (answer.playbook_actions ?? []).map((a) => ({
      actionId: a.action_id,
      horizonH: null,
      text: plainLanguage(a.detail),
      claimIds: [],
      outbound: a.outbound ?? false,
      released: a.released ?? false,
      actionType: a.action_type ?? null,
      title: a.title || shortTitle(a.detail),
      targetRegion: a.target_region ?? null,
      affectedSiteCount: a.affected_site_count ?? null,
      draftMessage: a.draft_message ?? null,
    })),
    judgeScore: answer.judge?.overall_score ?? null,
    judgePasses: null,
    status: desk.approval.status,
    note: desk.approval.note ?? null,
    evidence: reviewEvidence({
      claims: answer.claims.map((c) => ({ ...c, citations: answer.citations.filter((ci) => ci.claim_id === c.claim_id) })),
      judge: answer.judge?.claims ?? [],
    }),
  };
  const source = live ?? fixture;

  const decide = useCallback(
    async (body: ApprovalBody): Promise<string | null> => {
      if (!source.runId) {
        const status: CardStatus = body.action === "approve" ? "approved" : body.action === "edit" ? "edited" : "rejected";
        desk.decide(status, body.reviewer_note ?? "");
        return null;
      }
      const result = await postApproval(source.runId, body);
      if (!result.ok) return result.message;
      const approval = rec(result.body?.approval);
      const status = cardStatus(typeof result.body?.status === "string" ? result.body.status : null, typeof approval?.status === "string" ? approval.status : null);
      setLive((cur) =>
        cur
          ? {
              ...cur,
              status: status === "pending" ? (body.action === "reject" ? "rejected" : body.action === "edit" ? "edited" : "approved") : status,
              note: body.reviewer_note ?? null,
              items: cur.items.map((i) => (body.draft_messages?.[i.actionId] ? { ...i, draftMessage: body.draft_messages[i.actionId] } : i)),
            }
          : cur,
      );
      setAwaitingRunId(null);
      return null;
    },
    [desk, source.runId],
  );

  const [editing, setEditing] = useState(false);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const startEdit = () => {
    setDrafts(initialDrafts(source.items));
    setEditing(true);
  };
  const ev = source.evidence;
  const reviewHref = source.runId ? `${apiBaseUrl()}/runs/${encodeURIComponent(source.runId)}` : routeHref("insurer", "review");

  return (
    <div className="approvals hitl">
      <section className="card" aria-label="Approval queue">
        <p className="section-label">Queue</p>
        <p className="note">{source.runId ? `Live run ${source.runId}` : "Packed example run · local preview only."}</p>
        {loadNote && <p className="note">{loadNote}</p>}
        <dl className="kpis">
          <div>
            <dt>Status</dt>
            <dd>{source.status}</dd>
          </div>
          <div>
            <dt>Judge overall</dt>
            <dd>{source.judgeScore !== null ? source.judgeScore.toFixed(2) : "—"}</dd>
          </div>
          <div>
            <dt>Claims supported</dt>
            <dd>{ev.scored > 0 ? `${ev.supported} / ${ev.claims.length}` : "—"}</dd>
          </div>
          <div>
            <dt>Citations</dt>
            <dd>{ev.citations}</dd>
          </div>
        </dl>
        {source.items.length === 0 ? (
          <p className="note">No proposed action on this run.</p>
        ) : (
          <ul className="approval-list">
            {source.items.map((item) => (
              <ActionCard
                key={item.actionId}
                item={item}
                source={source}
                editing={editing && item.outbound}
                draft={drafts[item.actionId] ?? item.draftMessage ?? ""}
                onDraft={(text) => setDrafts((d) => ({ ...d, [item.actionId]: text }))}
              />
            ))}
          </ul>
        )}
        <DecisionBar
          source={source}
          editing={editing}
          drafts={drafts}
          onStartEdit={startEdit}
          onCancelEdit={() => setEditing(false)}
          onDecide={async (body) => {
            const message = await decide(body);
            if (!message) setEditing(false);
            return message;
          }}
        />
        <h3>Reviewed answer</h3>
        <p>{plainLanguage(source.summary)}</p>
        {ev.claims.length > 0 && (
          <ul className="claim-summary">
            {ev.claims.map((claim) => (
              <li key={claim.id}>
                {claim.grounding ? (
                  <span className={`badge badge-${claim.grounding}`}>
                    {claim.grounding}
                    {claim.score !== null ? ` ${claim.score.toFixed(2)}` : ""}
                  </span>
                ) : (
                  <span className="badge">not scored</span>
                )}{" "}
                {plainLanguage(claim.text)}
              </li>
            ))}
          </ul>
        )}
        <div className="button-row">
          <button type="button" className="button" onClick={() => desk.openEvidence("discharge")}>
            Open evidence
          </button>
          {source.runId ? (
            <a className="button ghost" href={reviewHref} target="_blank" rel="noreferrer">
              Read the review chain of run {source.runId}
            </a>
          ) : (
            <a className="button ghost" href={reviewHref}>
              Read the review chain
            </a>
          )}
          {!source.runId && source.status !== "pending" && (
            <button type="button" className="button ghost" onClick={desk.resetApproval}>
              Reset preview
            </button>
          )}
        </div>
      </section>
    </div>
  );
}

function JudgeBadge({ score, passes }: { score: number | null; passes: boolean | null }) {
  if (score === null) return <span className="judge-badge judge-badge--none">Judge · not scored</span>;
  const tone = passes === false || score < 0.7 ? "warn" : "ok";
  return (
    <span className={`judge-badge judge-badge--${tone}`} title="Judge overall score for this run">
      Judge {score.toFixed(2)}
      {passes === null ? "" : passes ? " · passes" : " · does not pass"}
    </span>
  );
}

/** One proposed action: content and its draft. No buttons; the decision is run level. */
function ActionCard({
  item,
  source,
  editing,
  draft,
  onDraft,
}: {
  item: PlaybookItem;
  source: QueueSource;
  editing: boolean;
  draft: string;
  onDraft: (text: string) => void;
}) {
  const draftId = useId();
  return (
    <li className={`approval approval--${source.status}`}>
      <div className="approval__summary">
        <span className={`chip chip--${item.actionType ?? "action"}`}>{actionChip(item.actionType)}</span>
        <strong>{item.title}</strong>
        <span className="muted small">
          {item.targetRegion ?? "region not stated"} · {sitesLine(item.affectedSiteCount)}
          {item.horizonH !== null ? ` · ${item.horizonH} h` : ""}
        </span>
        <JudgeBadge score={source.judgeScore} passes={source.judgePasses} />
        <span className={`status status--${source.status}`}>{source.status}</span>
      </div>
      <div className="approval__detail">
        {item.text && item.text !== item.title && <p>{plainLanguage(item.text)}</p>}
        <p className="eyebrow" id={draftId}>
          Draft message (sent only after approval)
        </p>
        {editing ? (
          <textarea aria-labelledby={draftId} value={draft} rows={5} onChange={(e) => onDraft(e.target.value)} />
        ) : item.draftMessage ? (
          <blockquote className="draft">{item.draftMessage}</blockquote>
        ) : (
          <p className="note">{item.outbound ? "No draft was built for this action." : "Internal action: no outbound message."}</p>
        )}
      </div>
    </li>
  );
}

function DecisionBar({
  source,
  editing,
  drafts,
  onStartEdit,
  onCancelEdit,
  onDecide,
}: {
  source: QueueSource;
  editing: boolean;
  drafts: Record<string, string>;
  onStartEdit: () => void;
  onCancelEdit: () => void;
  onDecide: (body: ApprovalBody) => Promise<string | null>;
}) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const n = source.items.length;
  const anyOutbound = source.items.some((i) => i.outbound);
  const locked = source.status !== "pending" || busy;

  const submit = async (action: ApprovalBody["action"]) => {
    const built = buildApprovalBody(action, note, action === "edit" ? drafts : {}, source.items);
    if (!built.ok) {
      setError(built.message);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const message = await onDecide(built.body);
      if (message) setError(message);
    } finally {
      setBusy(false);
    }
  };

  if (source.status !== "pending") {
    return (
      <p className={`status-line status-line--${source.status === "edited" ? "approved" : source.status}`} role="status">
        {decisionStatusLine(source.status)}
        {source.note && <> Note: “{source.note}”</>}
      </p>
    );
  }
  return (
    <div className="decision-bar hitl-decision" role="group" aria-label="Decision for this run">
      <p className="hitl-scope">
        This decision applies to all {n} proposed action{n === 1 ? "" : "s"} in this run. Nothing is sent: outbound actions are drafts in this demo.
      </p>
      <label className="field">
        Reviewer note
        <input
          type="text"
          placeholder="Required to reject or edit."
          value={note}
          onChange={(e) => setNote(e.target.value)}
          disabled={locked}
        />
      </label>
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
      <div className="approval__actions">
        {editing ? (
          <>
            <button type="button" className="button primary" disabled={locked} onClick={() => void submit("edit")}>
              Save edits and approve
            </button>
            <button type="button" className="button" disabled={busy} onClick={() => { setError(null); onCancelEdit(); }}>
              Cancel edit
            </button>
          </>
        ) : (
          <>
            <button type="button" className="button danger" disabled={locked} onClick={() => void submit("reject")}>
              Reject run
            </button>
            {anyOutbound && (
              <button type="button" className="button" disabled={locked} onClick={onStartEdit}>
                Edit drafts
              </button>
            )}
            <button type="button" className="button primary" disabled={locked} onClick={() => void submit("approve")}>
              Approve run
            </button>
          </>
        )}
      </div>
    </div>
  );
}
