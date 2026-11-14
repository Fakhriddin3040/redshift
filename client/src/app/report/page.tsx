"use client";

import { useEffect, useState } from "react";
import { Loading } from "@/components/Loading";
import { api } from "@/lib/api";
import { SYMPTOM_LABEL } from "@/lib/checkin";
import { METRIC, PATTERN_LABEL, fmtUnit, hhmm, levelName, longDate, minutes } from "@/lib/format";
import { REPORT_SECTIONS, dayOf, useVigil } from "@/lib/store";
import type { Alert, CrewItem, Today } from "@/lib/types";

function vitalsLine(t: Today): string {
  const shown = t.vitals.filter((c) => c.value != null);
  if (!shown.length) return "No vital-sign readings at the moment of writing.";
  const list = shown.map((c) => `${METRIC[c.m].lower} ${fmtUnit(c.value, c.m)}`).join(", ");
  const off = shown.filter((c) => c.state === "watch" || c.state === "alert" || c.state === "critical");
  const tail = off.length
    ? ` Outside personal baseline: ${off.map((c) => METRIC[c.m].lower).join(", ")}.`
    : t.baseline.state === "learning"
      ? ` Personal baseline still being learned (day ${t.baseline.day} of ${t.baseline.of}).`
      : " All within personal baseline.";
  return list[0].toUpperCase() + list.slice(1) + "." + tail;
}

function alertsLine(alerts: Alert[], day: string | null): string {
  const todays = alerts.filter((a) => a.key === "incident" && dayOf(a.ts_start) === day);
  if (!todays.length) return "No alerts today.";
  return todays
    .map((a) => {
      const topic = a.pattern ? PATTERN_LABEL[a.pattern] ?? a.pattern : a.primary ? METRIC[a.primary].label : "Reading";
      return `${levelName(a.peak_level)} · ${topic} at ${hhmm(a.ts_start)}, ${minutes(Math.max(1, a.since_min))}${a.ack_ts ? ", acknowledged" : ""}${a.ts_end ? "" : ", ongoing"}.`;
    })
    .join(" ");
}

function cabinLine(t: Today): string {
  const parts = t.cabin.filter((c) => c.value != null).map((c) => `${METRIC[c.m].lower} ${fmtUnit(c.value, c.m)}`);
  if (!parts.length) return "No cabin readings.";
  const co2 = t.cabin.find((c) => c.m === "ppco2");
  const s = parts.join(", ");
  return s[0].toUpperCase() + s.slice(1) + "." + (co2?.value != null ? (co2.value > 3 ? " CO₂ above the 3.0 mmHg limit." : " CO₂ under the 3.0 mmHg limit.") : "");
}

function coverageLine(t: Today, me: CrewItem | undefined): string {
  if (!me || me.data_today_pct == null || t.now_ts == null) return "No data today.";
  const elapsed = Math.floor((t.now_ts % 86400) / 60) + 1;
  const withData = Math.round((me.data_today_pct / 100) * elapsed);
  return `${minutes(withData)} of data, ${minutes(elapsed - withData)} without.`;
}

export default function ReportPage() {
  const { today, crewId, checkin, report, saveReport, dayKey } = useVigil();
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [crew, setCrew] = useState<CrewItem[]>([]);

  useEffect(() => {
    api.alerts(crewId).then(setAlerts).catch(() => setAlerts([]));
    api.crew().then(setCrew).catch(() => setCrew([]));
  }, [crewId]);

  if (!today) return <Loading />;
  const me = crew.find((c) => c.id === crewId);

  const text: Record<string, string> = {
    vitals: vitalsLine(today),
    alerts: alertsLine(alerts, dayKey),
    sleep: "No nights recorded yet.",
    checkin: checkin
      ? `Sleep quality ${checkin.sleep}/5, mood ${checkin.mood}/5, energy ${checkin.energy}/5. ` +
        (checkin.symptoms.length ? `Reported: ${checkin.symptoms.map((s) => SYMPTOM_LABEL[s]?.toLowerCase() ?? s).join(", ")}.` : "No symptoms reported.") +
        (checkin.note ? ` “${checkin.note}”` : "")
      : "Not filed today. No data.",
    cabin: cabinLine(today),
  };
  const titles: Record<string, string> = { vitals: "Vital signs", alerts: "Alerts and notices", sleep: "Sleep", checkin: "Check-in", cabin: "Cabin air" };

  const set = (patch: Partial<typeof report>) => saveReport({ ...report, ...patch, queued: patch.queued ?? false });

  return (
    <section className="page" style={{ gap: 28 }}>
      <div>
        <div className="eyebrow">Report for Earth</div>
        <h1 className="h1">What the ground will read</h1>
        <p className="lede">You decide what goes into the daily health summary for your flight surgeon. It is sent at the next acquisition of signal.</p>
      </div>
      <div className="cols" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))" }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <h2 className="h2">Include</h2>
          <div>
            {REPORT_SECTIONS.map(([k, label]) => {
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
                  <span style={{ flex: 1 }}>{label}</span>
                </button>
              );
            })}
            <div style={{ display: "flex", gap: 12, alignItems: "center", borderTop: "1px solid var(--color-divider)", padding: "11px 0" }}>
              <span style={{ width: 14, flex: "none" }} />
              <span className="mute">Data coverage — always included</span>
            </div>
          </div>
          <div className="field">
            <label htmlFor="rep-note">Note to the flight surgeon</label>
            <textarea id="rep-note" className="input" value={report.note} onChange={(e) => set({ note: e.target.value })} placeholder="Anything you want raised at the next private medical conference" />
          </div>
          <div style={{ display: "flex", gap: 14, alignItems: "center", flexWrap: "wrap" }}>
            <button className="btn btn-primary" onClick={() => saveReport({ ...report, queued: !report.queued })}>
              {report.queued ? "Withdraw from queue" : "Queue for next downlink"}
            </button>
            <span className="mute" style={{ fontSize: 13 }}>{report.queued ? "Queued. Sends at the next acquisition of signal." : "Sends at the next acquisition of signal."}</span>
          </div>
        </div>

        <div style={{ border: "1px solid var(--color-divider)", padding: "28px 32px", display: "flex", flexDirection: "column", gap: 14 }}>
          <div className="mute num" style={{ fontSize: 12, display: "flex", flexDirection: "column", gap: 2 }}>
            <span>To: Flight Surgeon, Mission Control</span>
            <span>From: {me ? `${me.name}, ${me.role}` : `Crew ${crewId}`}</span>
            <span>{today.flight_day != null ? `Flight day ${today.flight_day} · ` : ""}{longDate(today.now_ts)}</span>
          </div>
          <div style={{ height: 1, background: "var(--color-text)" }} />
          <div style={{ fontSize: 19, letterSpacing: "-0.01em", lineHeight: 1.1 }}>Daily health summary</div>
          {REPORT_SECTIONS.map(([k]) => (
            <div key={k}>
              <div className="mute" style={{ fontSize: 12 }}>{titles[k]}</div>
              <p style={{ marginTop: 2, fontSize: 14, color: report.include[k] === false ? "var(--mute)" : undefined }}>
                {report.include[k] === false ? "Not shared today." : text[k]}
              </p>
            </div>
          ))}
          <div>
            <div className="mute" style={{ fontSize: 12 }}>Data coverage</div>
            <p className="num" style={{ marginTop: 2, fontSize: 14 }}>{coverageLine(today, me)}</p>
          </div>
          {report.note && (
            <div>
              <div className="mute" style={{ fontSize: 12 }}>Note from crewmember</div>
              <p style={{ marginTop: 2, fontSize: 14 }}>{report.note}</p>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
