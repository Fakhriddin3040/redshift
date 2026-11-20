"use client";

import { useEffect, useState } from "react";
import { Loading } from "@/components/Loading";
import { api } from "@/lib/api";
import { useI18n, type Dict } from "@/i18n";
import { fmtUnit, hhmm, levelName, longDate } from "@/lib/format";
import { REPORT_SECTIONS, dayOf, useVigil } from "@/lib/store";
import type { Alert, CrewItem, Today } from "@/lib/types";

function vitalsLine(today: Today, t: Dict): string {
  const shown = today.vitals.filter((c) => c.value != null);
  if (!shown.length) return t.report.noVitals;
  const list = shown.map((c) => `${t.metric[c.m].lower} ${fmtUnit(c.value, c.m, t)}`).join(", ");
  const off = shown.filter((c) => c.state === "watch" || c.state === "alert" || c.state === "critical");
  const tail = off.length
    ? t.report.outside(off.map((c) => t.metric[c.m].lower).join(", "))
    : today.baseline.state === "learning"
      ? t.report.learning(today.baseline.day, today.baseline.of)
      : t.report.allWithin;
  return list[0].toUpperCase() + list.slice(1) + "." + tail;
}

function alertsLine(alerts: Alert[], day: string | null, t: Dict): string {
  const todays = alerts.filter((a) => a.key === "incident" && dayOf(a.ts_start) === day);
  if (!todays.length) return t.report.noAlerts;
  return todays
    .map((a) => {
      const topic = a.pattern ? t.pattern[a.pattern] ?? a.pattern : a.primary ? t.metric[a.primary].label : t.report.reading;
      return t.report.alertLine(
        levelName(a.peak_level, t), topic, hhmm(a.ts_start), t.minutes(Math.max(1, a.since_min)), a.ack_ts != null, !a.ts_end
      );
    })
    .join(" ");
}

function cabinLine(today: Today, t: Dict): string {
  const parts = today.cabin.filter((c) => c.value != null).map((c) => `${t.metric[c.m].lower} ${fmtUnit(c.value, c.m, t)}`);
  if (!parts.length) return t.report.noCabin;
  const co2 = today.cabin.find((c) => c.m === "ppco2");
  const s = parts.join(", ");
  return s[0].toUpperCase() + s.slice(1) + "." + (co2?.value != null ? (co2.value > 3 ? t.report.co2Above : t.report.co2Under) : "");
}

function coverageLine(today: Today, me: CrewItem | undefined, t: Dict): string {
  if (!me || me.data_today_pct == null || today.now_ts == null) return t.report.noDataToday;
  const elapsed = Math.floor((today.now_ts % 86400) / 60) + 1;
  const withData = Math.round((me.data_today_pct / 100) * elapsed);
  return t.report.coverage(t.minutes(withData), t.minutes(elapsed - withData));
}

export default function ReportPage() {
  const { today, crewId, checkin, report, saveReport, dayKey } = useVigil();
  const { t } = useI18n();
  const r = t.report;
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [crew, setCrew] = useState<CrewItem[]>([]);

  useEffect(() => {
    api.alerts(crewId).then(setAlerts).catch(() => setAlerts([]));
    api.crew().then(setCrew).catch(() => setCrew([]));
  }, [crewId]);

  if (!today) return <Loading />;
  const me = crew.find((c) => c.id === crewId);

  const text: Record<string, string> = {
    vitals: vitalsLine(today, t),
    alerts: alertsLine(alerts, dayKey, t),
    sleep: r.noNights,
    checkin: checkin
      ? r.checkinLine(checkin.sleep, checkin.mood, checkin.energy) +
        (checkin.symptoms.length ? r.reported(checkin.symptoms.map((s) => t.checkin.symptoms[s]?.toLowerCase() ?? s).join(", ")) : r.noSymptoms) +
        (checkin.note ? ` “${checkin.note}”` : "")
      : r.checkinNotFiled,
    cabin: cabinLine(today, t),
  };

  const set = (patch: Partial<typeof report>) => saveReport({ ...report, ...patch, queued: patch.queued ?? false });

  return (
    <section className="page" style={{ gap: 28 }}>
      <div>
        <div className="eyebrow">{r.eyebrow}</div>
        <h1 className="h1">{r.title}</h1>
        <p className="lede">{r.lede}</p>
      </div>
      <div className="cols" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))" }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <h2 className="h2">{r.include}</h2>
          <div>
            {REPORT_SECTIONS.map((k) => {
              const on = report.include[k] !== false;
              return (
                <button
                  key={k}
                  role="checkbox"
                  aria-checked={on}
                  onClick={() => set({ include: { ...report.include, [k]: !on } })}
                  style={{ display: "flex", gap: 12, alignItems: "center", width: "100%", background: "none", border: 0, borderTop: "1px solid var(--color-divider)", padding: "11px 0", cursor: "pointer", textAlign: "left" }}
                >
                  <span className="check" data-on={on} />
                  <span style={{ flex: 1 }}>{r.sections[k]}</span>
                </button>
              );
            })}
            <div style={{ display: "flex", gap: 12, alignItems: "center", borderTop: "1px solid var(--color-divider)", padding: "11px 0" }}>
              <span style={{ width: 14, flex: "none" }} />
              <span className="mute">{r.coverageAlways}</span>
            </div>
          </div>
          <div className="field">
            <label htmlFor="rep-note">{r.noteLabel}</label>
            <textarea id="rep-note" className="input" value={report.note} onChange={(e) => set({ note: e.target.value })} placeholder={r.notePlaceholder} />
          </div>
          <div style={{ display: "flex", gap: 14, alignItems: "center", flexWrap: "wrap" }}>
            <button className="btn btn-primary" onClick={() => saveReport({ ...report, queued: !report.queued })}>
              {report.queued ? r.withdraw : r.queue}
            </button>
            <span className="mute" style={{ fontSize: 13 }}>{report.queued ? r.queuedNote : r.sendsNote}</span>
          </div>
        </div>

        <div style={{ border: "1px solid var(--color-divider)", padding: "28px 32px", display: "flex", flexDirection: "column", gap: 14 }}>
          <div className="mute num" style={{ fontSize: 12, display: "flex", flexDirection: "column", gap: 2 }}>
            <span>{r.to}</span>
            <span>{r.from(me ? `${me.name}, ${me.role}` : r.crewN(crewId))}</span>
            <span>{today.flight_day != null ? `${t.flightDay(today.flight_day)} · ` : ""}{longDate(today.now_ts, t)}</span>
          </div>
          <div style={{ height: 1, background: "var(--color-text)" }} />
          <div style={{ fontSize: 19, letterSpacing: "-0.01em", lineHeight: 1.1 }}>{r.summary}</div>
          {REPORT_SECTIONS.map((k) => (
            <div key={k}>
              <div className="mute" style={{ fontSize: 12 }}>{r.titles[k]}</div>
              <p style={{ marginTop: 2, fontSize: 14, color: report.include[k] === false ? "var(--mute)" : undefined }}>
                {report.include[k] === false ? r.notShared : text[k]}
              </p>
            </div>
          ))}
          <div>
            <div className="mute" style={{ fontSize: 12 }}>{r.coverageTitle}</div>
            <p className="num" style={{ marginTop: 2, fontSize: 14 }}>{coverageLine(today, me, t)}</p>
          </div>
          {report.note && (
            <div>
              <div className="mute" style={{ fontSize: 12 }}>{r.noteFrom}</div>
              <p style={{ marginTop: 2, fontSize: 14 }}>{report.note}</p>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
