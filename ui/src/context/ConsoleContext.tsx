import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { adoptView, markBatchSeed } from "../api/adopt";
import { loadLiveViews } from "../api/client";
import {
  DEFAULT_DATE,
  DEFAULT_POINT_ID,
  FIXTURE_DETAILS,
  SIM_PLAY_INTERVAL_MS,
  SIM_WINDOW_END,
  SIM_WINDOW_START,
  SIMULATED_ALERT_M3S,
} from "../config/scenario";
import { loadFixtures, type FixtureBundle } from "../fixtures/load";
import { datesOf, isModelledGlofasSource, pointById, pointsCrossing, rowAt } from "../lib/series";
import { formatDay } from "../lib/format";
import { fixtureDischargeNotice, replayNotice, seedRowsNotice } from "../lib/notices";
import { parseHash, routeHref, type DeskRoute, type PageId } from "../lib/route";
import type { Answer, Approval, ApprovalStatus } from "../types/contract";
import type { EvidenceTopic, Notice, RouteId } from "../types/ui";
import type {
  DataOrigin,
  DischargeDailyRow,
  ExposureJoinRow,
  HazardTimelineRow,
  ProvenanceRow,
  ValenciaPoint,
} from "../types/views";

interface ViewSlice<T> {
  rows: T;
  origin: DataOrigin;
  detail: string;
}

export interface ConsoleValue {
  route: RouteId;
  page: PageId;
  /** Same as route and page, as one union so a page switch can narrow it. */
  deskRoute: DeskRoute;
  healthOk: boolean;
  healthDetail: string;
  discharge: ViewSlice<DischargeDailyRow[]>;
  hazard: ViewSlice<HazardTimelineRow[]>;
  exposure: ViewSlice<ExposureJoinRow[]>;
  provenance: ViewSlice<ProvenanceRow[]>;
  points: ValenciaPoint[];
  answer: Answer;
  dates: string[];
  date: string;
  setDate: (date: string) => void;
  pointId: string;
  setPointId: (pointId: string) => void;
  evidenceOpen: boolean;
  evidenceTopic: EvidenceTopic;
  openEvidence: (topic: EvidenceTopic) => void;
  closeEvidence: () => void;
  /** Ask FloodSense popup. Closed at start. A route change never opens it. */
  askOpen: boolean;
  openAsk: () => void;
  closeAsk: () => void;
  approval: Approval;
  decide: (status: ApprovalStatus, note: string) => void;
  resetApproval: () => void;
  notices: Notice[];
  markNotificationsRead: () => void;
  playing: boolean;
  playSimulation: () => void;
  stopSimulation: () => void;
}

const ConsoleContext = createContext<ConsoleValue | null>(null);

/** Reads the hash and rewrites it to the canonical href, so `#/insurer` and #36 hashes settle on one page. */
function readRoute(approvalPending: boolean): DeskRoute {
  const route = parseHash(window.location.hash, approvalPending);
  const href = routeHref(route.role, route.page);
  if (window.location.hash !== href) window.history.replaceState(null, "", href);
  return route;
}

function initialApproval(answer: Answer): Approval {
  const action = answer.playbook_actions?.[0];
  return {
    approval_id: "apr_fixture_valencia",
    run_id: answer.run_id,
    action_id: action?.action_id ?? "act_fixture_review_footprint",
    status: "pending",
    judge: answer.judge,
  };
}

function slice<T>(rows: T, detail: string): ViewSlice<T> {
  return { rows, origin: "fixture", detail };
}

export function ConsoleProvider({ children }: { children: ReactNode }) {
  const bundle = useMemo<FixtureBundle | { error: string }>(() => {
    try {
      return loadFixtures();
    } catch (error) {
      return { error: error instanceof Error ? error.message : "Fixtures failed to load." };
    }
  }, []);

  if ("error" in bundle) {
    return (
      <p className="boot-error" role="alert">
        {bundle.error}
      </p>
    );
  }

  return <ReadyConsole bundle={bundle}>{children}</ReadyConsole>;
}

