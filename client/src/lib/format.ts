import type { Dict } from "@/i18n";
import type { Alert, Card, CardState, Ctx, Level, MetricKey, Today } from "./types";

export const levelName = (l: Level | null | undefined, t: Dict) => (l == null ? "—" : t.levels[l]);

/** Color for a level word / number. Usual stays mute (labels) or vital (numbers). */
export function levelColor(l: Level | null | undefined, usual = "var(--mute)"): string {
  if (l === 1) return "var(--kick)";
  if (l === 2 || l === 3) return "var(--attn)";
  return usual;
}

/** Numeric format only; names and units are in the dictionary (`t.metric`). */
export const METRIC: Record<MetricKey, { digits: number }> = {
  hr: { digits: 0 },
  spo2: { digits: 0 },
  rr: { digits: 0 },
  skin_t: { digits: 1 },
  ppco2: { digits: 1 },
  press: { digits: 0 },
  amb_t: { digits: 1 },
};

export const METRIC_KEYS = Object.keys(METRIC) as MetricKey[];
export const isMetricKey = (s: string): s is MetricKey => s in METRIC;
export const isVital = (m: MetricKey) => m === "hr" || m === "spo2" || m === "rr" || m === "skin_t";

/** "93 %" is used in prose, "93" in the big number. */
export function fmt(v: number | null | undefined, m: MetricKey): string {
  if (v == null) return "—";
  return v.toFixed(METRIC[m].digits);
}
export function fmtUnit(v: number | null | undefined, m: MetricKey, t: Dict): string {
  if (v == null) return "—";
  const u = t.metric[m].unit;
  return `${fmt(v, m)}${u === "%" ? " %" : ` ${u}`}`;
}
/** Range bounds keep one extra decimal when rounding would shift them visibly (95.5 stays 95.5, 55.9 → 56). */
export function fmtRange(r: [number, number] | null | undefined, m: MetricKey): string {
  if (!r) return "—";
  const d = METRIC[m].digits;
  const f = 10 ** d;
  const b = (v: number) => (Math.abs(v * f - Math.round(v * f)) > 0.15 ? v.toFixed(d + 1) : v.toFixed(d));
  return `${b(r[0])}–${b(r[1])}`;
}

export const ctxWord = (c: Ctx | null | undefined, t: Dict) => t.ctxWord[c ?? "rest"];

const pad = (n: number) => String(n).padStart(2, "0");

/** HH:MM in GMT (the station clock). */
export function hhmm(ts: number | null | undefined): string {
  if (ts == null) return "—";
  const d = new Date(ts * 1000);
  return `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`;
}
export function hhmmss(ts: number | null | undefined): string {
  if (ts == null) return "—";
  const d = new Date(ts * 1000);
  return `${hhmm(ts)}:${pad(d.getUTCSeconds())}`;
}
export function longDate(ts: number | null | undefined, t: Dict): string {
  if (ts == null) return "";
  return new Date(ts * 1000).toLocaleDateString(t.intl, {
    weekday: "long", day: "numeric", month: "long", year: "numeric", timeZone: "UTC",
  });
}
export function shortDay(ts: number, t: Dict): string {
  return new Date(ts * 1000).toLocaleDateString(t.intl, { day: "numeric", month: "short", timeZone: "UTC" });
}
export function greeting(ts: number | null | undefined, t: Dict): string {
  return t.greeting(ts == null ? null : new Date(ts * 1000).getUTCHours());
}

/** Status word + color + number color for a card state (§5.3). */
export function cardLook(c: Card, t: Dict): { status: string; statusColor: string; numColor: string } {
  const s: CardState = c.state;
  const status = t.card.status[s] ?? (s === "not_measured" || s === "learning" ? "" : t.card.status.usual!);
  switch (s) {
    case "watch":
      return { status, statusColor: "var(--kick)", numColor: "var(--kick)" };
    case "alert":
    case "critical":
      return { status, statusColor: "var(--attn)", numColor: "var(--attn)" };
    case "exercising":
      return { status, statusColor: "var(--mute)", numColor: "var(--vital)" };
    case "no_data":
    case "not_measured":
      return { status, statusColor: "var(--mute)", numColor: "var(--mute)" };
    default:
      return { status, statusColor: "var(--mute)", numColor: "var(--vital)" };
  }
}

/** Left part of the card's bottom line (§5.3). */
export function cardNote(c: Card, today: Pick<Today, "baseline">, t: Dict): string {
  if (c.state === "not_measured") return t.card.notMeasured;
  if (c.state === "no_data") return c.since_ts ? t.card.noDataSince(hhmm(c.since_ts)) : t.card.noData;
  if (c.m === "ppco2") return t.card.limit((c.limit ?? 3).toFixed(1));
  if (c.m === "press") return pressureTrend(c.spark) ? t.card.falling : t.card.stable;
  if (c.m === "amb_t") return t.card.cabinAir;
  if (c.state === "exercising") return t.card.notCompared;
  if (c.learning || !c.usual) return t.card.learning(today.baseline.day, today.baseline.of);
  return t.card.usual(fmtRange(c.usual, c.m));
}

/** True when cabin pressure is falling. */
function pressureTrend(spark: (number | null)[]): boolean {
  const vals = spark.filter((v): v is number => v != null);
  if (vals.length < 10) return false;
  const recent = vals.slice(-5).reduce((a, b) => a + b, 0) / 5;
  const earlier = vals.slice(0, 5).reduce((a, b) => a + b, 0) / 5;
  return recent - earlier < -2;
}

export function isIncident(a: Alert) {
  return a.key === "incident";
}
