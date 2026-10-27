import { ServingLine } from "./Banners";
import { useConsole } from "../context/ConsoleContext";
import { formatDay } from "../lib/format";
import { pointById } from "../lib/series";

/**
 * Shared date, point, and playback state. Simulate starts on Alerts; Stop is here on every page.
 * On Approvals and Review the answer serving line rides in the same strip, so there is one banner.
 */
export function ReplayBar() {
  const { date, pointId, playing, points, stopSimulation, route, page } = useConsole();
  const showServing = route === "insurer" && (page === "approvals" || page === "review");
  const point = pointById(points, pointId);
  const place = point ? `${point.point_id} ${point.name}` : pointId;

  return (
    <div className="replay-bar">
      <span className="section-label">Replay</span>
      <strong>{formatDay(date)}</strong>
      <span>{place}</span>
      <span className="replay-state" data-playing={playing ? "true" : "false"}>
        {playing ? "Playing" : "Paused"}
      </span>
      {playing && (
        <button type="button" className="button replay-stop" onClick={stopSimulation}>
          Stop
        </button>
      )}
      {showServing && <ServingLine inline />}
    </div>
  );
}