function ReadyConsole({ bundle, children }: { bundle: FixtureBundle; children: ReactNode }) {
  const [deskRoute, setDeskRoute] = useState<DeskRoute>(() => parseHash(window.location.hash));
  const [healthOk, setHealthOk] = useState(false);
  const [healthDetail, setHealthDetail] = useState("Checking API health. Rows on screen are fixtures until a view route answers.");
  const [discharge, setDischarge] = useState<ViewSlice<DischargeDailyRow[]>>(
    slice(bundle.discharge, FIXTURE_DETAILS.discharge_daily),
  );
  const [hazard, setHazard] = useState<ViewSlice<HazardTimelineRow[]>>(
    slice(bundle.hazard, FIXTURE_DETAILS.hazard_timeline),
  );
  const [exposure, setExposure] = useState<ViewSlice<ExposureJoinRow[]>>(
    slice(bundle.exposure, FIXTURE_DETAILS.exposure_join),
  );
  const [provenance, setProvenance] = useState<ViewSlice<ProvenanceRow[]>>(
    slice(bundle.provenance, FIXTURE_DETAILS.provenance),
  );
  const dates = useMemo(() => datesOf(discharge.rows), [discharge.rows]);
  const [date, setDateState] = useState(DEFAULT_DATE);
  const [pointId, setPointId] = useState(DEFAULT_POINT_ID);
  const [evidenceOpen, setEvidenceOpen] = useState(false);
  const [evidenceTopic, setEvidenceTopic] = useState<EvidenceTopic>("discharge");
  const [askOpen, setAskOpen] = useState(false);
  const [approval, setApproval] = useState<Approval>(() => initialApproval(bundle.answer));
  const approvalPendingRef = useRef(true);
  approvalPendingRef.current = approval.status === "pending";
  const [notices, setNotices] = useState<Notice[]>(() => [
    replayNotice(bundle.answer),
    fixtureDischargeNotice(bundle.discharge),
  ]);
  const [playing, setPlaying] = useState(false);
  const playingRef = useRef(false);
  playingRef.current = playing;
  const playUntilRef = useRef(SIM_WINDOW_END);
  const raisedFor = useRef(new Set<string>());
  const previousDate = useRef(date);

  const setDate = useCallback((next: string) => {
    setDateState(next);
  }, []);

  useEffect(() => {
    const onHash = () => setDeskRoute(readRoute(approvalPendingRef.current));
    onHash();
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  useEffect(() => {
    setEvidenceOpen(false);
  }, [deskRoute]);

  useEffect(() => {
    if (dates.length > 0 && !dates.includes(date)) setDateState(dates[0]);
  }, [dates, date]);

  useEffect(() => {
    let cancelled = false;
    loadLiveViews().then((live) => {
      if (cancelled) return;
      setHealthOk(live.health.ok);
      setHealthDetail(live.health.detail);
      const take = <T,>(parsed: T[] | null, miss: string, fixtureRows: T[], fixtureDetail: string) =>
        adoptView({
          healthOk: live.health.ok,
          parsed,
          fixtureRows,
          fixtureDetail,
          missDetail: miss,
        });
      const dischargeSlice = take(
        live.discharge_daily,
        live.details.discharge_daily,
        bundle.discharge,
        FIXTURE_DETAILS.discharge_daily,
      );
      setDischarge(dischargeSlice);
      setHazard(
        markBatchSeed(
          dischargeSlice,
          take(live.hazard_timeline, live.details.hazard_timeline, bundle.hazard, FIXTURE_DETAILS.hazard_timeline),
        ),
      );
      setExposure(
        markBatchSeed(
          dischargeSlice,
          take(live.exposure_join, live.details.exposure_join, bundle.exposure, FIXTURE_DETAILS.exposure_join),
        ),
      );
      setProvenance(
        markBatchSeed(
          dischargeSlice,
          take(live.provenance, live.details.provenance, bundle.provenance, FIXTURE_DETAILS.provenance),
        ),
      );
    });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    setNotices((list) => {
      const rest = list.filter((notice) => notice.id !== "seed-loaded" && notice.id !== "fixture-loaded");
      if (discharge.origin === "live") return rest;
      const notice =
        discharge.origin === "seed" ? seedRowsNotice(discharge.rows) : fixtureDischargeNotice(discharge.rows);
      const current = list.find((item) => item.id === notice.id);
      if (current && current.title === notice.title && current.body === notice.body) return list;
      return [notice, ...rest];
    });
  }, [discharge.origin, discharge.rows]);

  useEffect(() => {
    if (!playing) return;
    const id = window.setInterval(() => {
      setDateState((current) => {
        if (current >= playUntilRef.current) return current;
        const index = dates.indexOf(current);
        return dates[index + 1] ?? current;
      });
    }, SIM_PLAY_INTERVAL_MS);
    return () => window.clearInterval(id);
  }, [playing, dates]);

  useEffect(() => {
    const before = previousDate.current;
    previousDate.current = date;
    if (!playingRef.current) return;
    if (before < date) {
      const ids = pointsCrossing(discharge.rows, before, date, SIMULATED_ALERT_M3S);
      const key = `${date}:${ids.join(",")}`;
      if (ids.length > 0 && !raisedFor.current.has(key)) {
        raisedFor.current.add(key);
        const names = ids.map((id) => {
          const point = pointById(bundle.points, id);
          return point ? `${id} ${point.name}` : id;
        });
        const sources = ids.map((id) => rowAt(discharge.rows, id, date)?.source ?? "");
        const modelled = sources.length > 0 && sources.every((source) => isModelledGlofasSource(source));
        const what = modelled ? "Modelled GloFAS discharge" : "Discharge";
        setNotices((list) => [
          {
            id: `sim-${key}`,
            tone: "sim",
            read: false,
            title: "Simulated alert",
            body: `${what} crossed ${SIMULATED_ALERT_M3S} m³/s on ${formatDay(date)} at ${names.join(", ")}. Simulation only. Not an official warning.`,
          },
          ...list,
        ]);
      }
    }
    if (date >= playUntilRef.current) setPlaying(false);
  }, [date, discharge.rows, bundle.points]);

  const openEvidence = useCallback((topic: EvidenceTopic) => {
    setEvidenceTopic(topic);
    setEvidenceOpen(true);
  }, []);

  const closeEvidence = useCallback(() => setEvidenceOpen(false), []);

  const openAsk = useCallback(() => setAskOpen(true), []);

  const closeAsk = useCallback(() => setAskOpen(false), []);

  const decide = useCallback((status: ApprovalStatus, note: string) => {
    setApproval((current) => ({ ...current, status, note }));
  }, []);

  const resetApproval = useCallback(() => {
    setApproval(initialApproval(bundle.answer));
  }, [bundle.answer]);

  const markNotificationsRead = useCallback(() => {
    setNotices((list) => (list.some((notice) => !notice.read) ? list.map((notice) => ({ ...notice, read: true })) : list));
  }, []);

  const stopSimulation = useCallback(() => setPlaying(false), []);

  const playSimulation = useCallback(() => {
    if (playingRef.current) {
      setPlaying(false);
      return;
    }
    if (dates.length < 2) return;
    setNotices((list) => list.filter((notice) => notice.tone !== "sim"));
    raisedFor.current.clear();
    const end = dates.includes(SIM_WINDOW_END) ? SIM_WINDOW_END : dates[dates.length - 1];
    playUntilRef.current = end;
    const start = dates.find((item) => item >= SIM_WINDOW_START && item < end) ?? dates[0];
    setDateState(start);
    setPlaying(true);
  }, [dates]);

  const value = useMemo<ConsoleValue>(
    () => ({
      route: deskRoute.role,
      page: deskRoute.page,
      deskRoute,
      healthOk,
      healthDetail,
      discharge,
      hazard,
      exposure,
      provenance,
      points: bundle.points,
      answer: bundle.answer,
      dates,
      date,
      setDate,
      pointId,
      setPointId,
      evidenceOpen,
      evidenceTopic,
      openEvidence,
      closeEvidence,
      askOpen,
      openAsk,
      closeAsk,
      approval,
      decide,
      resetApproval,
      notices,
      markNotificationsRead,
      playing,
      playSimulation,
      stopSimulation,
    }),
    [
      deskRoute,
      healthOk,
      healthDetail,
      discharge,
      hazard,
      exposure,
      provenance,
      bundle.points,
      bundle.answer,
      dates,
      date,
      setDate,
      pointId,
      evidenceOpen,
      evidenceTopic,
      openEvidence,
      closeEvidence,
      askOpen,
      openAsk,
      closeAsk,
      approval,
      decide,
      resetApproval,
      notices,
      markNotificationsRead,
      playing,
      playSimulation,
      stopSimulation,
    ],
  );

  return <ConsoleContext.Provider value={value}>{children}</ConsoleContext.Provider>;
}

export function useConsole(): ConsoleValue {
  const value = useContext(ConsoleContext);
  if (!value) throw new Error("useConsole must be used inside ConsoleProvider");
  return value;
}
