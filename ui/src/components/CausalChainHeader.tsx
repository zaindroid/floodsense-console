import { useEffect, useState } from "react";
import { runBadge } from "../api/ask";
import { adoptRunBody, fetchRecordedRun, replayRunId, type RecordedRun } from "../api/replay";
import sampleRun from "../fixtures/run_f16733274f1c.json";
import { AgentPipeline } from "./AgentPipeline";
import { RetrievalPanel } from "./RetrievalPanel";
import { RunWalkthrough } from "./RunWalkthrough";

export const SAMPLE_RUN_ID = "f16733274f1c";

/** The bundled recorded run (f16733274f1c, one revise and one repair round). Always a replay. */
export function sampleRecordedRun(): RecordedRun | null {
  return adoptRunBody(sampleRun as unknown as Record<string, unknown>, SAMPLE_RUN_ID);
}

type Source = { kind: "bundled" } | { kind: "configured"; id: string } | { kind: "failed"; id: string } | { kind: "loading"; id: string };

/** Pure: the note under the header for where the run came from. Null for a configured run that loaded. */
export function causalChainNote(source: Source): string | null {
  switch (source.kind) {
    case "bundled":
      return `Bundled recording of run ${SAMPLE_RUN_ID}, shipped with the UI. Not this session's run, not live.`;
    case "failed":
      return `Could not load recorded run ${source.id} (VITE_REPLAY_RUN_ID). Showing the bundled recording of run ${SAMPLE_RUN_ID} instead. Not live.`;
    case "loading":
      return `Loading recorded run ${source.id}… showing the bundled recording of run ${SAMPLE_RUN_ID} until then.`;
    case "configured":
      return null;
  }
}

/** Insurer Review header: the agent graph of the reviewed run. VITE_REPLAY_RUN_ID, else the bundled recording, said so. */
export function CausalChainHeader() {
  const [run, setRun] = useState<RecordedRun | null>(() => sampleRecordedRun());
  const [walking, setWalking] = useState(false);
  const [source, setSource] = useState<Source>(() => {
    const id = replayRunId();
    return id ? { kind: "loading", id } : { kind: "bundled" };
  });
  useEffect(() => {
    const id = replayRunId();
    if (!id) return;
    const controller = new AbortController();
    void fetchRecordedRun(id, undefined, controller.signal).then((r) => {
      if (controller.signal.aborted) return;
      if (r) {
        setRun(r);
        setSource({ kind: "configured", id });
      } else setSource({ kind: "failed", id });
    });
    return () => controller.abort();
  }, []);
  if (!run) return null;
  const kind = run.servedFrom === "live" ? "live" : run.servedFrom === "cache" ? "cached" : "replay";
  const note = causalChainNote(source);
  const isSample = run.runId === SAMPLE_RUN_ID && source.kind !== "configured";
  return (
    <section className="card agp-card" aria-label="Causal chain">
      <div className="stp-card-head">
        <p className="section-label">Causal chain</p>
        <span className={`stp-run-label stp-run-${kind}`}>
          {run.servedFrom === "live" ? runBadge(run) : `Recorded run · not live · ${run.runId}`}
        </span>
      </div>
      {note && (
        <p className={`note agp-source-note${source.kind === "failed" ? " is-failed" : ""}`} role="note">
          {note}
        </p>
      )}
      {isSample && (
        <p className="note">
          Known agent output defect in this recording: claim C2 states discharge “reached 23.38 m3/s … from 23.38 m3/s” at
          the same instant. It is shown as recorded, not corrected.
        </p>
      )}
      <AgentPipeline run={run} collapsed={false} title="How the agents reached this answer" />
      <div className="wt-open">
        <button type="button" className="button primary" onClick={() => setWalking(true)}>
          Walk through this run
        </button>
        <p className="note">
          {run.trace.length} recorded steps in the order they happened: the hypotheses, the loops back, the Judge, the
          human gate.
        </p>
      </div>
      {walking && <RunWalkthrough run={run} onClose={() => setWalking(false)} />}
      <details className="disclosure">
        <summary>Document retrieval and Judge verdicts</summary>
        <RetrievalPanel run={run} />
      </details>
    </section>
  );
}
