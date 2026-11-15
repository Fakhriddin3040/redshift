"use client";

// DESIGN_TZ §9.1. Real ISS dose from the NASA OSDR Environmental Data App
// (mission RR-12, April–May 2019). The values are real but old, so the page
// states when they were measured and never presents them as today's dose.

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { RadiationResponse } from "@/lib/types";

const monthYear = (iso: string) =>
  new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-GB", { month: "long", year: "numeric", timeZone: "UTC" });
const dayMonth = (iso: string) =>
  new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });

const CHART_PX = 150; // tallest bar, in a 160 px plot

function measured(d: RadiationResponse): string {
  if (!d.measured_from || !d.measured_to) return "";
  const a = monthYear(d.measured_from);
  const b = monthYear(d.measured_to);
  return a === b ? a : `${a.split(" ")[0]}–${b}`;
}

export default function RadiationPage() {
  const [data, setData] = useState<RadiationResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api.radiation().then(setData).catch((e) => setErr(String(e.message ?? e)));
  }, []);

  const days = data?.days ?? [];
  const max = Math.max(0.0001, ...days.map((d) => d.total));
  const last = days.length ? days[days.length - 1] : null;
  const tiles: { k: string; v: number | null; unit: string; n: string }[] = [
    { k: "Last recorded day", v: data?.last_24h ?? null, unit: "mGy", n: last ? dayMonth(last.day) + " 2019" : "No station data yet" },
    { k: "Mean, fourteen days", v: data?.mean_14d ?? null, unit: "mGy/day", n: days.length ? `${days.length} days` : "No station data yet" },
    { k: "Total, fourteen days", v: data?.total_14d ?? null, unit: "mGy", n: days.length ? `${dayMonth(days[0].day)} – ${dayMonth(days[days.length - 1].day)}` : "No station data yet" },
  ];

  return (
    <section className="page">
      <div>
        <div className="eyebrow">Station dosimeter · ISS · NASA OSDR Environmental Data App</div>
        <h1 className="h1">Radiation</h1>
        <p className="lede">
          Dose on station runs many times higher than on the ground. Days with more South Atlantic Anomaly passes read higher.
          {data && days.length > 0 && ` Measured on the ISS, ${measured(data)}.`}
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
        <h2 className="h2" style={{ marginBottom: 12 }}>Daily dose, fourteen days</h2>
        {days.length === 0 ? (
          <div style={{ height: 160, borderBottom: "1px solid var(--color-text)", display: "grid", placeItems: "center" }}>
            <span className="mute" style={{ fontSize: 13 }}>{err ? `Could not load: ${err}` : "No readings in this period."}</span>
          </div>
        ) : (
          <>
            <div
              role="img"
              aria-label={`Daily absorbed dose for ${days.length} days, from ${Math.min(...days.map((d) => d.total)).toFixed(2)} to ${max.toFixed(2)} mGy per day`}
              style={{ height: 160, borderBottom: "1px solid var(--color-text)", display: "flex", alignItems: "flex-end", gap: 6 }}
            >
              {days.map((d) => {
                const gcr = d.gcr ?? 0;
                return (
                  <div
                    key={d.day}
                    title={`${dayMonth(d.day)} 2019 · ${d.total.toFixed(3)} mGy · cosmic rays ${gcr.toFixed(3)}, South Atlantic Anomaly ${(d.saa ?? 0).toFixed(3)}`}
                    style={{ flex: 1, minWidth: 4 }}
                  >
                    <div style={{ height: (Math.max(0, d.total - gcr) / max) * CHART_PX, background: "var(--color-accent)" }} />
                    <div style={{ height: (gcr / max) * CHART_PX, background: "var(--mute)", opacity: 0.55 }} />
                  </div>
                );
              })}
            </div>
            <div className="axis">
              <span>{dayMonth(days[0].day)}</span>
              <span>{dayMonth(days[Math.floor(days.length / 2)].day)}</span>
              <span>{dayMonth(days[days.length - 1].day)}</span>
            </div>
          </>
        )}
        <p className="foot-note" style={{ marginTop: 10 }}>
          mGy per day · absorbed dose · upper part of each bar: South Atlantic Anomaly passes; lower part: galactic cosmic rays.
          {data && days.length > 0 && ` Source: ${data.source}. These are recorded values, not a live reading.`}
        </p>
      </div>
    </section>
  );
}
