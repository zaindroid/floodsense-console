import { useConsole } from "../context/ConsoleContext";
import { formatDay, formatHour, formatM3s, formatMm } from "../lib/format";
import { statusLabel } from "../lib/origin";
import {
  glofasDischargeNote,
  hazardOnDate,
  peakRow,
  pointById,
  provenanceForSource,
  rainSummary,
  rowAt,
  seriesFor,
} from "../lib/series";
import { Colophon, OriginBanner } from "./Banners";
import { MapPanel } from "./MapPanel";
import { Sparkline } from "./Sparkline";

export function CitizenView() {
  const desk = useConsole();
  const point = pointById(desk.points, desk.pointId);
  const series = seriesFor(desk.discharge.rows, desk.pointId);
  const row = rowAt(desk.discharge.rows, desk.pointId, desk.date);
  const activeIndex = series.findIndex((item) => item.date === desk.date);
  const peak = peakRow(series);
  const rain = rainSummary(hazardOnDate(desk.hazard.rows, desk.pointId, desk.date));
  const provenance = row ? provenanceForSource(row.source, desk.provenance.rows) : undefined;
  const origin = statusLabel(desk.discharge.origin);
  const modelled = row ? glofasDischargeNote(row.source) : null;

  return (
    <div className="workspace">
      <OriginBanner />
      <div className="citizen-grid">
        <MapPanel simulate={false} showBook={false} exposureDefault={false} />
        <section className="card" aria-label="Plain-language discharge">
          <p className="section-label">Citizen</p>
          <h2>{point ? point.name : desk.pointId}</h2>
          <p className="figure-caption">{origin}</p>
          <p className="figure">{row ? formatM3s(row.discharge_m3s) : "—"}</p>
          <p className="figure-unit">m³/s discharge</p>
          <Sparkline
            values={series.map((item) => item.discharge_m3s)}
            activeIndex={activeIndex}
            label={`Discharge series for ${desk.pointId}`}
          />
          <p>
            {row && point
              ? `On ${formatDay(desk.date)}, ${point.name} shows ${formatM3s(row.discharge_m3s)} m³/s in the loaded discharge series. The source column is ${row.source}. ${modelled ? `${modelled} ` : ""}Not an official warning.`
              : `No discharge row for ${desk.pointId} on ${formatDay(desk.date)}.`}
            {peak && row && peak.date === row.date ? " This is the highest day in the loaded series for this point." : ""}
          </p>
          {rain.peak && (
            <p className="note">
              Hourly rain on this date sums to {formatMm(rain.sum)} mm, with a max hour of {formatMm(rain.peak.rain_mm)} mm
              at {formatHour(rain.peak.ts_utc)}. warning_level is{" "}
              {rain.peak.warning_level === null ? "null" : rain.peak.warning_level}.
            </p>
          )}
          {provenance && (
            <p className="note">
              {provenance.attribution}. {provenance.licence}.
            </p>
          )}
          <p>
            <a href="#/insurer">Open the insurer desk</a> for the cited chain, Skeptic notes, and approval.
          </p>
        </section>
      </div>
      <Colophon />
    </div>
  );
}
