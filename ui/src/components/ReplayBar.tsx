import { useConsole } from "../context/ConsoleContext";
import { formatDay } from "../lib/format";
import { pointById } from "../lib/series";

/** Read-only strip. Playback still lives on the map controls. */
export function ReplayBar() {
  const { date, pointId, playing, points } = useConsole();
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
    </p>
  );
}
