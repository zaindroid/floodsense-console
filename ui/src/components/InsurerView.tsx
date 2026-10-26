import { Alerts } from "./Alerts";
import { Approvals } from "./Approvals";
import { ServingLine } from "./Banners";
import { Drilldown } from "./Drilldown";
import { MapPanel } from "./MapPanel";
import { Portfolio } from "./Portfolio";
import { ReviewColumn } from "./ReviewColumn";
import type { InsurerPage } from "../lib/route";

/** One insurer page per hash. The old desk's parts, each on the page the IA gives it. */
export function InsurerView({ page }: { page: InsurerPage }) {
  switch (page) {
    case "approvals":
      return (
        <div className="page-stack">
          <ServingLine inline />
          <Approvals />
        </div>
      );
    case "portfolio":
      return <Portfolio />;
    case "sites":
      return (
        <div className="insurer-top">
          <MapPanel exposureDefault />
          <Drilldown />
        </div>
      );
    case "alerts":
      return <Alerts />;
    case "review":
      return (
        <div className="page-stack">
          <ServingLine inline />
          <ReviewColumn />
        </div>
      );
  }
}
