"use client";

// Nights come from GET /crew/{id}/sleep: minutes the context rule classified as
// sleep, grouped into nights. The evening advice is static guidance.

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { hhmm, minutes, shortDay } from "@/lib/format";
import { useVigil } from "@/lib/store";
import type { Night, SleepResponse } from "@/lib/types";

const TONIGHT = [
  ["16:00", "Finish exercise. Late sessions push sleep onset back."],
  ["20:00", "Switch crew-quarters lighting to the warm pre-sleep setting."],
  ["21:00", "Screens off, window shades closed."],
  ["06:00", "Bright, blue-enriched light for the first hour awake."],
];

// The band shows 18:00 → 10:00 GMT, sixteen hours.
const BAND_START_H = 18;
const BAND_HOURS = 16;

function bandPos(n: Night): { left: string; width: string } {
  const hours = (ts: number) => {
    const d = new Date(ts * 1000);
    const h = d.getUTCHours() + d.getUTCMinutes() / 60;
    return (h - BAND_START_H + 24) % 24;
  };
  const a = Math.min(BAND_HOURS, hours(n.onset_ts));
  const b = Math.min(BAND_HOURS, Math.max(a, a + (n.wake_ts - n.onset_ts) / 3600));
  return { left: `${(a / BAND_HOURS) * 100}%`, width: `${((b - a) / BAND_HOURS) * 100}%` };
}

export default function SleepPage() {
  const { crewId } = useVigil();
  // Keep the crew the answer belongs to, so another person's nights are never shown.
  const [loaded, setLoaded] = useState<{ crew: number; data: SleepResponse } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const data = loaded && loaded.crew === crewId ? loaded.data : null;

  useEffect(() => {
    let live = true;
    const load = () =>
      api.sleep(crewId)
        .then((d) => { if (live) { setLoaded({ crew: crewId, data: d }); setErr(null); } })
        .catch((e) => { if (live) setErr(String(e.message ?? e)); });
    load();
    const id = setInterval(load, 60_000);
    return () => { live = false; clearInterval(id); };
  }, [crewId]);

  const nights = data?.nights ?? [];
  const last = nights.length ? nights[nights.length - 1] : null;
  const longest = Math.max(1, ...nights.map((n) => n.asleep_min));
  const title = !data
    ? err ? "Sleep data is not available." : "Loading…"
    : !data.shared ? "Sleep is not shared."
    : last ? `${minutes(last.asleep_min)} asleep last night.`
    : "No nights recorded yet.";

  return (
    <section className="page">
      <div>
        <div className="eyebrow">Sleep and circadian rhythm</div>
        <h1 className="h1">{title}</h1>
        <p className="lede">
          With sixteen sunrises a day, cabin light is the main cue your body gets.
          {last
            ? ` Asleep from ${hhmm(last.onset_ts)} to ${hhmm(last.wake_ts)} GMT, estimated from wrist motion and heart rate.`
            : " Once the wristband has recorded a night, it is shown here against the schedule."}
          {data?.asleep_now ? " The current night is still in progress and is not counted yet." : ""}
        </p>
      </div>
      <div>
        <h2 className="h2" style={{ marginBottom: 12 }}>Last night against the schedule</h2>
        {last ? (
          <div className="dayband" role="img" aria-label={`Asleep from ${hhmm(last.onset_ts)} to ${hhmm(last.wake_ts)} GMT`}>
            <i style={bandPos(last)} />
          </div>
        ) : (
          <div className="dayband" style={{ height: 64, display: "grid", placeItems: "center" }}>
            <span className="mute" style={{ fontSize: 13 }}>No nights recorded yet.</span>
          </div>
        )}
        <div className="axis"><span>18:00</span><span>22:00</span><span>02:00</span><span>06:00</span><span>10:00</span></div>
      </div>
      <div className="cols">
        <div>
          <h2 className="h2" style={{ marginBottom: 12 }}>
            Seven nights{data?.mean_7n_min != null ? ` · mean ${minutes(data.mean_7n_min)}` : ""}
          </h2>
          {nights.length === 0 ? (
            <div className="empty mute">No nights recorded yet.</div>
          ) : (
            [...nights].reverse().map((n) => (
              <div key={n.onset_ts} style={{ borderTop: "1px solid var(--color-divider)", padding: "10px 0", display: "grid", gridTemplateColumns: "56px 1fr 176px", gap: 12, alignItems: "center" }}>
                <span className="mute" style={{ fontSize: 13 }}>{shortDay(n.wake_ts)}</span>
                <span style={{ height: 8, background: "var(--color-divider)", display: "block" }}>
                  <span style={{ display: "block", height: "100%", width: `${(n.asleep_min / longest) * 100}%`, background: "var(--color-accent)" }} />
                </span>
                <span className="num" style={{ textAlign: "right", fontSize: 13 }}>
                  {minutes(n.asleep_min)}
                  <span className="mute"> · {hhmm(n.onset_ts)}–{hhmm(n.wake_ts)}</span>
                </span>
              </div>
            ))
          )}
        </div>
        <div>
          <h2 className="h2" style={{ marginBottom: 4 }}>For tonight</h2>
          {TONIGHT.map(([t, s]) => (
            <div key={t} style={{ borderTop: "1px solid var(--color-divider)", padding: "12px 0", display: "flex", gap: 16, alignItems: "baseline" }}>
              <span className="num kick" style={{ width: 52, flex: "none" }}>{t}</span>
              <span>{s}</span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
