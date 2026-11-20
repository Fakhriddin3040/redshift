"use client";

import { useEffect, useRef, useState } from "react";
import { Loading } from "@/components/Loading";
import { deviceLine } from "@/components/Shell";
import { api } from "@/lib/api";
import { useI18n } from "@/i18n";
import { hhmm } from "@/lib/format";
import { useVigil } from "@/lib/store";
import type { Card, CrewItem, MetricResponse } from "@/lib/types";

function sensorWorks(cards: Card[], keys: string[]): boolean {
  return cards.some((c) => keys.includes(c.m) && c.state !== "not_measured");
}

export default function DevicePage() {
  const { today, crewId, lastTickAt } = useVigil();
  const { t } = useI18n();
  const p = t.devicePage;
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
  const line = deviceLine(today, lastTickAt, t);
  const offSince = today.vitals.map((c) => c.since_ts).find((s) => s != null);
  const title =
    d.link === "no_link"
      ? p.noLink(line.noLinkMin ? t.minutes(line.noLinkMin) : null)
      : d.worn === false
        ? p.notWorn(offSince ? hhmm(offSince) : null)
        : p.connected;

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
        <div className="eyebrow">{p.eyebrow}</div>
        <h1 className="h1">{title}</h1>
      </div>

      <div>
        <h2 className="h2" style={{ marginBottom: 12 }}>{p.dataToday}</h2>
        <div className="dayband">
          {segs.map((s) => <i key={s.a} style={{ left: `${s.a * 100}%`, width: `${(s.b - s.a) * 100}%` }} />)}
        </div>
        <div className="axis">{axis.map((t, i) => <span key={i}>{t}</span>)}</div>
        <p className="foot-note num" style={{ marginTop: 10 }}>
          {day ? p.coverage(t.minutes(withData), t.minutes(total - withData)) : p.noReadings}
        </p>
      </div>

      <div className="tiles">
        <div className="tile">
          <div className="k">{p.link}</div>
          <div className="v" style={{ fontSize: 24, color: d.link === "no_link" ? "var(--kick)" : undefined }}>{d.link === "connected" ? p.connectedWord : p.noLinkWord}</div>
          <div className="n">{ago != null ? p.lastReading(ago) : p.noLive}</div>
        </div>
        <div className="tile">
          <div className="k">{p.signal}</div>
          <div className="v" style={{ fontSize: 24, color: d.signal === "poor" ? "var(--kick)" : undefined }}>{d.signal ? t.signal[d.signal] : "—"}</div>
          <div className="n">{d.worn === false ? p.notWorn2 : p.optical}</div>
        </div>
        <div className="tile">
          <div className="k">{p.battery}</div>
          <div className="v" style={{ fontSize: 24 }}>{d.batt != null ? `${d.batt} %` : "—"}</div>
          <div className="n">{p.wristband}</div>
        </div>
        <div className="tile">
          <div className="k">{p.dataToday}</div>
          <div className="v" style={{ fontSize: 24 }}>{me?.data_today_pct != null ? `${me.data_today_pct} %` : "—"}</div>
          <div className="n">{p.minutesSince}</div>
        </div>
      </div>

      <div>
        <h2 className="h2" style={{ marginBottom: 4 }}>{p.sensors}</h2>
        <table className="table">
          <thead><tr>{p.cols.map((h) => <th key={h}>{h}</th>)}</tr></thead>
          <tbody>
            {([
              ["optical", sensorWorks(cards, ["hr", "spo2", "rr"])],
              ["motion", today.ctx != null],
              ["skin", sensorWorks(cards, ["skin_t"])],
              ["cabin", sensorWorks(cards, ["ppco2", "amb_t"])],
              ["press", sensorWorks(cards, ["press"])],
            ] as const).map(([k, works]) => (
              <tr key={k}>
                <td>{p.rows[k][0]}</td>
                <td className="mute">{p.rows[k][1]}</td>
                <td style={{ color: works ? undefined : "var(--mute)" }}>{works ? p.working : p.notInstalled}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
