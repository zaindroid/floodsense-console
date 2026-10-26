import { useEffect, useState } from "react";
import { NAV_COLLAPSE_QUERY } from "../lib/route";

function windowIsNarrow(): boolean {
  return window.matchMedia(NAV_COLLAPSE_QUERY).matches;
}

/** Collapsed by default under 980px. A manual toggle holds until the breakpoint changes. */
export function useCollapsedNav(): { collapsed: boolean; toggle: () => void } {
  const [collapsed, setCollapsed] = useState(windowIsNarrow);

  useEffect(() => {
    const media = window.matchMedia(NAV_COLLAPSE_QUERY);
    const onChange = () => setCollapsed(media.matches);
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, []);

  return {
    collapsed,
    toggle: () => setCollapsed((current) => !current),
  };
}
