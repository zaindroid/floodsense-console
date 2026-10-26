import { useEffect, useId, useRef, useState } from "react";
import { useConsole } from "../context/ConsoleContext";
import { useDismiss } from "../hooks/useDismiss";
import { servingLabel } from "../lib/format";
import { honestyChip, originPill } from "../lib/origin";
import { OriginList, ServingLine } from "./Banners";
import { applyTheme, readTheme, type ThemeName } from "../lib/theme";
import { PROVIDER_LABELS, showProviderSelect, type LlmProvider } from "../lib/llmProvider";

export function Header() {
  const desk = useConsole();
  const [theme, setTheme] = useState<ThemeName>(readTheme);
  const [bellOpen, setBellOpen] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const [chipOpen, setChipOpen] = useState(false);
  const chipRef = useRef<HTMLDivElement>(null);
  const chipTitle = useId();
  const chipMenu = useId();
  const bellRef = useRef<HTMLDivElement>(null);
  const profileRef = useRef<HTMLDivElement>(null);
  const bellTitle = useId();
  const profileTitle = useId();
  const unread = desk.notices.filter((notice) => !notice.read).length;
  const markNotificationsRead = desk.markNotificationsRead;
  const origins = [desk.discharge.origin, desk.hazard.origin, desk.exposure.origin, desk.provenance.origin];
  const rows = originPill(origins);
  const chip = honestyChip(origins, servingLabel(desk.answer).kind);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  useEffect(() => {
    if (bellOpen) markNotificationsRead();
  }, [bellOpen, markNotificationsRead]);

  const closeBell = () => setBellOpen(false);
  const closeProfile = () => setProfileOpen(false);
  const closeChip = () => setChipOpen(false);
  useDismiss(chipOpen, closeChip, chipRef);
  useDismiss(bellOpen, closeBell, bellRef);
  useDismiss(profileOpen, closeProfile, profileRef);

  return (
    <header className="header">
      <a className="skip" href="#content">
        Skip to content
      </a>
      <div className="header-inner">
        <div className="brand">
          <span className="mark" aria-hidden="true">
            <svg viewBox="0 0 32 32" width="28" height="28">
              <rect width="32" height="32" rx="8" fill="currentColor" opacity="0.16" />
              <path d="M5 20c3-4 5-4 8 0s5 4 8 0 5-4 6 0" fill="none" stroke="currentColor" strokeWidth="2" />
              <path d="M5 14c3-3 5-3 8 0s5 3 8 0 5-3 6 0" fill="none" stroke="currentColor" strokeWidth="2" />
            </svg>
          </span>
          <div>
            <p className="product">FloodSense EU</p>
            <p className="product-sub">Valencia replay · EMSR773</p>
          </div>
        </div>
        <nav className="nav-links" aria-label="Workspace">
          <a href="#/citizen" aria-current={desk.route === "citizen" ? "page" : undefined}>
            Citizen
          </a>
          <a href="#/insurer" aria-current={desk.route === "insurer" ? "page" : undefined}>
            Insurer
          </a>
        </nav>
        <div className="header-tools">
          {showProviderSelect(desk.llmProviders) && (
            <label className="llm-select" title="Local benchmarking only. The demo runs Nightshift.">
              <span>LLM:</span>{" "}
              <select
                value={desk.llmProvider}
                aria-label="LLM provider (test only)"
                onChange={(event) => desk.setLlmProvider(event.target.value as LlmProvider)}
              >
                {desk.llmProviders.map((p) => (
                  <option key={p} value={p}>
                    {PROVIDER_LABELS[p]}
                  </option>
                ))}
              </select>
            </label>
          )}
          <div className="menu-anchor chip-anchor" ref={chipRef}>
            <button
              type="button"
              className={`pill pill-${chip.state}`}
              data-state={chip.state}
              aria-expanded={chipOpen}
              aria-controls={chipOpen ? chipMenu : undefined}
              aria-label={`Data status: ${chip.label}. Rows ${rows.label}.`}
              onClick={() => {
                setBellOpen(false);
                setProfileOpen(false);
                setChipOpen((open) => !open);
              }}
            >
              {chip.label}
            </button>
            {chipOpen && (
              <div className="menu menu-wide" id={chipMenu} role="region" aria-labelledby={chipTitle}>
                <p className="menu-kicker" id={chipTitle}>
                  {chip.label}
                </p>
                <p className="menu-body">
                  {chip.state === "preview"
                    ? `Rows on screen are ${rows.label.toLowerCase()}, not live views.`
                    : chip.state === "cached"
                      ? "Every view is live. The answer is cached or replayed."
                      : "Every view is live and the answer is live."}
                </p>
                <p className="menu-title">Answer</p>
                <ServingLine />
                <p className="menu-title">Views</p>
                <OriginList />
              </div>
            )}
          </div>
          <button
            type="button"
            className="icon-button"
            aria-pressed={theme === "dark"}
            aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
            onClick={() => {
              const next = theme === "dark" ? "light" : "dark";
              setTheme(next);
              applyTheme(next);
            }}
          >
            {theme === "dark" ? <SunIcon /> : <MoonIcon />}
          </button>
          <div className="menu-anchor" ref={bellRef}>
            <button
              type="button"
              className="icon-button"
              aria-expanded={bellOpen}
              aria-label={unread > 0 ? `Notifications, ${unread} unread` : "Notifications"}
              onClick={() => {
                setProfileOpen(false);
                setChipOpen(false);
                setBellOpen((open) => !open);
              }}
            >
              <BellIcon />
              {unread > 0 && <span className="count">{unread}</span>}
            </button>
            {bellOpen && (
              <div className="menu" role="dialog" aria-labelledby={bellTitle}>
                <p className="menu-kicker" id={bellTitle}>
                  Notices
                </p>
                {desk.notices.length === 0 ? (
                  <p className="menu-body">No notices.</p>
                ) : (
                  <ul className="notice-list">
                    {desk.notices.map((notice) => (
                      <li key={notice.id} className={notice.tone === "sim" ? "notice notice-sim" : "notice"}>
                        <p className="menu-title">{notice.title}</p>
                        <p className="menu-body">{notice.body}</p>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </div>
          <div className="menu-anchor" ref={profileRef}>
            <button
              type="button"
              className="icon-button"
              aria-expanded={profileOpen}
              aria-label="Account preview"
              onClick={() => {
                setBellOpen(false);
                setChipOpen(false);
                setProfileOpen((open) => !open);
              }}
            >
              <PersonIcon />
            </button>
            {profileOpen && (
              <div className="menu" role="dialog" aria-labelledby={profileTitle}>
                <p className="menu-kicker" id={profileTitle}>
                  Account
                </p>
                <p className="menu-title">Preview session</p>
                <p className="menu-body">Sign-in is not wired on this build. No credentials are collected.</p>
                <button type="button" className="button" disabled>
                  Sign in
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    </header>
  );
}

function SunIcon() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
      <circle cx="12" cy="12" r="3.5" fill="none" stroke="currentColor" strokeWidth="1.8" />
      <path d="M12 3v2.2M12 18.8V21M3 12h2.2M18.8 12H21M5.6 5.6l1.6 1.6M16.8 16.8l1.6 1.6M18.4 5.6l-1.6 1.6M7.2 16.8l-1.6 1.6" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}

function MoonIcon() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
      <path d="M15 3.5a8 8 0 1 0 5.5 13.5A7 7 0 0 1 15 3.5z" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
    </svg>
  );
}

function BellIcon() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
      <path d="M6 16h12l-1.2-2.2V10a4.8 4.8 0 0 0-9.6 0v3.8L6 16z" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
      <path d="M10 16a2 2 0 0 0 4 0" fill="none" stroke="currentColor" strokeWidth="1.8" />
    </svg>
  );
}

function PersonIcon() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
      <circle cx="12" cy="9" r="3" fill="none" stroke="currentColor" strokeWidth="1.8" />
      <path d="M5.5 19c1.4-2.4 3.6-3.5 6.5-3.5s5.1 1.1 6.5 3.5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}
