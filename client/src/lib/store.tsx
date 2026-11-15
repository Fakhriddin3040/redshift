"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { api, liveUrl } from "./api";
import type { LiveMessage, Today } from "./types";

const DEFAULT_CREW = Number(process.env.NEXT_PUBLIC_CREW_ID ?? 1) || 1;
const POLL_MS = 10_000;

export interface Checkin {
  day: string; // YYYY-MM-DD (GMT, from server time)
  sleep: number;
  mood: number;
  energy: number;
  symptoms: string[];
  note: string;
  filedTs: number;
}

export interface ReportDraft {
  include: Record<string, boolean>;
  note: string;
  queued: boolean;
}

export const REPORT_SECTIONS = [
  ["vitals", "Vital signs summary"],
  ["alerts", "Alerts and notices"],
  ["sleep", "Sleep"],
  ["checkin", "Daily check-in"],
  ["cabin", "Cabin air"],
] as const;

const DEFAULT_REPORT: ReportDraft = {
  include: Object.fromEntries(REPORT_SECTIONS.map(([k]) => [k, true])),
  note: "",
  queued: false,
};

interface VigilState {
  crewId: number;
  setCrewId: (id: number) => void;
  today: Today | null;
  error: string | null;
  live: "connecting" | "open" | "closed";
  lastTickAt: number | null; // wall-clock ms of the last live tick
  refresh: () => Promise<void>;
  ack: (alertId: number) => Promise<void>;
  checkin: Checkin | null;
  saveCheckin: (c: Omit<Checkin, "day" | "filedTs">) => void;
  dayKey: string | null;
  report: ReportDraft;
  saveReport: (r: ReportDraft) => void;
}

const Ctx = createContext<VigilState | null>(null);

function readLocal<T>(key: string): T | null {
  try {
    const s = localStorage.getItem(key);
    return s ? (JSON.parse(s) as T) : null;
  } catch {
    return null;
  }
}
function writeLocal(key: string, value: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* storage unavailable — keep in memory only */
  }
}

export function dayOf(ts: number | null | undefined): string | null {
  return ts == null ? null : new Date(ts * 1000).toISOString().slice(0, 10);
}

