import { useConsole } from "../context/ConsoleContext";
import { formatDay } from "../lib/format";
import { pointById } from "../lib/series";

/** Shared date, point, and playback state. Simulate starts on Alerts; Stop is here on every page. */
export function ReplayBar() {
  const { date, pointId, playing, points, stopSimulation } = useConsole();
  const point = pointById(points, pointId);
  const place = point ? `${point.point_id} ${point.name}` : pointId;

  return (
    <p className="replay-bar">
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
    </p>
  );
}
