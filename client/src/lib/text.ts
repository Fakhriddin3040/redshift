// Interface copy built from server data (DESIGN_TZ §5.1, §5.4, §7, §12).
// The server's own `text` (what / why / action) wins whenever it is present.

import type { Alert, AlertMetric, Card, MetricKey, Today } from "./types";
import { METRIC, PATTERN_LABEL, ctxWord, fmtRange, fmtUnit, isVital, levelName, minutesWord } from "./format";

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

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

/** First sentence under the greeting on Today. */
export function lede(today: Today): string {
  const inc = incidentOf(today);
  const open = today.notices.filter((n) => n.ack_ts == null).length;
  const primary = inc?.primary;
  if (today.level >= 2 && primary) {
    const am = inc!.metrics.find((x) => x.m === primary);
    if (primary === "ppco2") return "Cabin CO₂ is above the 3.0 mmHg limit. Follow the crew procedure for high CO₂.";
    if (primary === "press") return "Cabin pressure is dropping. Follow the crew procedure for a pressure leak.";
    const dir = direction(am, cardOf(today, primary)) ?? "outside";
    const where = dir === "outside" ? "outside" : dir;
    if (today.level === 3) return `${METRIC[primary].label} is ${where} the safety limit. Follow the steps from the alert.`;
    return `${METRIC[primary].label} is ${where} your usual range. Check the sensor fit and repeat the reading.`;
  }
  if (today.level === 1 && primary) {
    const am = inc!.metrics.find((x) => x.m === primary);
    if (!isVital(primary)) return `${METRIC[primary].label} in the cabin is slightly above its limit. Everything else is within range.`;
    const dir = direction(am, cardOf(today, primary)) ?? "outside";
    return `${METRIC[primary].label} is slightly ${dir} your usual range. Everything else is within it.`;
  }
  if (today.baseline.state === "learning") {
    return `Vigil is still learning your usual ranges — day ${today.baseline.day} of ${today.baseline.of}. Until then, only fixed safety limits apply.`;
  }
  if (open === 0) return "Everything is within your own usual range.";
  return `${open === 1 ? "One notice needs" : `${open} notices need`} your attention. Everything else is within your own usual range.`;
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
function companion(am: AlertMetric, ctx: Alert["ctx"]): string {
  const name = cap(METRIC[am.m].lower);
  if (am.trend === "rising" || am.trend === "falling") {
    return `${name} is ${am.trend}${isVital(am.m) ? ` while ${ctxWord(ctx)}` : ""}`;
  }
  return `${name} is ${fmtUnit(am.value, am.m)}`;
}

function measured(today: Today | null, m: MetricKey) {
  const c = cardOf(today, m);
  return c != null && c.state !== "not_measured" && c.state !== "no_data";
}

/** "cabin CO₂ and pressure are normal" — only for what is actually measured (§12). */
function cabinNormal(inc: Alert, today: Today | null): string | null {
  const flagged = new Set(inc.metrics.map((x) => x.m));
  const ok = (["ppco2", "press"] as const).filter((m) => !flagged.has(m) && measured(today, m));
  if (ok.length === 2) return "cabin CO₂ and pressure are normal";
  if (ok.length === 1) return ok[0] === "ppco2" ? "cabin CO₂ is normal" : "cabin pressure is normal";
  return null;
}

export function incidentWhy(inc: Alert, today: Today | null): string {
  if (inc.text?.why) return String(inc.text.why);
  const primary = inc.primary;
  const am = inc.metrics.find((x) => x.m === primary);
  const parts: string[] = [];
  if (am && primary) {
    parts.push(am.usual ? `${fmtUnit(am.value, primary)}, usual ${fmtRange(am.usual, primary)}.` : `${fmtUnit(am.value, primary)}.`);
  }
  const rest = inc.metrics.filter((x) => x.m !== primary).map((x) => companion(x, inc.ctx));
  const cabin = cabinNormal(inc, today);
  const tail = [...rest, ...(cabin ? [cabin] : [])];
  if (tail.length) parts.push(cap(tail.join("; ")) + ".");
  return parts.join(" ");
}

export function incidentTitle(inc: Alert, today: Today | null): string {
  if (inc.text?.what) return String(inc.text.what);
  const m = inc.primary;
  if (!m) return "Readings outside the usual range";
  const am = inc.metrics.find((x) => x.m === m);
  const dur = minutesWord(Math.max(1, am?.since_min ?? inc.since_min));
  if (m === "ppco2") return `Cabin CO₂ above the 3.0 mmHg limit for ${dur}`;
  if (m === "press") return `Cabin pressure ${am?.trend === "falling" ? "falling" : "low"} for ${dur}`;
  const dir = direction(am, cardOf(today, m));
  if (inc.source === "hard" || !am?.usual) {
    return `${METRIC[m].label} ${dir ?? "outside"} the safety limit for ${dur}`;
  }
  return `${METRIC[m].label} ${dir ?? "outside"} your usual range for ${dur}`;
}

export function noticeText(n: Alert, today: Today | null): NoticeText {
  if (n.key === "baseline_learned") {
    return {
      label: "Note",
      title: "Your usual ranges are set",
      body: "Learned from 7 days of your own readings. They keep adjusting slowly as you adapt.",
      explained: false,
      tone: "var(--mute)",
    };
  }
  if (n.key.startsWith("checkin:")) {
    return {
      label: "To do",
      title: "Daily check-in not yet filed",
      body: "About one minute. Until it is filed, today is shown to the ground as “no data”, never as “fine”.",
      action: { label: "Start check-in", href: "/checkin" },
      explained: false,
      tone: "var(--mute)",
    };
  }
  const lvl = Math.max(n.level, n.ack_ts ? 0 : n.peak_level) as Alert["level"];
  const shown = n.level || n.peak_level;
  const topic = n.pattern ? PATTERN_LABEL[n.pattern] ?? n.pattern : n.primary ? METRIC[n.primary].label : "Readings";
  return {
    label: `${n.ts_end ? "Ended" : levelName(shown)} · ${topic}`,
    title: incidentTitle(n, today),
    body: incidentWhy(n, today),
    action: n.primary ? { label: `Open ${METRIC[n.primary].lower}`, href: `/metric/${n.primary}` } : undefined,
    explained: n.text_src != null && n.text_src !== "template",
    tone: lvl >= 2 ? "var(--attn)" : lvl === 1 ? "var(--kick)" : "var(--mute)",
  };
}

/** One sentence for the Alert / Critical banner (§4.4). */
export function bannerText(today: Today): string {
  const inc = incidentOf(today);
  if (!inc) return "A reading is outside its safe range.";
  if (inc.text?.what) return String(inc.text.what);
  const m = inc.primary;
  if (!m) return "Readings are outside your usual range.";
  const am = inc.metrics.find((x) => x.m === m);
  const dur = minutesWord(Math.max(1, am?.since_min ?? inc.since_min));
  if (!isVital(m)) return `${cap(METRIC[m].lower)} has been outside its limit for ${dur}.`;
  const dir = direction(am, cardOf(today, m)) ?? "outside";
  const ref = inc.source === "hard" || !am?.usual ? "the safety limit" : "your usual range";
  return `${METRIC[m].label} has been ${dir} ${ref} for ${dur}${inc.ctx ? ` while ${ctxWord(inc.ctx)}` : ""}.`;
}

/** Steps for the Critical screen: at most three (§7). */
export function criticalSteps(inc: Alert): string[] {
  const a = inc.text?.action;
  if (Array.isArray(a)) return a.slice(0, 3).map(String);
  if (typeof a === "string" && a) return [a];
  switch (inc.primary) {
    case "spo2":
      return [
        "Check the sensor fit and repeat the reading with the kit oximeter.",
        "If it stays at 91 % or below, notify the crew medical officer.",
      ];
    case "hr":
      return [
        "Stop activity, sit or anchor yourself and breathe slowly for two minutes.",
        "Repeat the reading. If it does not settle, notify the crew medical officer.",
      ];
    case "rr":
      return [
        "Check the sensor fit and count your breaths for one minute.",
        "If it does not settle, notify the crew medical officer.",
      ];
    case "ppco2":
      return ["Move to a module with fresh airflow.", "Report the reading to the ground and the commander."];
    case "press":
      return ["Follow the emergency procedure for a pressure leak.", "Notify the commander and the ground."];
    default:
      return ["Check the sensor fit and repeat the reading.", "Notify the crew medical officer."];
  }
}

export function criticalWhy(inc: Alert, today: Today | null): string {
  if (inc.text?.why) return String(inc.text.why);
  const primary = inc.primary;
  const am = inc.metrics.find((x) => x.m === primary);
  const parts: string[] = [];
  if (primary && am) {
    parts.push(
      `${METRIC[primary].label} is ${am.trend === "rising" || am.trend === "falling" ? am.trend : "outside its safe range"}` +
        (isVital(primary) ? ` while ${ctxWord(inc.ctx)}` : "") + "."
    );
  }
  const others = inc.metrics.filter((x) => x.m !== primary).map((x) => companion(x, inc.ctx));
  if (others.length) parts.push(cap(others.join("; ")) + ".");
  const cabin = cabinNormal(inc, today);
  if (cabin) parts.push(cap(cabin) + ".");
  if (inc.pattern && PATTERN_LABEL[inc.pattern]) {
    parts.push(`This matches ${PATTERN_LABEL[inc.pattern].toLowerCase()}${inc.ctx !== "active" ? ", not exercise" : ""}.`);
  }
  return parts.join(" ");
}
