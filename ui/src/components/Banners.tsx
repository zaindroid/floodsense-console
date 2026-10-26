import { servingLabel, servingQualifier } from "../lib/format";
import { statusLabel } from "../lib/origin";
import { useConsole } from "../context/ConsoleContext";
import type { ProvenanceRow } from "../types/views";

export function CacheBanner() {
  const { answer } = useConsole();
  const serving = servingLabel(answer);
  return (
    <p className={`banner banner-${serving.kind}`} data-serving={serving.servedFrom} role="status">
      <strong>{serving.kind === "cached" ? `${serving.text} UTC` : serving.text}</strong>
      <span>
        {" "}
        · {servingQualifier(serving)} · run {serving.runId}
      </span>
    </p>
  );
}

export function OriginBanner() {
  const desk = useConsole();
  const parts = [
    ["discharge_daily", desk.discharge],
    ["hazard_timeline", desk.hazard],
    ["exposure_join", desk.exposure],
    ["provenance", desk.provenance],
  ] as const;
  return (
    <p className="banner banner-origin" data-origin={parts.map(([, slice]) => slice.origin).join(" ")}>
      {parts.map(([name, slice], index) => (
        <span key={name}>
          {index > 0 && " · "}
          <span className="origin-name">{name}</span> {statusLabel(slice.origin)}
        </span>
      ))}
      <span> · {desk.healthDetail}</span>
    </p>
  );
}

function pick(rows: ProvenanceRow[], test: (dataset: string) => boolean): ProvenanceRow | undefined {
  return rows.find((row) => test(row.dataset.toLowerCase()));
}

export function Colophon() {
  const { provenance } = useConsole();
  const rows = provenance.rows;
  const chosen = [
    pick(rows, (name) => name.includes("glofas") || name.includes("open-meteo flood")),
    pick(rows, (name) => name.includes("emsr773")),
    pick(rows, (name) => name.includes("osm")),
    pick(rows, (name) => name.includes("synthetic")),
  ].filter((row): row is ProvenanceRow => Boolean(row));
  return (
    <footer className="colophon">
      {chosen.map((row) => (
        <p key={row.dataset}>
          {row.attribution} ({row.licence})
        </p>
      ))}
      <p>Portfolio rows are synthetic. Modelled discharge is not an official warning.</p>
    </footer>
  );
}
