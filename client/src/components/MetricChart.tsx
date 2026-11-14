"use client";

import { useMemo, useRef, useState } from "react";
import { METRIC, fmt, fmtRange, hhmm, shortDay } from "@/lib/format";
import type { MetricResponse } from "@/lib/types";
import { gappedPath } from "./VitalCard";

const H = 280;
const RIBBON = 8;
const PAD = { l: 44, r: 12, t: 14, b: 22 };

const CTX_FILL = ["transparent", "var(--ctx-sleep)", "var(--ctx-rest)", "var(--ctx-active)"];

function limitLabel(kind: string, value: number, unit: string): string {
  if (kind === "watch_above") return `Limit ${value} ${unit}`;
  const u = unit === "%" ? " %" : ` ${unit}`;
  return kind === "critical_below" ? `Critical at ${value}${u} or below` : `Critical at ${value}${u} or above`;
}

export function MetricChart({ data, width }: { data: MetricResponse; width: number }) {
  const [hover, setHover] = useState<number | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const m = data.m;
  const pts = data.points;
  const W = Math.max(320, width);
  const plotW = W - PAD.l - PAD.r;
  const plotH = H - PAD.t - PAD.b;

  const scale = useMemo(() => {
    const vals: number[] = [];
    for (const p of pts) {
      if (p[1] != null) vals.push(p[1]);
      if (p[2] != null) vals.push(p[2]);
      if (p[3] != null) vals.push(p[3]);
    }
    if (!vals.length) return null;
    let lo = Math.min(...vals);
    let hi = Math.max(...vals);
    // include limits only when they are near the data, so the line keeps its detail
    for (const l of data.limits) {
      const span = Math.max(hi - lo, 1);
      if (l.value >= lo - span && l.value <= hi + span) {
        lo = Math.min(lo, l.value);
        hi = Math.max(hi, l.value);
      }
    }
    const pad = Math.max((hi - lo) * 0.12, METRIC[m].digits ? 0.1 : 1);
    return { lo: lo - pad, hi: hi + pad };
  }, [pts, data.limits, m]);

  const n = pts.length;
  const x = (i: number) => PAD.l + (i * plotW) / Math.max(1, n - 1);
  const y = (v: number) => (scale ? PAD.t + plotH - ((v - scale.lo) / (scale.hi - scale.lo)) * plotH : 0);
  const colW = plotW / Math.max(1, n - 1);

  const ticks = useMemo(() => {
    if (!scale) return [];
    const out: number[] = [];
    for (let i = 0; i < 4; i++) out.push(scale.lo + ((scale.hi - scale.lo) * (i + 0.5)) / 4);
    return out;
  }, [scale]);

  const timeTicks = useMemo(() => {
    const k = 5;
    return Array.from({ length: k }, (_, i) => Math.round((i * (n - 1)) / (k - 1)));
  }, [n]);

  // deviation spans from events
  const spans = data.events.map((e) => {
    const s = (e.ts_start - pts[0][0]) / data.step_s;
    const end = ((e.ts_end ?? data.now_ts) - pts[0][0]) / data.step_s;
    return { ...e, i0: Math.max(0, s), i1: Math.min(n - 1, end) };
  }).filter((e) => e.i1 >= 0 && e.i0 <= n - 1);

  // runs of missing data
  const gaps: [number, number][] = [];
  let g0: number | null = null;
  pts.forEach((p, i) => {
    if (p[1] == null && g0 == null) g0 = i;
    if (p[1] != null && g0 != null) {
      gaps.push([g0, i - 1]);
      g0 = null;
    }
  });
  // the current minute is still open on the server — do not mark it as a gap
  if (g0 != null && g0 < n - 1) gaps.push([g0, n - 1]);

  const onMove = (e: React.MouseEvent) => {
    const r = svgRef.current?.getBoundingClientRect();
    if (!r) return;
    const px = ((e.clientX - r.left) / r.width) * W;
    const i = Math.round(((px - PAD.l) / plotW) * (n - 1));
    setHover(i >= 0 && i < n ? i : null);
  };

  const fmtTime = (ts: number) => (data.range === "7d" ? shortDay(ts) : hhmm(ts));
  const hp = hover != null ? pts[hover] : null;

  return (
    <div className="chart-wrap">
      <svg
        ref={svgRef}
        className="chart"
        viewBox={`0 0 ${W} ${H + RIBBON + 10}`}
        onMouseMove={onMove}
        onMouseLeave={() => setHover(null)}
        role="img"
        aria-label={`${METRIC[m].label}, ${data.range}`}
      >
        <defs>
          <pattern id="hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <line x1="0" y1="0" x2="0" y2="6" stroke="var(--color-text)" strokeWidth="1" opacity="0.12" />
          </pattern>
        </defs>

        {/* deviations */}
        {spans.map((s) => (
          <rect
            key={s.id}
            x={x(s.i0)}
            width={Math.max(2, x(s.i1) - x(s.i0))}
            y={PAD.t}
            height={plotH}
            fill={s.level === 1 ? "var(--kick)" : "var(--attn)"}
            opacity={0.14}
          />
        ))}

        {/* no data */}
        {gaps.map(([a, b]) => (
          <g key={a}>
            <rect x={x(a) - colW / 2} width={Math.max(colW, x(b) - x(a) + colW)} y={PAD.t} height={plotH} fill="url(#hatch)" />
            {b - a >= n * 0.06 && (
              <text x={(x(a) + x(b)) / 2} y={PAD.t + 14} textAnchor="middle">No data</text>
            )}
          </g>
        ))}

        {scale && (
          <>
            {/* personal norm band: per point, with gaps */}
            {pts.map((p, i) => {
              if (p[2] == null || p[3] == null) return null;
              return <rect key={i} x={x(i) - colW / 2} width={colW + 0.5} y={y(p[3])} height={Math.max(1, y(p[2]) - y(p[3]))} fill="var(--color-text)" opacity={0.08} />;
            })}

            {/* limits */}
            {data.limits
              .filter((l) => l.value >= scale.lo && l.value <= scale.hi)
              .map((l) => (
                <g key={l.kind + l.value}>
                  <line x1={PAD.l} x2={W - PAD.r} y1={y(l.value)} y2={y(l.value)} stroke={l.kind === "watch_above" ? "var(--kick)" : "var(--attn)"} strokeDasharray="4 4" />
                  <text x={W - PAD.r} y={y(l.value) - 5} textAnchor="end">{limitLabel(l.kind, l.value, data.unit)}</text>
                </g>
              ))}

            {/* value line */}
            <path d={gappedPath(pts.map((p) => p[1]), x, y)} fill="none" stroke="var(--vital)" strokeWidth={1.5} strokeLinejoin="round" />

            {/* y ticks */}
            {ticks.map((t) => (
              <text key={t} x={PAD.l - 8} y={y(t) + 4} textAnchor="end">{fmt(t, m)}</text>
            ))}
          </>
        )}

        {!scale && (
          <text x={PAD.l + plotW / 2} y={PAD.t + plotH / 2} textAnchor="middle" style={{ fontSize: 14 }}>No readings in this period.</text>
        )}

        {/* base lines */}
        <line x1={PAD.l} x2={PAD.l} y1={PAD.t} y2={PAD.t + plotH} stroke="var(--color-divider)" />
        <line x1={PAD.l} x2={W - PAD.r} y1={PAD.t + plotH} y2={PAD.t + plotH} stroke="var(--color-divider)" />

        {/* time axis */}
        {timeTicks.map((i) => (
          <text key={i} x={x(i)} y={H - 6} textAnchor={i === 0 ? "start" : i === n - 1 ? "end" : "middle"}>{fmtTime(pts[i][0])}</text>
        ))}

        {/* context ribbon */}
        {pts.map((p, i) => (
          <rect key={`c${i}`} x={x(i) - colW / 2} width={colW + 0.5} y={H + 4} height={RIBBON} fill={p[1] == null ? "transparent" : CTX_FILL[p[4]] ?? "transparent"} />
        ))}

        {/* hover */}
        {hover != null && <line x1={x(hover)} x2={x(hover)} y1={PAD.t} y2={PAD.t + plotH} stroke="var(--color-text)" opacity={0.4} />}
        {hp && hp[1] != null && scale && <circle cx={x(hover!)} cy={y(hp[1])} r={3} fill="var(--vital)" />}
      </svg>

      {hp && (
        <div className="chart-tip" style={{ left: `${(x(hover!) / W) * 100}%`, transform: `translateX(${hover! > n / 2 ? "-105%" : "5%"})` }}>
          <div>{data.range === "7d" ? `${shortDay(hp[0])} ${hhmm(hp[0])}` : hhmm(hp[0])}</div>
          <div>{hp[1] == null ? "No data" : `${fmt(hp[1], m)} ${data.unit}`}</div>
          {hp[2] != null && hp[3] != null && <div className="mute">Usual {fmtRange([hp[2], hp[3]], m)}</div>}
        </div>
      )}

      <div className="legend" style={{ marginTop: 6 }}>
        <span><i style={{ background: "var(--ctx-sleep)" }} />Asleep</span>
        <span><i style={{ background: "var(--ctx-rest)" }} />Resting</span>
        <span><i style={{ background: "var(--ctx-active)" }} />Exercise</span>
      </div>
    </div>
  );
}