export function VigilProvider({ children }: { children: React.ReactNode }) {
  const [crewId, setCrewIdState] = useState(DEFAULT_CREW);
  const [today, setToday] = useState<Today | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [live, setLive] = useState<VigilState["live"]>("connecting");
  const [lastTickAt, setLastTickAt] = useState<number | null>(null);
  const [checkins, setCheckins] = useState<Record<string, Checkin>>({});
  const [reports, setReports] = useState<Record<string, ReportDraft>>({});
  const refetchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    // localStorage is only readable after hydration
    const saved = readLocal<number>("vigil.crew");
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (saved) setCrewIdState(saved);
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setCheckins(readLocal<Record<string, Checkin>>(`vigil.checkin.${crewId}`) ?? {});
    setReports(readLocal<Record<string, ReportDraft>>(`vigil.report.${crewId}`) ?? {});
  }, [crewId]);

  const setCrewId = useCallback((id: number) => {
    writeLocal("vigil.crew", id);
    setToday(null);
    setCrewIdState(id);
  }, []);

  const refresh = useCallback(async () => {
    try {
      const t = await api.today(crewId);
      setToday(t);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [crewId]);

  const scheduleRefresh = useCallback(() => {
    if (refetchTimer.current) clearTimeout(refetchTimer.current);
    refetchTimer.current = setTimeout(() => void refresh(), 150);
  }, [refresh]);

  // polling: catches card states, device link and anything the socket does not push
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- async fetch, state is set after await
    void refresh();
    const id = setInterval(() => void refresh(), POLL_MS);
    return () => clearInterval(id);
  }, [refresh]);

  // live socket with reconnect
  useEffect(() => {
    let ws: WebSocket | null = null;
    let stopped = false;
    let retry: ReturnType<typeof setTimeout> | null = null;

    const connect = () => {
      setLive("connecting");
      try {
        ws = new WebSocket(liveUrl(crewId));
      } catch {
        setLive("closed");
        retry = setTimeout(connect, 3000);
        return;
      }
      ws.onopen = () => setLive("open");
      ws.onclose = () => {
        setLive("closed");
        if (!stopped) retry = setTimeout(connect, 3000);
      };
      ws.onerror = () => ws?.close();
      ws.onmessage = (ev) => {
        let msg: LiveMessage;
        try {
          msg = JSON.parse(ev.data);
        } catch {
          return;
        }
        if (msg.t === "tick") {
          setLastTickAt(Date.now());
          setToday((t) => {
            if (!t) return t;
            const upd = <C extends Today["vitals"][number]>(c: C): C => {
              if (!(c.m in msg.v) || c.state === "not_measured") return c;
              const v = msg.v[c.m];
              return { ...c, value: v ?? null };
            };
            return {
              ...t,
              now_ts: msg.ts,
              ctx: msg.ctx ?? t.ctx,
              level: msg.level,
              device: { ...t.device, link: "connected", worn: msg.worn },
              vitals: t.vitals.map(upd),
              cabin: t.cabin.map(upd),
            };
          });
        } else if (msg.t === "level") {
          setToday((t) => (t ? { ...t, level: msg.level, critical_acked: msg.critical_acked } : t));
          scheduleRefresh();
        } else {
          scheduleRefresh();
        }
      };
    };
    connect();
    return () => {
      stopped = true;
      if (retry) clearTimeout(retry);
      ws?.close();
    };
  }, [crewId, scheduleRefresh]);

  const ack = useCallback(
    async (alertId: number) => {
      // optimistic: mark acked locally so the Critical screen closes at once
      setToday((t) =>
        t
          ? {
              ...t,
              critical_acked: t.critical_acked || t.notices.some((n) => n.id === alertId && n.key === "incident" && n.level === 3),
              notices: t.notices.map((n) => (n.id === alertId ? { ...n, ack_ts: t.now_ts ?? 0 } : n)),
            }
          : t
      );
      try {
        await api.ack(alertId);
      } finally {
        await refresh();
      }
    },
    [refresh]
  );

  const dayKey = dayOf(today?.now_ts);
  const checkin = dayKey ? checkins[dayKey] ?? null : null;

  const saveCheckin = useCallback(
    (c: Omit<Checkin, "day" | "filedTs">) => {
      if (!dayKey) return;
      const entry: Checkin = { ...c, day: dayKey, filedTs: today?.now_ts ?? Math.floor(Date.now() / 1000) };
      setCheckins((all) => {
        const next = { ...all, [dayKey]: entry };
        writeLocal(`vigil.checkin.${crewId}`, next);
        return next;
      });
      // The server stores it, shows it on the Crew page and closes today's reminder.
      // If the server is unreachable the entry stays in this browser and the reminder is acknowledged here.
      api.checkin(crewId, c)
        .then(() => refresh())
        .catch(() => {
          const reminder = today?.notices.find((n) => n.key === `checkin:${dayKey}` && n.ack_ts == null);
          if (reminder) void ack(reminder.id);
        });
    },
    [dayKey, today, crewId, ack, refresh]
  );

  const report = (dayKey && reports[dayKey]) || DEFAULT_REPORT;
  const saveReport = useCallback(
    (r: ReportDraft) => {
      if (!dayKey) return;
      setReports((all) => {
        const next = { ...all, [dayKey]: r };
        writeLocal(`vigil.report.${crewId}`, next);
        return next;
      });
    },
    [dayKey, crewId]
  );

  const value = useMemo<VigilState>(
    () => ({ crewId, setCrewId, today, error, live, lastTickAt, refresh, ack, checkin, saveCheckin, dayKey, report, saveReport }),
    [crewId, setCrewId, today, error, live, lastTickAt, refresh, ack, checkin, saveCheckin, dayKey, report, saveReport]
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useVigil(): VigilState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useVigil outside VigilProvider");
  return v;
}

/** Page level for the background: usual / watch / alert / critical-acked. */
export function pageLevel(t: Today | null): "usual" | "watch" | "alert" | "critical" | "critical-acked" {
  if (!t) return "usual";
  if (t.level === 3) return t.critical_acked ? "critical-acked" : "critical";
  return (["usual", "watch", "alert"] as const)[t.level];
}
