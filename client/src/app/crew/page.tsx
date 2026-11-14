"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { hhmm, levelColor, levelName, minutes } from "@/lib/format";
import { useVigil } from "@/lib/store";
import type { CrewItem } from "@/lib/types";

const TOPIC: Record<string, string> = {
  hr: "heart rate", spo2: "oxygen", rr: "breathing", skin_t: "temperature", co2: "CO₂", pressure: "pressure", amb_t: "cabin",
};

export default function CrewPage() {
  const { crewId, checkin } = useVigil();
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
        <div className="eyebrow">Crew summary · {crew ? `${crew.length} aboard` : "…"}</div>
        <h1 className="h1">The crew at a glance</h1>
        <p className="lede">Each crewmember chooses what appears here. Detail stays private to them and the flight surgeon; this page shows status only, and a blank is shown as a blank.</p>
      </div>
      {err && <p className="mute">{err}</p>}
      {crew && (
        <div style={{ overflowX: "auto" }}>
          <table className="table" style={{ minWidth: 720 }}>
            <thead>
              <tr><th>Crewmember</th><th>Status</th><th>Baseline</th><th>Check-in</th><th>Sleep, 7-night mean</th><th>Data today</th></tr>
            </thead>
            <tbody>
              {crew.map((c) => {
                const me = c.id === crewId;
                const noData = c.data_today_pct == null;
                const status = noData ? "No data today" : `${levelName(c.level)}${c.topic ? ` · ${TOPIC[c.topic] ?? c.topic}` : ""}`;
                const ci =
                  c.checkin_ts === "not_shared" ? "Not shared"
                  : me && checkin ? hhmm(checkin.filedTs)
                  : typeof c.checkin_ts === "number" ? hhmm(c.checkin_ts)
                  : "Not filed";
                const sleep =
                  c.sleep_7n_mean_min === "not_shared" ? "Not shared"
                  : typeof c.sleep_7n_mean_min === "number" ? minutes(c.sleep_7n_mean_min)
                  : "—";
                const mute = (s: string) => (s === "Not shared" || s === "Not filed" || s === "—" ? "var(--mute)" : undefined);
                return (
                  <tr key={c.id}>
                    <td>
                      {c.name}
                      {me ? <em className="mute"> (you)</em> : <span className="mute">, {c.role}</span>}
                    </td>
                    <td style={{ color: noData ? "var(--mute)" : levelColor(c.level, "inherit") }}>{status}</td>
                    <td style={{ color: c.baseline.state === "learning" ? "var(--vital)" : undefined }}>
                      {c.baseline.state === "learned" ? "Learned" : `Learning · day ${c.baseline.day} of ${c.baseline.of}`}
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
