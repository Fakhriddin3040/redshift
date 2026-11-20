"use client";

// DESIGN_TZ §9.1. Real ISS dose from the NASA OSDR Environmental Data App
// (mission RR-12, April–May 2019). The values are real but old, so the page
// states when they were measured and never presents them as today's dose.

import { useEffect, useState } from "react";
import { useI18n, type Dict } from "@/i18n";
import { api } from "@/lib/api";
import type { RadiationResponse } from "@/lib/types";

const monthYear = (iso: string, t: Dict) =>
  new Date(`${iso}T00:00:00Z`).toLocaleDateString(t.intl, { month: "long", year: "numeric", timeZone: "UTC" });
const dayMonth = (iso: string, t: Dict) =>
  new Date(`${iso}T00:00:00Z`).toLocaleDateString(t.intl, { day: "numeric", month: "short", timeZone: "UTC" });

const CHART_PX = 150; // tallest bar, in a 160 px plot

function measured(d: RadiationResponse, t: Dict): string {
  if (!d.measured_from || !d.measured_to) return "";
  const a = monthYear(d.measured_from, t);
  const b = monthYear(d.measured_to, t);
  return a === b ? a : `${a.split(" ")[0]}–${b}`;
}

export default function RadiationPage() {
  const { t } = useI18n();
  const p = t.radiation;
  const dm = (iso: string) => dayMonth(iso, t);
  const [data, setData] = useState<RadiationResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api.radiation().then(setData).catch((e) => setErr(String(e.message ?? e)));
  }, []);

  const days = data?.days ?? [];
  const max = Math.max(0.0001, ...days.map((d) => d.total));
  const last = days.length ? days[days.length - 1] : null;
  const tiles: { k: string; v: number | null; unit: string; n: string }[] = [
    { k: p.lastDay, v: data?.last_24h ?? null, unit: p.mGy, n: last ? dm(last.day) + " 2019" : p.noStation },
    { k: p.mean14, v: data?.mean_14d ?? null, unit: p.mGyDay, n: days.length ? p.days(days.length) : p.noStation },
    { k: p.total14, v: data?.total_14d ?? null, unit: p.mGy, n: days.length ? `${dm(days[0].day)} – ${dm(days[days.length - 1].day)}` : p.noStation },
  ];

  return (
    <section className="page">
      <div>
        <div className="eyebrow">{p.eyebrow}</div>
        <h1 className="h1">{p.title}</h1>
        <p className="lede">
          {p.lede}
          {data && days.length > 0 && p.measured(measured(data, t))}
        </p>
      </div>
      <div className="tiles">
        {tiles.map((t) => (
          <div key={t.k} className="tile">
            <div className="k">{t.k}</div>
            <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
              <span className={t.v == null ? "v mute" : "v"}>{t.v == null ? "—" : t.v.toFixed(2)}</span>
              <span className="mute" style={{ fontSize: 12 }}>{t.unit}</span>
            </div>
            <div className="n">{t.n}</div>
          </div>
        ))}
      </div>
      <div>
        <h2 className="h2" style={{ marginBottom: 12 }}>{p.daily14}</h2>
        {days.length === 0 ? (
          <div style={{ height: 160, borderBottom: "1px solid var(--color-text)", display: "grid", placeItems: "center" }}>
            <span className="mute" style={{ fontSize: 13 }}>{err ? p.couldNotLoad(err) : p.noReadings}</span>
          </div>
        ) : (
          <>
            <div
              role="img"
              aria-label={p.aria(days.length, Math.min(...days.map((d) => d.total)).toFixed(2), max.toFixed(2))}
              style={{ height: 160, borderBottom: "1px solid var(--color-text)", display: "flex", alignItems: "flex-end", gap: 6 }}
            >
              {days.map((d) => {
                const gcr = d.gcr ?? 0;
                return (
                  <div
                    key={d.day}
                    title={p.barTitle(`${dm(d.day)} 2019`, d.total.toFixed(3), gcr.toFixed(3), (d.saa ?? 0).toFixed(3))}
                    style={{ flex: 1, minWidth: 4 }}
                  >
                    <div style={{ height: (Math.max(0, d.total - gcr) / max) * CHART_PX, background: "var(--color-accent)" }} />
                    <div style={{ height: (gcr / max) * CHART_PX, background: "var(--mute)", opacity: 0.55 }} />
                  </div>
                );
              })}
            </div>
            <div className="axis">
              <span>{dm(days[0].day)}</span>
              <span>{dm(days[Math.floor(days.length / 2)].day)}</span>
              <span>{dm(days[days.length - 1].day)}</span>
            </div>
          </>
        )}
        <p className="foot-note" style={{ marginTop: 10 }}>
          {p.foot}
          {data && days.length > 0 && p.source(data.source)}
        </p>
      </div>
    </section>
  );
}
