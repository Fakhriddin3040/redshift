"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { Loading } from "./Loading";
import { MetricChart } from "./MetricChart";
import { api } from "@/lib/api";
import { useI18n, type Dict } from "@/i18n";
import { fmt, fmtRange, fmtUnit, hhmm, isVital, levelColor, levelName, shortDay } from "@/lib/format";
import { useVigil } from "@/lib/store";
import type { MetricKey, MetricResponse, RangeKey } from "@/lib/types";

const RANGES: RangeKey[] = ["1h", "24h", "7d"];
function headline(d: MetricResponse, baselineDay: number, of: number, sinceMin: number | null, t: Dict): string {
  const m = d.m;
  const v = d.now.value;
  const name = t.metric[m].lower;
  const p = t.metricPage;
  if (d.now.state === "not_measured") return p.notMeasured(t.metric[m].label);
  if (v == null) return p.noReading(name);
  if (m === "ppco2") return p.co2(fmtUnit(v, m, t), v > 3);
  if (!isVital(m)) return p.cabin(fmtUnit(v, m, t));
  if (d.now.state === "exercising") return p.exercising(fmtUnit(v, m, t));
  if (!d.now.usual) return p.learning(name, baselineDay, of);
  if (!d.now.diff) return p.within(fmtUnit(v, m, t));
  return p.outside(fmtUnit(v, m, t), d.now.diff < 0 ? "below" : "above", sinceMin);
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
  const { t } = useI18n();
  const p = t.metricPage;
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
  const unit = t.metric[m].unit;

  return (
    <section className="page">
      <div>
        <div className="crumbs">
          <Link href="/">{t.nav.today}</Link> / {t.metric[m].label}
        </div>
        <h1 className="h1">
          {data ? headline(data, today.baseline.day, today.baseline.of, incMetric?.since_min ?? null, t) : t.metric[m].label}
        </h1>
        <p className="lede">
          {data?.now.ctx ? t.ctx[data.now.ctx] : "—"}
          {isVital(m) ? p.vitalLede : p.cabinLede}
        </p>
      </div>

      <div ref={ref}>
        <div className="block-head">
          <h2 className="h2">{t.metric[m].label}, {unit}</h2>
          <div className="seg" role="group" aria-label={p.period}>
            {RANGES.map((r) => (
              <button key={r} aria-pressed={range === r} onClick={() => setRange(r)}>{p.ranges[r]}</button>
            ))}
          </div>
        </div>
        {err && !data && <p className="mute">{err === "no data for this crew member yet" ? p.noReadings : err}</p>}
        {data && <MetricChart data={data} width={width} />}
      </div>

      {data && (
        <div className="cols">
          <div>
            <h2 className="h2" style={{ marginBottom: 4 }}>{p.now}</h2>
            {[
              [p.current, fmtUnit(data.now.value, m, t)],
              ...(isVital(m) ? [[p.usualNow, data.now.usual ? `${fmtRange(data.now.usual, m)} ${unit}` : p.stillLearning]] : []),
              ...(isVital(m)
                ? [[p.difference, data.now.diff == null ? "—" : data.now.diff === 0 ? p.withinRange : p.diff(`${fmt(Math.abs(data.now.diff), m)} ${unit}`, data.now.diff < 0)]]
                : data.limits.length
                  ? [[p.limit, `${data.limits[0].value} ${unit}`]]
                  : []),
              [p.context, data.now.ctx ? t.ctx[data.now.ctx] : "—"],
              [p.signal, data.now.signal ? t.signal[data.now.signal] : "—"],
            ].map(([k, v]) => (
              <div key={k} className="record-row">
                <span className="k">{k}</span>
                <span className="v">{v}</span>
              </div>
            ))}
          </div>
          <div>
            <h2 className="h2" style={{ marginBottom: 4 }}>{p.events}</h2>
            {data.events.length === 0 && <div className="empty">{p.noDeviations}</div>}
            {[...data.events].reverse().map((e) => {
              const dur = Math.max(1, Math.round(((e.ts_end ?? data.now_ts) - e.ts_start) / 60));
              return (
                <div key={e.id} className="record-row">
                  <span className="k num">{data.range === "7d" ? `${shortDay(e.ts_start, t)} ` : ""}{hhmm(e.ts_start)}</span>
                  <span className="v">
                    <span style={{ color: levelColor(e.level), fontSize: 12, marginRight: 8 }}>{levelName(e.level, t)}</span>
                    {e.pattern ? t.pattern[e.pattern] ?? e.pattern : t.metric[m].label}
                  </span>
                  <span className="n">
                    {e.ts_end ? t.minutes(dur) : p.ongoing(t.minutes(dur))} · {e.ack ? p.acked : p.notAcked}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      <p className="foot-note">
        {isVital(m) ? p.vitalFoot : p.cabinFoot}
      </p>
    </section>
  );
}
