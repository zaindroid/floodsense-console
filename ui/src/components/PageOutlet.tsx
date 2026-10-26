import { CitizenView } from "./CitizenView";
import { InsurerView } from "./InsurerView";
import { DESK_NAV } from "../lib/route";
import { useConsole } from "../context/ConsoleContext";

/** Thin outlet. Both desks still render the current views until a later split. */
export function PageOutlet() {
  const { route, page } = useConsole();
  const desk = route === "citizen" ? "Citizen" : "Insurer";
  const label = DESK_NAV[route].find((item) => item.page === page)?.label ?? "Overview";

  return (
    <>
      <h1 className="sr-only">
        {desk} {label}
      </h1>
      <p className="section-label page-kicker">
        {desk} · {label}
      </p>
      {route === "citizen" ? <CitizenView /> : <InsurerView />}
    </>
  );
}
