// Shapes of the Vigil backend API (/api/v1). All times are unix seconds; null = no data.

export type MetricKey = "hr" | "spo2" | "rr" | "skin_t" | "ppco2" | "press" | "amb_t";
export type VitalKey = "hr" | "spo2" | "rr" | "skin_t";
export type Level = 0 | 1 | 2 | 3;
export type Ctx = "off" | "sleep" | "rest" | "active";
export type Signal = "good" | "fair" | "poor";

export type CardState =
  | "not_measured"
  | "no_data"
  | "usual"
  | "watch"
  | "alert"
  | "critical"
  | "exercising"
  | "learning";

export interface Card {
  m: MetricKey;
  value: number | null;
  unit: string;
  state: CardState;
  since_ts?: number | null;
  learning?: boolean;
  usual?: [number, number] | null;
  band?: [number, number] | null;
  limit: number | null;
  spark: (number | null)[];
}

export interface Baseline {
  state: "learning" | "learned";
  day: number;
  of: number;
  ready_pct?: number;
}

export interface DeviceBrief {
  link: "connected" | "no_link";
  worn: boolean | null;
  signal: Signal | null;
  batt: number | null;
}

export interface AlertMetric {
  m: MetricKey;
  value: number | null;
  usual: [number, number] | null;
  z: number | null;
  trend: "rising" | "falling" | "stable" | null;
  since_min: number;
}

export interface AlertText {
  what?: string;
  why?: string;
  action?: string | string[];
  [k: string]: unknown;
}

export interface Alert {
  id: number;
  crew: number;
  key: string; // "incident" | "baseline_learned" | "checkin:YYYY-MM-DD"
  source: "hard" | "env" | "baseline" | "system";
  level: Level;
  peak_level: Level;
  ts_start: number;
  ts_end: number | null;
  since_min: number;
  pattern: string | null;
  p: number | null;
  ctx: Ctx | null;
  primary: MetricKey | null;
  metrics: AlertMetric[];
  text: AlertText | null;
  text_src: string | null;
  ack_ts: number | null;
}

export interface Today {
  now_ts: number | null;
  flight_day: number | null;
  level: Level;
  critical_acked: boolean;
  ctx: Ctx | null;
  baseline: Baseline;
  device: DeviceBrief;
  vitals: Card[];
  cabin: Card[];
  record: { checkin: unknown; sleep: unknown; radiation: unknown; report: unknown };
  notices: Alert[];
}

export interface CrewItem {
  id: number;
  now_ts: number | null;
  name: string;
  role: string;
  level: Level | null;
  topic: string | null;
  baseline: Baseline;
  checkin_ts: number | "not_shared" | null;
  sleep_7n_mean_min: number | "not_shared" | null;
  data_today_pct: number | null;
}

export type RangeKey = "1h" | "24h" | "7d";
/** [ts, value, lo, hi, ctx(0 off,1 sleep,2 rest,3 active)] */
export type Point = [number, number | null, number | null, number | null, number];

export interface MetricLimit {
  value: number;
  kind: "critical_above" | "critical_below" | "watch_above";
}

export interface MetricEvent {
  id: number;
  ts_start: number;
  ts_end: number | null;
  level: Level;
  pattern: string | null;
  ack: boolean;
}

export interface MetricResponse {
  m: MetricKey;
  unit: string;
  range: RangeKey;
  step_s: number;
  now_ts: number;
  now: {
    value: number | null;
    usual: [number, number] | null;
    diff: number | null;
    ctx: Ctx | null;
    signal: Signal | null;
    state: CardState;
  };
  points: Point[];
  limits: MetricLimit[];
  events: MetricEvent[];
}

export type LiveMessage =
  | {
      t: "tick";
      ts: number;
      ctx: Ctx | null;
      level: Level;
      v: Partial<Record<MetricKey, number | null>>;
      sqi: number;
      worn: boolean;
    }
  | { t: "alert"; alert: Alert }
  | { t: "level"; level: Level; critical_acked: boolean }
  | { t: "baseline"; state: Baseline["state"]; day: number; of: number };
