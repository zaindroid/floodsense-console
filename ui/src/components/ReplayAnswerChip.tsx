import { useId, useRef, useState } from "react";
import { useConsole } from "../context/ConsoleContext";
import { useDismiss } from "../hooks/useDismiss";
import { servingLabel, servingQualifier } from "../lib/format";

/** Collapsed chip. The answer is the fixture already on the desk. This does not call a model. */
export function ReplayAnswerChip() {
  const { answer } = useConsole();
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const titleId = useId();
  const dockRef = useRef<HTMLDivElement>(null);
  const close = () => setOpen(false);
  useDismiss(open, close, dockRef);
  const serving = servingLabel(answer);
  const when = serving.kind === "cached" ? `${serving.text} UTC` : serving.text;

  return (
    <div className="replay-dock" ref={dockRef}>
      {open && (
        <div className="replay-dock-card" id={panelId} role="region" aria-labelledby={titleId}>
          <p className="section-label" id={titleId}>
            Replay answer
          </p>
          <p className="replay-question">{answer.question}</p>
          <p className="note">
            {when} · {servingQualifier(serving)}
          </p>
          <p className="note">Fixture. This screen does not call a model.</p>
        </div>
      )}
      <button
        type="button"
        className="replay-chip"
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
        onClick={() => setOpen((current) => !current)}
      >
        Replay answer
      </button>
    </div>
  );
}
