import type { Alert, Card, CardState, Ctx, Level, MetricKey, Today } from "./types";

export const LEVEL_NAMES = ["Usual", "Watch", "Alert", "Critical"] as const;
export const levelName = (l: Level | null | undefined) => (l == null ? "—" : LEVEL_NAMES[l]);

/** Color for a level word / number. Usual stays mute (labels) or vital (numbers). */
export function levelColor(l: Level | null | undefined, usual = "var(--mute)"): string {
  if (l === 1) return "var(--kick)";
  if (l === 2 || l === 3) return "var(--attn)";
  return usual;
}

export const METRIC: Record<MetricKey, { label: string; lower: string; unit: string; digits: number }> = {
  hr: { label: "Heart rate", lower: "heart rate", unit: "bpm", digits: 0 },
  spo2: { label: "Blood oxygen", lower: "blood oxygen", unit: "%", digits: 0 },
  rr: { label: "Respiration", lower: "respiration", unit: "br/min", digits: 0 },
  skin_t: { label: "Skin temperature", lower: "skin temperature", unit: "°C", digits: 1 },
  ppco2: { label: "CO₂", lower: "cabin CO₂", unit: "mmHg", digits: 1 },
  press: { label: "Pressure", lower: "cabin pressure", unit: "hPa", digits: 0 },
  amb_t: { label: "Temperature", lower: "cabin temperature", unit: "°C", digits: 1 },
};

export const METRIC_KEYS = Object.keys(METRIC) as MetricKey[];
export const isMetricKey = (s: string): s is MetricKey => s in METRIC;
export const isVital = (m: MetricKey) => m === "hr" || m === "spo2" || m === "rr" || m === "skin_t";

/** "93 %" is used in prose, "93" in the big number. */
export function fmt(v: number | null | undefined, m: MetricKey): string {
  if (v == null) return "—";
  return v.toFixed(METRIC[m].digits);
}
export function fmtUnit(v: number | null | undefined, m: MetricKey): string {
  if (v == null) return "—";
  const u = METRIC[m].unit;
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

export const PATTERN_LABEL: Record<string, string> = {
  hypoxia: "Low blood oxygen",
  tachycardia_rest: "Fast heart rate at rest",
  bradycardia: "Slow heart rate",
  fever_like: "Rising skin temperature",
  hypercapnia: "Response to high cabin CO₂",
  depressurization: "Cabin pressure drop",
  sensor_artifact: "Unreliable sensor reading",
};

export const CTX_LABEL: Record<Ctx, string> = {
  off: "Not worn",
  sleep: "Asleep",
  rest: "Resting",
  active: "Exercising",
};
export const ctxWord = (c: Ctx | null | undefined) =>
  c === "sleep" ? "asleep" : c === "active" ? "exercising" : c === "off" ? "not worn" : "resting";

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
export function longDate(ts: number | null | undefined): string {
  if (ts == null) return "";
  return new Date(ts * 1000).toLocaleDateString("en-GB", {
    weekday: "long", day: "numeric", month: "long", year: "numeric", timeZone: "UTC",
  });
}
export function shortDay(ts: number): string {
  return new Date(ts * 1000).toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });
}
export function minutes(n: number): string {
  if (n < 60) return `${n} min`;
  const h = Math.floor(n / 60);
  const m = n % 60;
  return m ? `${h} h ${pad(m)} m` : `${h} h`;
}
export function minutesWord(n: number): string {
  if (n <= 1) return "1 minute";
  if (n < 60) return `${n} minutes`;
  return minutes(n);
}
export function greeting(ts: number | null | undefined): string {
  if (ts == null) return "Hello";
  const h = new Date(ts * 1000).getUTCHours();
  return h < 5 ? "Good night" : h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
}

/** Status word + color + number color for a card state (§5.3). */
export function cardLook(c: Card): { status: string; statusColor: string; numColor: string } {
  const s: CardState = c.state;
  switch (s) {
    case "watch":
      return { status: "Watch", statusColor: "var(--kick)", numColor: "var(--kick)" };
    case "alert":
      return { status: "Alert", statusColor: "var(--attn)", numColor: "var(--attn)" };
    case "critical":
      return { status: "Critical", statusColor: "var(--attn)", numColor: "var(--attn)" };
    case "exercising":
      return { status: "Exercise", statusColor: "var(--mute)", numColor: "var(--vital)" };
    case "no_data":
      return { status: "Sensor off", statusColor: "var(--mute)", numColor: "var(--mute)" };
    case "not_measured":
      return { status: "", statusColor: "var(--mute)", numColor: "var(--mute)" };
    case "learning":
      return { status: "", statusColor: "var(--mute)", numColor: "var(--vital)" };
    default:
      return { status: "Usual", statusColor: "var(--mute)", numColor: "var(--vital)" };
  }
}

/** Left part of the card's bottom line (§5.3). */
export function cardNote(c: Card, today: Pick<Today, "baseline">): string {
  if (c.state === "not_measured") return "Not measured by this device";
  if (c.state === "no_data") return c.since_ts ? `No data since ${hhmm(c.since_ts)}` : "No data";
  if (c.m === "ppco2") return `Limit ${(c.limit ?? 3).toFixed(1)} mmHg`;
  if (c.m === "press") return pressureTrend(c.spark);
  if (c.m === "amb_t") return "Cabin air";
  if (c.state === "exercising") return "Not compared during exercise";
  if (c.learning || !c.usual) return `Learning · day ${today.baseline.day} of ${today.baseline.of}`;
  return `Your usual ${fmtRange(c.usual, c.m)}`;
}

function pressureTrend(spark: (number | null)[]): string {
  const vals = spark.filter((v): v is number => v != null);
  if (vals.length < 10) return "Stable";
  const recent = vals.slice(-5).reduce((a, b) => a + b, 0) / 5;
  const earlier = vals.slice(0, 5).reduce((a, b) => a + b, 0) / 5;
  return recent - earlier < -2 ? "Falling" : "Stable";
}

export function isIncident(a: Alert) {
  return a.key === "incident";
}
