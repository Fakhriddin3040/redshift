"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { Loading } from "./Loading";
import { MetricChart } from "./MetricChart";
import { api } from "@/lib/api";
import { CTX_LABEL, METRIC, PATTERN_LABEL, fmt, fmtRange, fmtUnit, hhmm, isVital, levelColor, levelName, minutes, shortDay } from "@/lib/format";
import { useVigil } from "@/lib/store";
import type { MetricKey, MetricResponse, RangeKey } from "@/lib/types";

const RANGES: RangeKey[] = ["1h", "24h", "7d"];
const RANGE_LABEL: Record<RangeKey, string> = { "1h": "1 h", "24h": "24 h", "7d": "7 d" };

function headline(d: MetricResponse, baselineDay: number, of: number, sinceMin: number | null): string {
  const m = d.m;
  const v = d.now.value;
  const name = METRIC[m].lower;
  if (d.now.state === "not_measured") return `${METRIC[m].label} is not measured by this device.`;
  if (v == null) return `No ${name} reading right now.`;
  if (m === "ppco2") return `${fmtUnit(v, m)}, ${v > 3 ? "above" : "under"} the 3.0 mmHg limit.`;
  if (!isVital(m)) return `${fmtUnit(v, m)} in the cabin.`;
  if (d.now.state === "exercising") return `${fmtUnit(v, m)}, not compared during exercise.`;
  if (!d.now.usual) return `Still learning your usual ${name} — day ${baselineDay} of ${of}.`;
  if (!d.now.diff) return `${fmtUnit(v, m)}, within your usual range.`;
  const dir = d.now.diff < 0 ? "below" : "above";
  return `${fmtUnit(v, m)}, ${dir} your usual range${sinceMin ? ` for ${sinceMin} minutes` : ""}.`;
}

function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [w, setW] = useState(800);
  useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver(([e]) => setW(Math.round(e.contentRect.width)));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  return [ref, w] as const;
}

export function MetricView({ m }: { m: MetricKey }) {
  const { crewId, today } = useVigil();
  const [range, setRange] = useState<RangeKey>("1h");
  const [data, setData] = useState<MetricResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [ref, width] = useWidth<HTMLDivElement>();

  const load = useCallback(async () => {
    try {
      setData(await api.metric(crewId, m, range));
      setErr(null);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }, [crewId, m, range]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- async fetch, state is set after await
    void load();
    const id = setInterval(load, range === "1h" ? 15_000 : 60_000);
    return () => clearInterval(id);
  }, [load, range]);

  if (!today) return <Loading />;

  const inc = today.notices.find((n) => n.key === "incident");
  const incMetric = inc?.metrics.find((x) => x.m === m);
  const unit = METRIC[m].unit;

  return (
    <section className="page">
      <div>
        <div className="crumbs">
          <Link href="/">Today</Link> / {METRIC[m].label}
        </div>
        <h1 className="h1">
          {data ? headline(data, today.baseline.day, today.baseline.of, incMetric?.since_min ?? null) : METRIC[m].label}
        </h1>
        <p className="lede">
          {data?.now.ctx ? CTX_LABEL[data.now.ctx] : "—"}
          {isVital(m) ? " · compared with your own readings at this time of day" : " · cabin air, same for the whole crew"}
        </p>
      </div>

      <div ref={ref}>
        <div className="block-head">
          <h2 className="h2">{METRIC[m].label}, {unit}</h2>
          <div className="seg" role="group" aria-label="Period">
            {RANGES.map((r) => (
              <button key={r} aria-pressed={range === r} onClick={() => setRange(r)}>{RANGE_LABEL[r]}</button>
            ))}
          </div>
        </div>
        {err && !data && <p className="mute">{err === "no data for this crew member yet" ? "No readings in this period." : err}</p>}
        {data && <MetricChart data={data} width={width} />}
      </div>

      {data && (
        <div className="cols">
          <div>
            <h2 className="h2" style={{ marginBottom: 4 }}>Now</h2>
            {[
              ["Current", fmtUnit(data.now.value, m)],
              ...(isVital(m) ? [["Your usual now", data.now.usual ? `${fmtRange(data.now.usual, m)} ${unit}` : "Still learning"]] : []),
              ...(isVital(m)
                ? [["Difference", data.now.diff == null ? "—" : data.now.diff === 0 ? "Within range" : `${fmt(Math.abs(data.now.diff), m)} ${unit} ${data.now.diff < 0 ? "below" : "above"}`]]
                : data.limits.length
                  ? [["Limit", `${data.limits[0].value} ${unit}`]]
                  : []),
              ["Context", data.now.ctx ? CTX_LABEL[data.now.ctx] : "—"],
              ["Signal", data.now.signal ? data.now.signal[0].toUpperCase() + data.now.signal.slice(1) : "—"],
            ].map(([k, v]) => (
              <div key={k} className="record-row">
                <span className="k">{k}</span>
                <span className="v">{v}</span>
              </div>
            ))}
          </div>
          <div>
            <h2 className="h2" style={{ marginBottom: 4 }}>Events</h2>
            {data.events.length === 0 && <div className="empty">No deviations in this period.</div>}
            {[...data.events].reverse().map((e) => {
              const dur = Math.max(1, Math.round(((e.ts_end ?? data.now_ts) - e.ts_start) / 60));
              return (
                <div key={e.id} className="record-row">
                  <span className="k num">{data.range === "7d" ? `${shortDay(e.ts_start)} ` : ""}{hhmm(e.ts_start)}</span>
                  <span className="v">
                    <span style={{ color: levelColor(e.level), fontSize: 12, marginRight: 8 }}>{levelName(e.level)}</span>
                    {e.pattern ? PATTERN_LABEL[e.pattern] ?? e.pattern : METRIC[m].label}
                  </span>
                  <span className="n">
                    {e.ts_end ? minutes(dur) : `ongoing · ${minutes(dur)}`} · {e.ack ? "acknowledged" : "not acknowledged"}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      <p className="foot-note">
        {isVital(m)
          ? "Your usual range is learned from the last 14 days of your own readings, separately for sleep, rest and time of day. Readings taken during an alert are not learned."
          : "Cabin limits are fixed and the same for everyone aboard."}
      </p>
    </section>
  );
}
