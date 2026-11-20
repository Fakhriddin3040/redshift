// Interface copy built from server data (DESIGN_TZ §5.1, §5.4, §7, §12).
// The server's own `text` (what / why / action) wins whenever it is present
// and is written in the UI language (the server writes English only, see `Dict.serverText`).

import type { Dict } from "@/i18n";
import type { Dir } from "@/i18n/en";
import type { Alert, AlertMetric, Card, MetricKey, Today } from "./types";
import { fmtRange, fmtUnit, ctxWord, isVital } from "./format";

export function direction(am: AlertMetric | undefined, card?: Card): "below" | "above" | null {
  if (!am) return null;
  if (am.z != null && am.z !== 0) return am.z < 0 ? "below" : "above";
  const usual = am.usual ?? card?.usual ?? null;
  if (am.value != null && usual) {
    if (am.value < usual[0]) return "below";
    if (am.value > usual[1]) return "above";
  }
  if (am.m === "spo2") return "below";
  if (am.m === "ppco2") return "above";
  if (am.m === "press") return "below";
  return null;
}

function cardOf(today: Today | null, m: MetricKey | null | undefined): Card | undefined {
  if (!today || !m) return undefined;
  return [...today.vitals, ...today.cabin].find((c) => c.m === m);
}

export function incidentOf(today: Today | null): Alert | undefined {
  return today?.notices.find((n) => n.key === "incident");
}

/** The server's text for an alert, when it is in the UI language. */
const serverText = (a: Alert, t: Dict) => (t.serverText ? a.text : null);

/** First sentence under the greeting on Today. */
export function lede(today: Today, t: Dict): string {
  const inc = incidentOf(today);
  const open = today.notices.filter((n) => n.ack_ts == null).length;
  const primary = inc?.primary;
  const what = inc && serverText(inc, t)?.what;
  // The server's sentence describes the incident at its worst and stays true during recovery.
  if (today.level >= 1 && what) {
    return `${String(what)}.${today.level === 3 ? ` ${t.text.followSteps}` : ""}`;
  }
  if (today.level >= 2 && primary) {
    const am = inc!.metrics.find((x) => x.m === primary);
    if (primary === "ppco2") return t.text.ledeCo2High;
    if (primary === "press") return t.text.ledePressDrop;
    const dir: Dir = direction(am, cardOf(today, primary)) ?? "outside";
    if (today.level === 3) return t.text.ledeCritical(t.metric[primary].label, dir);
    return t.text.ledeAlert(t.metric[primary].label, dir);
  }
  if (today.level === 1 && primary) {
    const am = inc!.metrics.find((x) => x.m === primary);
    if (!isVital(primary)) return t.text.ledeWatchCabin(t.metric[primary].label);
    const dir: Dir = direction(am, cardOf(today, primary)) ?? "outside";
    return t.text.ledeWatch(t.metric[primary].label, dir);
  }
  if (today.baseline.state === "learning") {
    return t.text.ledeLearning(today.baseline.day, today.baseline.of);
  }
  if (open === 0) return t.text.ledeAllUsual;
  return t.text.ledeOpen(open);
}

export interface NoticeText {
  label: string;
  title: string;
  body: string;
  action?: { label: string; href: string };
  explained: boolean;
  tone: string; // css color of the label
}

/** "Heart rate is rising at rest" for secondary metrics of an incident. */
function companion(am: AlertMetric, ctx: Alert["ctx"], t: Dict): string {
  const name = t.metric[am.m].lower;
  if (am.trend === "rising" || am.trend === "falling") {
    return t.text.companionTrend(name, am.trend, isVital(am.m) ? ctxWord(ctx, t) : null);
  }
  return t.text.companionValue(name, fmtUnit(am.value, am.m, t));
}

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

function measured(today: Today | null, m: MetricKey) {
  const c = cardOf(today, m);
  return c != null && c.state !== "not_measured" && c.state !== "no_data";
}

/** "cabin CO₂ and pressure are normal" — only for what is actually measured (§12). */
function cabinNormal(inc: Alert, today: Today | null, t: Dict): string | null {
  const flagged = new Set(inc.metrics.map((x) => x.m));
  const ok = (["ppco2", "press"] as const).filter((m) => !flagged.has(m) && measured(today, m));
  if (ok.length === 2) return t.text.cabinBothNormal;
  if (ok.length === 1) return ok[0] === "ppco2" ? t.text.cabinCo2Normal : t.text.cabinPressNormal;
  return null;
}

export function incidentWhy(inc: Alert, today: Today | null, t: Dict): string {
  const why = serverText(inc, t)?.why;
  if (why) return String(why);
  const primary = inc.primary;
  const am = inc.metrics.find((x) => x.m === primary);
  const parts: string[] = [];
  if (am && primary) {
    const v = fmtUnit(am.value, primary, t);
    parts.push(am.usual ? t.text.valueUsual(v, fmtRange(am.usual, primary)) : `${v}.`);
  }
  const rest = inc.metrics.filter((x) => x.m !== primary).map((x) => companion(x, inc.ctx, t));
  const cabin = cabinNormal(inc, today, t);
  const tail = [...rest, ...(cabin ? [cabin] : [])];
  if (tail.length) parts.push(cap(tail.join("; ")) + ".");
  return parts.join(" ");
}

