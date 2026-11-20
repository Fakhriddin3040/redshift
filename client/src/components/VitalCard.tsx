"use client";

import Link from "next/link";
import { useI18n } from "@/i18n";
import { METRIC, cardLook, cardNote, fmt } from "@/lib/format";
import type { Card, Today } from "@/lib/types";

const W = 120;
const H = 30;

/** Path with real gaps: a null breaks the line (§6.2 "разрыв линии"). */
export function gappedPath(vals: (number | null)[], x: (i: number) => number, y: (v: number) => number): string {
  let d = "";
  let pen = false;
  vals.forEach((v, i) => {
    if (v == null) {
      pen = false;
      return;
    }
    d += `${pen ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`;
    pen = true;
  });
  return d;
}

function Spark({ card, color }: { card: Card; color: string }) {
  if (card.state === "not_measured") return <svg className="spark" aria-hidden />;
  const vals = card.spark;
  const band = card.state === "exercising" ? null : card.band ?? null;
  const showLimit = card.limit != null && (card.state === "learning" || card.state === "alert" || card.state === "critical" || card.m === "ppco2");
  const nums = vals.filter((v): v is number => v != null);
  const pool = [...nums, ...(band ?? []), ...(showLimit ? [card.limit!] : [])];
  if (!nums.length) return <svg className="spark" aria-hidden />;
  let lo = Math.min(...pool);
  let hi = Math.max(...pool);
  const pad = Math.max((hi - lo) * 0.15, METRIC[card.m].digits ? 0.1 : 1);
  lo -= pad;
  hi += pad;
  const y = (v: number) => H - 1 - ((v - lo) / (hi - lo)) * (H - 2);
  const x = (i: number) => (i * W) / Math.max(1, vals.length - 1);

  return (
    <svg className="spark" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" aria-hidden>
      {band && (
        <rect x={0} width={W} y={y(band[1])} height={Math.max(1, y(band[0]) - y(band[1]))} fill="var(--color-text)" opacity={0.08} />
      )}
      {showLimit && (
        <line x1={0} x2={W} y1={y(card.limit!)} y2={y(card.limit!)} stroke="var(--attn)" strokeDasharray="3 3" strokeWidth={1} vectorEffect="non-scaling-stroke" opacity={0.8} />
      )}
      <path d={gappedPath(vals, x, y)} fill="none" stroke={color} strokeWidth={1.4} vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
    </svg>
  );
}

export function VitalCard({ card, today }: { card: Card; today: Today }) {
  const { t } = useI18n();
  const look = cardLook(card, t);
  const unit = t.metric[card.m].unit;
  const stroke = look.numColor === "var(--mute)" ? "var(--mute)" : look.numColor;
  return (
    <Link href={`/metric/${card.m}`} className="vcard">
      <span className="label">{t.metric[card.m].label}</span>
      <div className="val">
        <span className="big" style={{ color: look.numColor }}>{fmt(card.value, card.m)}</span>
        <span className="unit">{unit}</span>
      </div>
      <Spark card={card} color={stroke} />
      <div className="bottom">
        <span className="mute">{cardNote(card, today, t)}</span>
        <span style={{ color: look.statusColor }}>{look.status}</span>
      </div>
    </Link>
  );
}
