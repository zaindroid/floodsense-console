import type { ReactNode } from "react";
import { isSafeHttpUrl } from "../lib/urls";

/** Renders an anchor only for http(s). Anything else is plain text, with no href. */
export function SafeLink({ href, children }: { href: string; children: ReactNode }) {
  if (!isSafeHttpUrl(href)) return <span>{children}</span>;
  return (
    <a href={href} target="_blank" rel="noreferrer">
      {children}
    </a>
  );
}
