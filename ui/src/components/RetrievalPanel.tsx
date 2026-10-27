import type { CSSProperties } from "react";
import type { RecordedRun } from "../api/replay";
import { buildRetrieval } from "../lib/retrieval";

/** Layer (c) retrieval: query → passages → Zetaris query id → Judge verdict per claim. Nothing when no layer (c). */
export function RetrievalPanel({ run }: { run: RecordedRun }) {
  const model = buildRetrieval(run);
  if (!model.groups.length) return null;
  return (
    <section className="rag" aria-label="Document retrieval">
      <header className="rag-head">
        <p className="agp-title">Document retrieval (layer c)</p>
        <p className="agp-meta">
          <span className="agp-badge agp-badge-rag">pgvector + Zetaris JDBC</span> {model.passageCount} passage
          {model.passageCount === 1 ? "" : "s"}
        </p>
      </header>
      {model.query && (
        <p className="rag-query">
          <span className="rag-k">Query</span> “{model.query}”
        </p>
      )}
      {model.groups.map((g) => (
        <div key={g.claimId} className={`rag-group${g.flagged ? " rag-flagged" : ""}`}>
          <p className="rag-claim">
            <span className="rag-k">{g.claimId}</span> {g.claimText}
          </p>
          <ol className="rag-passages">
            {g.passages.map((p, i) => (
              <li key={p.id} className="rag-passage" style={{ "--i": i } as CSSProperties}>
                <p className="rag-title">
                  {i + 1}. {p.title}
                  {p.page !== null && <span className="rag-page"> · p. {p.page}</span>}
                </p>
                <p className="rag-src">
                  {p.publisher ?? "Unknown publisher"}
                  {p.licence ? ` · ${p.licence}` : ""}
                </p>
                {p.quote ? <blockquote className="rag-quote">“{p.quote}”</blockquote> : <p className="rag-src">Map page, no text quote.</p>}
                {p.attribution && <p className="rag-attr">{p.attribution}</p>}
              </li>
            ))}
          </ol>
          <p className="rag-foot">
            {g.queryIds.length > 0 ? (
              <>
                Hydrated by Zetaris query <code>{g.queryIds.join(", ")}</code>
              </>
            ) : (
              "No Zetaris query id recorded for these passages."
            )}
          </p>
          <p className={`rag-verdict${g.flagged ? " rag-verdict-flag" : ""}`}>
            {g.flagged && <strong>Flagged by Judge · </strong>}
            {g.verdict ? (
              <>
                Judge: {g.verdict.grounding ?? "no grounding"}
                {g.verdict.score !== null ? ` · score ${g.verdict.score.toFixed(2)}` : ""}
                {g.verdict.rationale ? ` · ${g.verdict.rationale}` : ""}
                {g.verdict.modelId ? ` (${g.verdict.modelId})` : ""}
              </>
            ) : (
              "No per-claim Judge verdict in this run."
            )}
          </p>
        </div>
      ))}
    </section>
  );
}
