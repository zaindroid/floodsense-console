import { ConsoleProvider } from "./context/ConsoleContext";
import { AskFloodSense } from "./components/AskFloodSense";
import { EvidenceDrawer } from "./components/EvidenceDrawer";
import { Header } from "./components/Header";
import { PageOutlet } from "./components/PageOutlet";
import { ReplayBar } from "./components/ReplayBar";
import { SideNav } from "./components/SideNav";
import { useCollapsedNav } from "./hooks/useCollapsedNav";

export function App() {
  return (
    <ConsoleProvider>
      <Shell />
    </ConsoleProvider>
  );
}

function Shell() {
  const nav = useCollapsedNav();
  return (
    <div className="app-shell" data-nav={nav.collapsed ? "collapsed" : "open"}>
      <div className="shell-stage">
        <Header />
        <SideNav collapsed={nav.collapsed} onToggle={nav.toggle} />
        <ReplayBar />
        <main id="content">
          <PageOutlet />
        </main>
      </div>
      <AskFloodSense />
      <EvidenceDrawer />
    </div>
  );
}
