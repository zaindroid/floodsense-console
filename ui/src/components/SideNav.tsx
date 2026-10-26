import { DESK_NAV, routeHref } from "../lib/route";
import { useConsole } from "../context/ConsoleContext";

export function SideNav({ collapsed, onToggle }: { collapsed: boolean; onToggle: () => void }) {
  const { route, page } = useConsole();
  const desk = route === "citizen" ? "Citizen" : "Insurer";
  const items = DESK_NAV[route];

  return (
    <nav className="side-nav" aria-label={`${desk} pages`}>
      <button
        type="button"
        className="icon-button nav-toggle"
        aria-expanded={!collapsed}
        aria-controls="desk-pages"
        onClick={onToggle}
      >
        <span className="sr-only">{collapsed ? "Show pages" : "Hide pages"}</span>
        <NavIcon />
      </button>
      <div id="desk-pages" hidden={collapsed}>
        <p className="section-label">{desk}</p>
        <ul>
          {items.map((item) => {
            const href = routeHref(route, item.page);
            return (
              <li key={item.page}>
                <a href={href} aria-current={page === item.page ? "page" : undefined}>
                  {item.label}
                </a>
              </li>
            );
          })}
        </ul>
      </div>
    </nav>
  );
}

function NavIcon() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
      <path d="M4 7h16M4 12h16M4 17h16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}
