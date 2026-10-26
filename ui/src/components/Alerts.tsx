import { SIM_WINDOW_END, SIM_WINDOW_START, SIMULATED_ALERT_M3S } from "../config/scenario";
import { useConsole } from "../context/ConsoleContext";
import { formatDay } from "../lib/format";
import { rowsOnDate } from "../lib/series";

/** Simulation stepper (moved from the map card) and the simulated alerts it raises. */
export function Alerts() {
  const desk = useConsole();
  const steps = desk.dates.filter((date) => date >= SIM_WINDOW_START && date <= SIM_WINDOW_END);
  const alerts = desk.notices.filter((notice) => notice.tone === "sim");

  return (
    <div className="page-stack">
      <section className="card" aria-label="Alert simulation">
        <div className="card-head">
          <div>
            <p className="section-label">Simulation</p>
            <h2>
              Step {formatDay(SIM_WINDOW_START)}–{formatDay(SIM_WINDOW_END)}
            </h2>
          </div>
          <button type="button" className="button primary" onClick={desk.playSimulation} disabled={desk.dates.length < 2}>
            {desk.playing ? "Stop" : "Simulate alert"}
          </button>
        </div>
        <p className="note">
          A notice is added when discharge crosses {SIMULATED_ALERT_M3S} m³/s. Simulation only. Not an official warning.
          {desk.playing ? " Playing." : ""}
        </p>
        <ol className="steps">
          {steps.map((date) => {
            const over = rowsOnDate(desk.discharge.rows, date).filter(
              (row) => row.discharge_m3s >= SIMULATED_ALERT_M3S,
            ).length;
            return (
              <li key={date} aria-current={date === desk.date ? "step" : undefined} data-over={over > 0 ? "true" : "false"}>
                <strong>{formatDay(date)}</strong>
                <span>{over === 0 ? "No point over the line" : `${over} point${over === 1 ? "" : "s"} over the line`}</span>
              </li>
            );
          })}
        </ol>
        {steps.length === 0 && <p className="note">The loaded rows have no dates inside the simulation window.</p>}
      </section>
      <section className="card" aria-label="Simulated alerts">
        <p className="section-label">Alerts</p>
        <h2>{alerts.length === 0 ? "No simulated alerts yet" : `${alerts.length} simulated alert${alerts.length === 1 ? "" : "s"}`}</h2>
        {alerts.length === 0 ? (
          <p className="note">Press Simulate alert to step the window. Alerts also reach the bell.</p>
        ) : (
          <ul className="notice-list alert-list">
            {alerts.map((notice) => (
              <li key={notice.id} className="notice notice-sim">
                <p className="menu-title">{notice.title}</p>
                <p className="menu-body">{notice.body}</p>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
