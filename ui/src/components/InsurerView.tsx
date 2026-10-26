import { CacheBanner, Colophon, OriginBanner } from "./Banners";
import { Drilldown } from "./Drilldown";
import { EvidenceDrawer } from "./EvidenceDrawer";
import { MapPanel } from "./MapPanel";
import { ReviewColumn } from "./ReviewColumn";

export function InsurerView() {
  return (
    <div className="workspace insurer">
      <CacheBanner />
      <OriginBanner />
      <div className="insurer-top">
        <MapPanel simulate showBook exposureDefault />
        <Drilldown />
      </div>
      <ReviewColumn />
      <EvidenceDrawer />
      <Colophon />
    </div>
  );
}