export function incidentTitle(inc: Alert, today: Today | null, t: Dict): string {
  const what = serverText(inc, t)?.what;
  if (what) return String(what);
  const m = inc.primary;
  if (!m) return t.text.titleNoPrimary;
  const am = inc.metrics.find((x) => x.m === m);
  const dur = t.minutesWord(Math.max(1, am?.since_min ?? inc.since_min));
  if (m === "ppco2") return t.text.titleCo2(dur);
  if (m === "press") return t.text.titlePress(am?.trend === "falling", dur);
  const dir: Dir = direction(am, cardOf(today, m)) ?? "outside";
  if (inc.source === "hard" || !am?.usual) return t.text.titleHard(t.metric[m].label, dir, dur);
  return t.text.titleUsual(t.metric[m].label, dir, dur);
}

export function noticeText(n: Alert, today: Today | null, t: Dict): NoticeText {
  if (n.key === "baseline_learned") {
    return {
      label: t.text.baselineLabel,
      title: t.text.baselineTitle,
      body: t.text.baselineBody,
      explained: false,
      tone: "var(--mute)",
    };
  }
  if (n.key.startsWith("checkin:")) {
    return {
      label: t.text.checkinLabel,
      title: t.text.checkinTitle,
      body: t.text.checkinBody,
      action: { label: t.text.checkinAction, href: "/checkin" },
      explained: false,
      tone: "var(--mute)",
    };
  }
  const lvl = Math.max(n.level, n.ack_ts ? 0 : n.peak_level) as Alert["level"];
  const shown = n.level || n.peak_level;
  const topic = n.pattern ? t.pattern[n.pattern] ?? n.pattern : n.primary ? t.metric[n.primary].label : t.text.readings;
  return {
    label: `${n.ts_end ? t.text.ended : t.levels[shown]} · ${topic}`,
    title: incidentTitle(n, today, t),
    body: incidentWhy(n, today, t),
    action: n.primary ? { label: t.text.openMetric(t.metric[n.primary].lower), href: `/metric/${n.primary}` } : undefined,
    explained: t.serverText && n.text_src != null && n.text_src !== "template",
    tone: lvl >= 2 ? "var(--attn)" : lvl === 1 ? "var(--kick)" : "var(--mute)",
  };
}

/** One sentence for the Alert / Critical banner (§4.4). */
export function bannerText(today: Today, t: Dict): string {
  const inc = incidentOf(today);
  if (!inc) return t.text.bannerNone;
  const what = serverText(inc, t)?.what;
  if (what) return String(what);
  const m = inc.primary;
  if (!m) return t.text.bannerNoPrimary;
  const am = inc.metrics.find((x) => x.m === m);
  const dur = t.minutesWord(Math.max(1, am?.since_min ?? inc.since_min));
  if (!isVital(m)) return t.text.bannerCabin(t.metric[m].lower, dur);
  const dir: Dir = direction(am, cardOf(today, m)) ?? "outside";
  const hard = inc.source === "hard" || !am?.usual;
  return t.text.bannerVital(t.metric[m].label, dir, hard, dur, inc.ctx ? ctxWord(inc.ctx, t) : null);
}

/** Steps for the Critical screen: at most three (§7). */
export function criticalSteps(inc: Alert, t: Dict): string[] {
  const a = serverText(inc, t)?.action;
  if (Array.isArray(a)) return a.slice(0, 3).map(String);
  if (typeof a === "string" && a) return [a];
  return t.text.steps[inc.primary ?? "default"] ?? t.text.steps.default;
}

export function criticalWhy(inc: Alert, today: Today | null, t: Dict): string {
  const why = serverText(inc, t)?.why;
  if (why) return String(why);
  const primary = inc.primary;
  const am = inc.metrics.find((x) => x.m === primary);
  const parts: string[] = [];
  if (primary && am) {
    const trend = am.trend === "rising" || am.trend === "falling" ? am.trend : null;
    parts.push(t.text.critPrimary(t.metric[primary].label, trend, isVital(primary) ? ctxWord(inc.ctx, t) : null));
  }
  const others = inc.metrics.filter((x) => x.m !== primary).map((x) => companion(x, inc.ctx, t));
  if (others.length) parts.push(cap(others.join("; ")) + ".");
  const cabin = cabinNormal(inc, today, t);
  if (cabin) parts.push(cap(cabin) + ".");
  if (inc.pattern && t.pattern[inc.pattern]) {
    parts.push(t.text.matchesPattern(t.pattern[inc.pattern], inc.ctx !== "active"));
  }
  return parts.join(" ");
}
