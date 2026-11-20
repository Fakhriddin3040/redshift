"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useI18n } from "@/i18n";
import { hhmm, levelColor, levelName } from "@/lib/format";
import { useVigil } from "@/lib/store";
import type { CrewItem } from "@/lib/types";

export default function CrewPage() {
  const { crewId, checkin } = useVigil();
  const { t } = useI18n();
  const p = t.crew;
  const [crew, setCrew] = useState<CrewItem[] | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    const load = () => api.crew().then((c) => { setCrew(c); setErr(null); }).catch((e) => setErr(String(e.message ?? e)));
    load();
    const id = setInterval(load, 15_000);
    return () => clearInterval(id);
  }, []);

  return (
    <section className="page" style={{ gap: 28 }}>
      <div>
        <div className="eyebrow">{p.eyebrow(crew ? crew.length : null)}</div>
        <h1 className="h1">{p.title}</h1>
        <p className="lede">{p.lede}</p>
      </div>
      {err && <p className="mute">{err}</p>}
      {crew && (
        <div style={{ overflowX: "auto" }}>
          <table className="table" style={{ minWidth: 720 }}>
            <thead>
              <tr>{p.cols.map((h) => <th key={h}>{h}</th>)}</tr>
            </thead>
            <tbody>
              {crew.map((c) => {
                const me = c.id === crewId;
                const noData = c.data_today_pct == null;
                const status = noData ? p.noDataToday : `${levelName(c.level, t)}${c.topic ? ` · ${p.topic[c.topic] ?? c.topic}` : ""}`;
                const ci =
                  c.checkin_ts === "not_shared" ? p.notShared
                  : me && checkin ? hhmm(checkin.filedTs)
                  : typeof c.checkin_ts === "number" ? hhmm(c.checkin_ts)
                  : p.notFiled;
                const sleep =
                  c.sleep_7n_mean_min === "not_shared" ? p.notShared
                  : typeof c.sleep_7n_mean_min === "number" ? t.minutes(c.sleep_7n_mean_min)
                  : "—";
                const mute = (s: string) => (s === p.notShared || s === p.notFiled || s === "—" ? "var(--mute)" : undefined);
                return (
                  <tr key={c.id}>
                    <td>
                      {c.name}
                      {me ? <em className="mute">{p.you}</em> : <span className="mute">, {c.role}</span>}
                    </td>
                    <td style={{ color: noData ? "var(--mute)" : levelColor(c.level, "inherit") }}>{status}</td>
                    <td style={{ color: c.baseline.state === "learning" ? "var(--vital)" : undefined }}>
                      {c.baseline.state === "learned" ? p.learned : p.learning(c.baseline.day, c.baseline.of)}
                    </td>
                    <td style={{ color: mute(ci) }}>{ci}</td>
                    <td style={{ color: mute(sleep) }}>{sleep}</td>
                    <td style={{ color: noData ? "var(--mute)" : undefined }}>{noData ? "—" : `${c.data_today_pct} %`}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
