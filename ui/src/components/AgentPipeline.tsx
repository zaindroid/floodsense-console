import { Fragment, type CSSProperties } from "react";
import type { RecordedRun } from "../api/replay";
import { buildPipeline, formatLatency, type PipelineNode } from "../lib/pipeline";

const STATUS_TEXT: Record<PipelineNode["status"], string> = {
  done: "done",
  flag: "flagged",
  waiting: "waiting",
  skipped: "not run",
};

/** The agent graph for one run: Scope → … → Human approval, with the revise and repair loops. */
export function AgentPipeline({ run, compact = false, title }: { run: RecordedRun; compact?: boolean; title?: string }) {
  const model = buildPipeline(run);
  // The key restarts the reveal when another run is shown.
  return (
    <section className={`agp${compact ? " agp-compact" : ""}`} aria-label={title ?? "Agent pipeline"} key={run.runId}>
      <header className="agp-head">
        <p className="agp-title">{title ?? "Agent pipeline"}</p>
        <p className="agp-meta">
          run {run.runId} · {formatLatency(model.totalLatencyMs)} total
          {model.reviseRounds > 0 && ` · ${model.reviseRounds} revise round${model.reviseRounds === 1 ? "" : "s"}`}
          {model.repairRounds > 0 && ` · ${model.repairRounds} repair round${model.repairRounds === 1 ? "" : "s"}`}
        </p>
      </header>
      <ol className="agp-flow">
        {model.nodes.map((node, i) => (
          <Fragment key={node.id}>
            {i > 0 && (
              <li className="agp-edge" aria-hidden="true" style={{ "--i": i } as CSSProperties}>
                {node.id === "skeptic" && model.reviseRounds > 0 ? (
                  <span className="agp-loop agp-loop-revise" title="Skeptic sent the chain back to the Investigator">
                    ⇄ revise ×{model.reviseRounds}
                  </span>
                ) : (
                  <span className="agp-arrow">→</span>
                )}
              </li>
            )}
            <li className={`agp-node agp-${node.status}`} style={{ "--i": i } as CSSProperties} data-node={node.id}>
              <div className="agp-node-top">
                <span className="agp-name">{node.label}</span>
                <span className={`agp-status agp-status-${node.status}`}>{STATUS_TEXT[node.status]}</span>
              </div>
              <p className="agp-line">
                {formatLatency(node.latencyMs)}
                {node.lane && node.lane !== "none" ? ` · lane ${node.lane}` : ""}
                {node.runs > 1 ? ` · ran ${node.runs}×` : ""}
              </p>
              {node.summary && <p className="agp-summary">{node.summary}</p>}
              {node.badges.length > 0 && (
                <ul className="agp-badges" aria-label={`${node.label} sources`}>
                  {node.badges.map((b) => (
                    <li key={b.text} className={`agp-badge agp-badge-${b.kind}`}>
                      {b.text}
                    </li>
                  ))}
                </ul>
              )}
              {node.id === "judge" && model.repairRounds > 0 && (
                <p className="agp-loop agp-loop-repair" title="Judge flagged claims; Playbook rewrote them to their evidence">
                  ↺ repair ×{model.repairRounds} via Playbook
                </p>
              )}
            </li>
          </Fragment>
        ))}
      </ol>
      {model.board && (
        <p className="agp-board">
          <span className="agp-badge agp-badge-world">World Model</span>{" "}
          {model.board.states.map((s) => (
            <span key={s.id} className={`agp-hyp agp-hyp-${s.state}`}>
              {s.id} {s.state.replace(/_/g, " ")}
            </span>
          ))}
        </p>
      )}
    </section>
  );
}
