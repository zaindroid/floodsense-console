import type { RouteId } from "../types/ui";

/** Desk in the hash. Same two roles the header already switches. */
export type RoleId = RouteId;

export const CITIZEN_PAGES = ["overview", "place", "rain"] as const;
export const INSURER_PAGES = ["overview", "map", "point", "book", "review", "sources"] as const;

export type CitizenPage = (typeof CITIZEN_PAGES)[number];
export type InsurerPage = (typeof INSURER_PAGES)[number];
export type PageId = CitizenPage | InsurerPage;

export type DeskRoute = { role: "citizen"; page: CitizenPage } | { role: "insurer"; page: InsurerPage };

export const DESK_NAV: {
  citizen: readonly { page: CitizenPage; label: string }[];
  insurer: readonly { page: InsurerPage; label: string }[];
} = {
  citizen: [
    { page: "overview", label: "Overview" },
    { page: "place", label: "Place" },
    { page: "rain", label: "Rain" },
  ],
  insurer: [
    { page: "overview", label: "Overview" },
    { page: "map", label: "Map" },
    { page: "point", label: "Point" },
    { page: "book", label: "Book" },
    { page: "review", label: "Review" },
    { page: "sources", label: "Sources" },
  ],
};

export const DEFAULT_ROUTE: DeskRoute = { role: "insurer", page: "overview" };

/** Collapse the left nav at the same width the layout already stacks. */
export const NAV_COLLAPSE_QUERY = "(max-width: 980px)";

function hashBody(hash: string): string {
  const trimmed = hash.trim();
  const withoutMark = trimmed.startsWith("#") ? trimmed.slice(1) : trimmed;
  return withoutMark.replace(/^\/+/, "").replace(/\/+$/, "");
}

function citizenPage(token: string | undefined): CitizenPage | null {
  return CITIZEN_PAGES.find((page) => page === token) ?? null;
}

function insurerPage(token: string | undefined): InsurerPage | null {
  return INSURER_PAGES.find((page) => page === token) ?? null;
}

/**
 * `#/role/page`. An empty hash is the insurer overview.
 * One segment is that desk's overview. An unknown page, or extra segments, is that desk's overview.
 * An unknown role is the insurer overview.
 */
export function parseHash(hash: string): DeskRoute {
  const body = hashBody(hash);
  if (!body) return DEFAULT_ROUTE;
  const parts = body.split("/");
  const role = parts[0];
  if (role !== "citizen" && role !== "insurer") return DEFAULT_ROUTE;
  if (parts.length === 1) return { role, page: "overview" };
  if (parts.length !== 2) return { role, page: "overview" };
  if (role === "citizen") {
    return { role, page: citizenPage(parts[1]) ?? "overview" };
  }
  return { role, page: insurerPage(parts[1]) ?? "overview" };
}

/** Overview keeps the short hash (`#/insurer`). Other pages use `#/role/page`. */
export function routeHref(role: RoleId, page: PageId): string {
  if (page === "overview") return `#/${role}`;
  return `#/${role}/${page}`;
}
