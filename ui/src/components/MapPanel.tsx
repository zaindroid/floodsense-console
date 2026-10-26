import { useMemo, useState } from "react";
import { useConsole } from "../context/ConsoleContext";
import {
  BAND_ELEVATED_M3S,
  BAND_TYPICAL_M3S,
  COAST_LAT,
  COAST_LON,
  MAP_BOUNDS,
  MAP_CHANNEL_IDS,
  MOUTH_LAT,
  MOUTH_LON,
  SIM_WINDOW_END,
  SIM_WINDOW_START,
  SIMULATED_ALERT_M3S,
} from "../config/scenario";
import { formatDay, formatEur, formatM3s } from "../lib/format";
import { statusLabel } from "../lib/origin";
import {
  dischargeBand,
  exposureStats,
  insideMap,
  mapAspectRatio,
  markerText,
  project,
  rowsOnDate,
} from "../lib/series";
import type { ValenciaPoint } from "../types/views";

export function MapPanel({
  simulate,
  showBook,
  exposureDefault,
}: {
  simulate: boolean;
  showBook: boolean;
  exposureDefault: boolean;
}) {
  const desk = useConsole();
  const [showExposure, setShowExposure] = useState(exposureDefault);
  const rowsToday = rowsOnDate(desk.discharge.rows, desk.date);
  const byPoint = new Map(rowsToday.map((row) => [row.point_id, row]));
  const stats = useMemo(() => exposureStats(desk.exposure.rows), [desk.exposure.rows]);
  const peakCount = rowsToday.filter((row) => row.discharge_m3s >= SIMULATED_ALERT_M3S).length;
  const dateIndex = Math.max(0, desk.dates.indexOf(desk.date));
  const coastX = project(COAST_LAT, COAST_LON).x;
  const channel = MAP_CHANNEL_IDS
    .map((id) => desk.points.find((point) => point.point_id === id))
    .filter((point): point is ValenciaPoint => Boolean(point))
    .map((point) => project(point.lat, point.lon));
  const mouth = project(MOUTH_LAT, MOUTH_LON);
  const channelPoints = [...channel, mouth].map((point) => `${point.x},${point.y}`).join(" ");

  return (
    <section className="card map-card" aria-label="Valencia points">
      <div className="card-head">
        <div>
          <p className="section-label">Map</p>
          <h2>Points on {formatDay(desk.date)}</h2>
        </div>
        <label className="check">
          <input
            type="checkbox"
            checked={showExposure}
            onChange={(event) => setShowExposure(event.target.checked)}
          />
          Exposed sites
        </label>
      </div>
      <div className="toolbar">
        <label className="field">
          Point
          <select value={desk.pointId} onChange={(event) => desk.setPointId(event.target.value)}>
            {desk.points.map((point) => (
              <option key={point.point_id} value={point.point_id}>
                {point.point_id} · {point.name}
              </option>
            ))}
          </select>
        </label>
        {simulate && (
          <button type="button" className="button" onClick={desk.playSimulation} disabled={desk.dates.length < 2}>
            {desk.playing ? "Stop" : "Simulate alert"}
          </button>
        )}
      </div>
      {simulate && (
        <p className="note">
          Steps {formatDay(SIM_WINDOW_START)}–{formatDay(SIM_WINDOW_END)}. A notice is added when discharge crosses {SIMULATED_ALERT_M3S} m³/s.
          Simulation only. Not an official warning.
          {desk.playing ? " Playing." : ""}
        </p>
      )}
      <div className="map-stage" style={{ aspectRatio: mapAspectRatio() }}>
        <svg className="map-bg" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
          <rect width="100" height="100" fill="var(--land)" />
          <path
            d={`M ${coastX} 0 C ${coastX - 2.4} 18, ${coastX + 1.6} 36, ${coastX - 1} 54 C ${coastX + 1.8} 74, ${coastX - 1.4} 88, ${coastX} 100 L 100 100 L 100 0 Z`}
            fill="var(--sea)"
          />
          {channel.length > 1 && (
            <polyline points={channelPoints} fill="none" stroke="var(--accent)" strokeWidth="0.7" strokeDasharray="1.4 1.1" />
          )}
        </svg>
        {showExposure &&
          desk.exposure.rows
            .filter((row) => row.in_footprint)
            .map((row) => {
              const position = project(row.lat, row.lon);
              if (!insideMap(position)) return null;
              return (
                <span
                  key={row.policy_id}
                  className="exposure-dot"
                  style={{ left: `${position.x}%`, top: `${position.y}%` }}
                  title={`${row.policy_id} · ${row.segment}`}
                />
              );
            })}
        {desk.points.map((point) => {
          const position = project(point.lat, point.lon);
          if (!insideMap(position)) return null;
          const row = byPoint.get(point.point_id);
          const band = row ? dischargeBand(row.discharge_m3s) : "low";
          const selected = point.point_id === desk.pointId;
          const value = row ? `${formatM3s(row.discharge_m3s)} cubic metres per second` : "no discharge row";
          return (
            <button
              key={point.point_id}
              type="button"
              className="marker"
              data-band={band}
              aria-pressed={selected}
              style={{ left: `${position.x}%`, top: `${position.y}%` }}
              onClick={() => desk.setPointId(point.point_id)}
              aria-label={`${point.point_id} ${point.name}, ${value}`}
            >
              <span className="marker-id">{markerText(point.point_id)}</span>
              {selected && <span className="marker-name">{point.name}</span>}
            </button>
          );
        })}
        <span className="map-caption sea-caption">{statusLabel(desk.discharge.origin)} · schematic</span>
      </div>
      <div className="slider-block">
        <div className="slider-labels">
          <span>Replay date</span>
          <strong>{formatDay(desk.date)}</strong>
        </div>
        <input
          type="range"
          min={0}
          max={Math.max(desk.dates.length - 1, 0)}
          step={1}
          value={desk.dates.length === 0 ? 0 : dateIndex}
          aria-label="Replay date"
          aria-valuetext={formatDay(desk.date)}
          disabled={desk.dates.length === 0}
          onChange={(event) => {
            desk.stopSimulation();
            const next = desk.dates[Number(event.target.value)];
            if (next) desk.setDate(next);
          }}
        />
        <div className="slider-scale">
          <span>{desk.dates[0] ? formatDay(desk.dates[0]) : ""}</span>
          <span>{desk.dates.at(-1) ? formatDay(desk.dates.at(-1) ?? "") : ""}</span>
        </div>
      </div>
      <ul className="legend">
        <li><i data-band="low" /> under {BAND_TYPICAL_M3S} m³/s</li>
        <li><i data-band="typical" /> {BAND_TYPICAL_M3S}–{BAND_ELEVATED_M3S}</li>
        <li><i data-band="elevated" /> {BAND_ELEVATED_M3S}–{SIMULATED_ALERT_M3S}</li>
        <li><i data-band="peak" /> ≥ {SIMULATED_ALERT_M3S}</li>
        <li><i className="dot-sample" /> in_footprint</li>
      </ul>
      <p className="note">
        Marker colour is modelled discharge_m3s. The dashed line is a schematic inland-to-coast path, not a river layer.
        Bounds {MAP_BOUNDS.minLat}–{MAP_BOUNDS.maxLat} N, {MAP_BOUNDS.minLon}–{MAP_BOUNDS.maxLon} E.
        {peakCount > 0 ? ` ${peakCount} point${peakCount === 1 ? "" : "s"} in the peak band this day.` : ""}
      </p>
      {showBook && (
        <dl className="kpis">
          <div>
            <dt>Points</dt>
            <dd>{desk.points.length}</dd>
          </div>
          <div>
            <dt>Peak band</dt>
            <dd>{peakCount}</dd>
          </div>
          <div>
            <dt>in_footprint</dt>
            <dd>
              {stats.inFootprint} / {stats.policies}
            </dd>
          </div>
          <div>
            <dt>Sum insured</dt>
            <dd>{formatEur(stats.sumInsured)}</dd>
          </div>
        </dl>
      )}
    </section>
  );
}
