import { ServingLine } from "./Banners";
import { useConsole } from "../context/ConsoleContext";
import { replayBarView } from "../lib/events";
import { replayEventOfPlace } from "../lib/places";

/**
 * Context strip under the header. "Live data" on Now, a plain "Viewing: ... (replay of a past event)"
 * on pages that show a replayed event, nothing elsewhere. While the simulation plays, Stop stays
 * reachable on every page. On Approvals and Review the answer serving line rides in the same strip.
 */
export function ReplayBar() {
  const { date, playing, stopSimulation, route, page, deskRoute, eventId, ahrDate, placeId } = useConsole();
  const showServing = route === "insurer" && (page === "approvals" || page === "review");
  const view = replayBarView(deskRoute, eventId, { date }, { date: ahrDate }, replayEventOfPlace(placeId));
  if (view.kind === "none" && !playing && !showServing) return null;

  return (
    <div className="replay-bar" data-kind={view.kind}>
      {view.kind !== "none" && <span className="context-text">{view.text}</span>}
      {playing && (
        <>
          <span className="replay-state" data-playing="true">
            Simulation playing
          </span>
          <button type="button" className="button replay-stop" onClick={stopSimulation}>
            Stop
          </button>
        </>
      )}
      {showServing && <ServingLine inline />}
    </div>
  );
}
