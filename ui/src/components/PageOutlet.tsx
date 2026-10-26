import { Colophon } from "./Banners";
import { CitizenActions, CitizenArea, CitizenEvidence, CitizenOverview } from "./CitizenView";
import { InsurerView } from "./InsurerView";
import { pageLabel, type CitizenPage } from "../lib/route";
import { useConsole } from "../context/ConsoleContext";

/** One page body per hash. The Evidence drawer and the replay strip stay on the shell. */
export function PageOutlet() {
  const { deskRoute } = useConsole();
  const desk = deskRoute.role === "citizen" ? "Citizen" : "Insurer";
  const label = pageLabel(deskRoute);

  return (
    <>
      <h1 className="sr-only">
        {desk} {label}
      </h1>
      <p className="section-label page-kicker">
        {desk} · {label}
      </p>
      <div className="workspace" data-page={`${deskRoute.role}-${deskRoute.page}`}>
        {deskRoute.role === "citizen" ? <CitizenBody page={deskRoute.page} /> : <InsurerView page={deskRoute.page} />}
        <Colophon />
      </div>
    </>
  );
}

function CitizenBody({ page }: { page: CitizenPage }) {
  switch (page) {
    case "overview":
      return <CitizenOverview />;
    case "area":
      return <CitizenArea />;
    case "actions":
      return <CitizenActions />;
    case "evidence":
      return <CitizenEvidence />;
  }
}
