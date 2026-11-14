"use client";

import { useEffect, useRef, useState } from "react";
import { Loading } from "@/components/Loading";
import { deviceLine } from "@/components/Shell";
import { api } from "@/lib/api";
import { hhmm, minutes } from "@/lib/format";
import { useVigil } from "@/lib/store";
import type { Card, CrewItem, MetricResponse } from "@/lib/types";

function sensorStatus(cards: Card[], keys: string[]): string {
  const hit = cards.filter((c) => keys.includes(c.m));
  return hit.some((c) => c.state !== "not_measured") ? "Working" : "Not installed";
}

export default function DevicePage() {
  const { today, crewId, lastTickAt } = useVigil();
  const [day, setDay] = useState<MetricResponse | null>(null);
  const [me, setMe] = useState<CrewItem | null>(null);
  const [ago, setAgo] = useState<number | null>(null);

  const setAgoRef = useRef(() => {});
  useEffect(() => {
    setAgoRef.current = () => setAgo(lastTickAt ? Math.max(0, Math.round((Date.now() - lastTickAt) / 1000)) : null);
  }, [lastTickAt]);

  useEffect(() => {
    const load = () => {
      const probe = today?.vitals.find((c) => c.state !== "not_measured")?.m ?? "hr";
      api.metric(crewId, probe, "24h").then(setDay).catch(() => setDay(null));
      api.crew().then((all) => setMe(all.find((c) => c.id === crewId) ?? null)).catch(() => undefined);
    };
    load();
    const id = setInterval(load, 60_000);
    const tick = setInterval(() => setAgoRef.current(), 1000);
    return () => {
      clearInterval(id);
      clearInterval(tick);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [crewId, today == null]);

  if (!today) return <Loading />;

  const d = today.device;
  const line = deviceLine(today, lastTickAt);
  const offSince = today.vitals.map((c) => c.since_ts).find((s) => s != null);
  const title =
    d.link === "no_link"
      ? `No link to the wristband${line.text.startsWith("No link for") ? ` for ${line.text.slice(12)}` : ""}.`
      : d.worn === false
        ? `Wristband not worn${offSince ? ` since ${hhmm(offSince)}` : ""}.`
        : "Wristband connected.";

  // 24 h presence from the last day of minute points
  const segs: { a: number; b: number }[] = [];
  let withData = 0;
  if (day) {
    const n = day.points.length;
    let s: number | null = null;
    day.points.forEach((p, i) => {
      const has = p[1] != null && p[4] !== 0;
      if (has) withData++;
      if (has && s == null) s = i;
      if (!has && s != null) {
        segs.push({ a: s / n, b: i / n });
        s = null;
      }
    });
    if (s != null) segs.push({ a: s / n, b: 1 });
  }
  const total = day ? day.points.length : 0;
  const cards = [...today.vitals, ...today.cabin];
  const axis = day ? [0, 0.25, 0.5, 0.75, 1].map((f) => hhmm(day.points[0][0] + f * day.points.length * day.step_s)) : [];

  return (
    <section className="page">
      <div>
        <div className="eyebrow">Device</div>
        <h1 className="h1">{title}</h1>
      </div>

      <div>
        <h2 className="h2" style={{ marginBottom: 12 }}>Data today</h2>
        <div className="dayband">
          {segs.map((s) => <i key={s.a} style={{ left: `${s.a * 100}%`, width: `${(s.b - s.a) * 100}%` }} />)}
        </div>
        <div className="axis">{axis.map((t, i) => <span key={i}>{t}</span>)}</div>
        <p className="foot-note num" style={{ marginTop: 10 }}>
          {day ? `${minutes(withData)} of data · ${minutes(total - withData)} without · last 24 hours` : "No readings in this period."}
        </p>
      </div>

      <div className="tiles">
        <div className="tile">
          <div className="k">Link</div>
          <div className="v" style={{ fontSize: 24, color: d.link === "no_link" ? "var(--kick)" : undefined }}>{d.link === "connected" ? "Connected" : "No link"}</div>
          <div className="n">{ago != null ? `Last reading ${ago} s ago` : "No live reading yet"}</div>
        </div>
        <div className="tile">
          <div className="k">Signal</div>
          <div className="v" style={{ fontSize: 24, color: d.signal === "poor" ? "var(--kick)" : undefined }}>{d.signal ? d.signal[0].toUpperCase() + d.signal.slice(1) : "—"}</div>
          <div className="n">{d.worn === false ? "Not worn" : "Optical contact"}</div>
        </div>
        <div className="tile">
          <div className="k">Battery</div>
          <div className="v" style={{ fontSize: 24 }}>{d.batt != null ? `${d.batt} %` : "—"}</div>
          <div className="n">Wristband</div>
        </div>
        <div className="tile">
          <div className="k">Data today</div>
          <div className="v" style={{ fontSize: 24 }}>{me?.data_today_pct != null ? `${me.data_today_pct} %` : "—"}</div>
          <div className="n">Of minutes since 00:00 GMT</div>
        </div>
      </div>

      <div>
        <h2 className="h2" style={{ marginBottom: 4 }}>Sensors</h2>
        <table className="table">
          <thead><tr><th>Sensor</th><th>Measures</th><th>Status</th></tr></thead>
          <tbody>
            {[
              ["Optical", "Heart rate, blood oxygen, respiration", sensorStatus(cards, ["hr", "spo2", "rr"])],
              ["Motion", "Activity, sleep", today.ctx ? "Working" : "Not installed"],
              ["Skin temperature", "Skin temperature", sensorStatus(cards, ["skin_t"])],
              ["Cabin air", "CO₂, temperature", sensorStatus(cards, ["ppco2", "amb_t"])],
              ["Pressure", "Cabin pressure", sensorStatus(cards, ["press"])],
            ].map(([s, m, st]) => (
              <tr key={s}>
                <td>{s}</td>
                <td className="mute">{m}</td>
                <td style={{ color: st === "Working" ? undefined : "var(--mute)" }}>{st}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
