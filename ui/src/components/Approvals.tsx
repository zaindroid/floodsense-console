import { plainLanguage } from "../lib/plain";
import { useEffect, useId, useState } from "react";
import { useConsole } from "../context/ConsoleContext";
import { citationMarks, citationsById } from "../lib/citations";
import { decisionNoteError } from "../lib/decision";
import { routeHref } from "../lib/route";
import type { ApprovalStatus } from "../types/contract";
import { GroundingBadge } from "./ReviewColumn";

/** The HITL home. One queue item per playbook action on the answer; this replay has one approval in state. */
export function Approvals() {
  const desk = useConsole();
  const action = desk.answer.playbook_actions?.[0];
  const judge = desk.answer.judge;
  const headingId = useId();
  const cited = action ? citationsById(desk.answer, action.citation_ids) : [];
  const supported = judge?.claims.filter((claim) => claim.grounding === "supported").length ?? 0;

  return (
    <div className="approvals">
      <section className="card queue" aria-label="Approval queue">
        <p className="section-label">Queue</p>
        <ul>
          <li>
            <div className="queue-item is-selected">
              <span className="queue-title">{action ? action.title : "Reviewed answer"}</span>
              <span className={`badge badge-status-${desk.approval.status}`}>{desk.approval.status}</span>
            </div>
          </li>
        </ul>
        <p className="note">
          {desk.approval.status === "pending" ? "1 item waits for a decision." : "Nothing is pending."}
        </p>
      </section>
      <section className="card approval-detail" aria-labelledby={headingId}>
        <p className="section-label">Playbook action</p>
        <h2 id={headingId}>{action ? action.title : "No playbook action on this answer"}</h2>
        <DecisionBar />
        {action && (
          <>
            <p>
              {plainLanguage(action.detail)} {cited.length > 0 && <span className="cite-marks">{citationMarks(cited)}</span>}
            </p>
            <details className="disclosure">
              <summary>Technical detail</summary>
              <p className="note">action_id {action.action_id}</p>
            </details>
          </>
        )}
        <dl className="kpis">
          <div>
            <dt>Status</dt>
            <dd>{desk.approval.status}</dd>
          </div>
          <div>
            <dt>Judge overall</dt>
            <dd>{judge ? judge.overall_score.toFixed(2) : "—"}</dd>
          </div>
          <div>
            <dt>Claims supported</dt>
            <dd>{judge ? `${supported} / ${judge.claims.length}` : "—"}</dd>
          </div>
          <div>
            <dt>Citations</dt>
            <dd>{desk.answer.citations.length}</dd>
          </div>
        </dl>
        <h3>Reviewed answer</h3>
        <p>{desk.answer.question}</p>
        {judge && (
          <ul className="claim-summary">
            {judge.claims.map((claim) => (
              <li key={claim.claim_id}>
                <GroundingBadge grounding={claim.grounding} score={claim.score} />{" "}
                {plainLanguage(desk.answer.claims.find((item) => item.claim_id === claim.claim_id)?.text ?? "")}
              </li>
            ))}
          </ul>
        )}
        <div className="button-row">
          <button type="button" className="button" onClick={() => desk.openEvidence("discharge")}>
            Open evidence
          </button>
          <a className="button ghost" href={routeHref("insurer", "review")}>
            Read the review chain
          </a>
        </div>
      </section>
    </div>
  );
}

/** Sticky so Approve, Edit, and Reject stay in reach while the summary scrolls. */
function DecisionBar() {
  const desk = useConsole();
  const [note, setNote] = useState(desk.approval.note ?? "");
  const [noteError, setNoteError] = useState("");
  const locked = desk.approval.status !== "pending";

  useEffect(() => {
    setNote(desk.approval.note ?? "");
    setNoteError("");
  }, [desk.approval]);

  function commit(status: ApprovalStatus) {
    const error = decisionNoteError(status, note);
    if (error) {
      setNoteError(error);
      return;
    }
    setNoteError("");
    desk.decide(status, note.trim());
  }

  return (
    <div className="decision-bar" role="group" aria-label="Decision">
      <label className="field">
        Review note
        <textarea
          value={note}
          onChange={(event) => setNote(event.target.value)}
          rows={2}
          disabled={locked}
          placeholder="Required for edit or reject. Nothing is sent."
        />
      </label>
      {noteError && (
        <p className="error-text" role="alert">
          {noteError}
        </p>
      )}
      <div className="button-row">
        <button type="button" className="button primary" disabled={locked} onClick={() => commit("approved")}>
          Approve
        </button>
        <button type="button" className="button" disabled={locked} onClick={() => commit("edited")}>
          Edit
        </button>
        <button type="button" className="button danger" disabled={locked} onClick={() => commit("rejected")}>
          Reject
        </button>
        {locked && (
          <button type="button" className="button ghost" onClick={desk.resetApproval}>
            Reset preview
          </button>
        )}
        <p className="status-line" role="status">
          Status <strong>{desk.approval.status}</strong>
        </p>
      </div>
      <p className="note">Local preview only. Approving does not send an outbound action and does not change the Judge scores.</p>
    </div>
  );
}
