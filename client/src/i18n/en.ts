// English copy. This file defines the shape of a dictionary (`Dict`):
// every other locale must provide the same keys (see ./index.tsx to register one).

import type { CardState, Ctx, MetricKey, Signal } from "@/lib/types";

export type Dir = "below" | "above" | "outside";
export type Trend = "rising" | "falling";

const pad = (n: number) => String(n).padStart(2, "0");
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

const minutes = (n: number) => {
  if (n < 60) return `${n} min`;
  const h = Math.floor(n / 60);
  const m = n % 60;
  return m ? `${h} h ${pad(m)} m` : `${h} h`;
};

export const en = {
  code: "en",
  name: "English",
  short: "EN",
  intl: "en-GB", // dates
  // The server writes its own copy (alert text, Ask answers) in English only.
  serverText: true,

  // ---- formatting ----
  levels: ["Usual", "Watch", "Alert", "Critical"] as string[],
  metric: {
    hr: { label: "Heart rate", lower: "heart rate", unit: "bpm" },
    spo2: { label: "Blood oxygen", lower: "blood oxygen", unit: "%" },
    rr: { label: "Respiration", lower: "respiration", unit: "br/min" },
    skin_t: { label: "Skin temperature", lower: "skin temperature", unit: "°C" },
    ppco2: { label: "CO₂", lower: "cabin CO₂", unit: "mmHg" },
    press: { label: "Pressure", lower: "cabin pressure", unit: "hPa" },
    amb_t: { label: "Temperature", lower: "cabin temperature", unit: "°C" },
  } as Record<MetricKey, { label: string; lower: string; unit: string }>,
  pattern: {
    hypoxia: "Low blood oxygen",
    tachycardia_rest: "Fast heart rate at rest",
    bradycardia: "Slow heart rate",
    fever_like: "Rising skin temperature",
    hypercapnia: "Response to high cabin CO₂",
    depressurization: "Cabin pressure drop",
    sensor_artifact: "Unreliable sensor reading",
  } as Record<string, string>,
  ctx: { off: "Not worn", sleep: "Asleep", rest: "Resting", active: "Exercising" } as Record<Ctx, string>,
  /** "… while asleep" */
  ctxWord: { off: "not worn", sleep: "asleep", rest: "resting", active: "exercising" } as Record<Ctx, string>,
  signal: { good: "Good", fair: "Fair", poor: "Poor" } as Record<Signal, string>,
  signalLower: { good: "good", fair: "fair", poor: "poor" } as Record<Signal, string>,
  minutes,
  /** Duration in prose: "for 5 minutes". */
  minutesWord: (n: number) => (n <= 1 ? "1 minute" : n < 60 ? `${n} minutes` : minutes(n)),
  greeting: (hour: number | null): string =>
    hour == null ? "Hello" : hour < 5 ? "Good night" : hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening",

  // ---- vital cards (§5.3) ----
  card: {
    status: {
      watch: "Watch", alert: "Alert", critical: "Critical", exercising: "Exercise", no_data: "Sensor off", usual: "Usual",
    } as Partial<Record<CardState, string>>,
    notMeasured: "Not measured by this device",
    noDataSince: (hhmm: string) => `No data since ${hhmm}`,
    noData: "No data",
    limit: (v: string) => `Limit ${v} mmHg`,
    stable: "Stable",
    falling: "Falling",
    cabinAir: "Cabin air",
    notCompared: "Not compared during exercise",
    learning: (day: number, of: number) => `Learning · day ${day} of ${of}`,
    usual: (range: string) => `Your usual ${range}`,
  },

  // ---- notice / banner / Critical copy (lib/text.ts) ----
  text: {
    dir: { below: "below", above: "above", outside: "outside" } as Record<Dir, string>,
    followSteps: "Follow the steps from the alert.",
    ledeCo2High: "Cabin CO₂ is above the 3.0 mmHg limit. Follow the crew procedure for high CO₂.",
    ledePressDrop: "Cabin pressure is dropping. Follow the crew procedure for a pressure leak.",
    ledeCritical: (label: string, dir: Dir) => `${label} is ${dir} the safety limit. Follow the steps from the alert.`,
    ledeAlert: (label: string, dir: Dir) => `${label} is ${dir} your usual range. Check the sensor fit and repeat the reading.`,
    ledeWatchCabin: (label: string) => `${label} in the cabin is slightly above its limit. Everything else is within range.`,
    ledeWatch: (label: string, dir: Dir) => `${label} is slightly ${dir} your usual range. Everything else is within it.`,
    ledeLearning: (day: number, of: number) =>
      `Vigil is still learning your usual ranges — day ${day} of ${of}. Until then, only fixed safety limits apply.`,
    ledeAllUsual: "Everything is within your own usual range.",
    ledeOpen: (n: number) => `${n === 1 ? "One notice needs" : `${n} notices need`} your attention. Everything else is within your own usual range.`,

    baselineLabel: "Note",
    baselineTitle: "Your usual ranges are set",
    baselineBody: "Learned from 7 days of your own readings. They keep adjusting slowly as you adapt.",
    checkinLabel: "To do",
    checkinTitle: "Daily check-in not yet filed",
    checkinBody: "About one minute. Until it is filed, today is shown to the ground as “no data”, never as “fine”.",
    checkinAction: "Start check-in",
    ended: "Ended",
    readings: "Readings",
    openMetric: (lower: string) => `Open ${lower}`,

    companionTrend: (lower: string, trend: Trend, ctx: string | null) => `${cap(lower)} is ${trend}${ctx ? ` while ${ctx}` : ""}`,
    companionValue: (lower: string, value: string) => `${cap(lower)} is ${value}`,
    cabinBothNormal: "cabin CO₂ and pressure are normal",
    cabinCo2Normal: "cabin CO₂ is normal",
    cabinPressNormal: "cabin pressure is normal",
    valueUsual: (value: string, range: string) => `${value}, usual ${range}.`,

    titleNoPrimary: "Readings outside the usual range",
    titleCo2: (dur: string) => `Cabin CO₂ above the 3.0 mmHg limit for ${dur}`,
    titlePress: (falling: boolean, dur: string) => `Cabin pressure ${falling ? "falling" : "low"} for ${dur}`,
    titleHard: (label: string, dir: Dir, dur: string) => `${label} ${dir} the safety limit for ${dur}`,
    titleUsual: (label: string, dir: Dir, dur: string) => `${label} ${dir} your usual range for ${dur}`,

    bannerNone: "A reading is outside its safe range.",
    bannerNoPrimary: "Readings are outside your usual range.",
    bannerCabin: (lower: string, dur: string) => `${cap(lower)} has been outside its limit for ${dur}.`,
    bannerVital: (label: string, dir: Dir, hard: boolean, dur: string, ctx: string | null) =>
      `${label} has been ${dir} ${hard ? "the safety limit" : "your usual range"} for ${dur}${ctx ? ` while ${ctx}` : ""}.`,

    steps: {
      spo2: [
        "Check the sensor fit and repeat the reading with the kit oximeter.",
        "If it stays at 91 % or below, notify the crew medical officer.",
      ],
      hr: [
        "Stop activity, sit or anchor yourself and breathe slowly for two minutes.",
        "Repeat the reading. If it does not settle, notify the crew medical officer.",
      ],
      rr: ["Check the sensor fit and count your breaths for one minute.", "If it does not settle, notify the crew medical officer."],
      ppco2: ["Move to a module with fresh airflow.", "Report the reading to the ground and the commander."],
      press: ["Follow the emergency procedure for a pressure leak.", "Notify the commander and the ground."],
      default: ["Check the sensor fit and repeat the reading.", "Notify the crew medical officer."],
    } as Record<string, string[]>,
    critPrimary: (label: string, trend: Trend | null, ctx: string | null) =>
      `${label} is ${trend ?? "outside its safe range"}${ctx ? ` while ${ctx}` : ""}.`,
    matchesPattern: (pattern: string, notExercise: boolean) =>
      `This matches ${pattern.toLowerCase()}${notExercise ? ", not exercise" : ""}.`,
  },

  // ---- shell ----
  nav: { today: "Today", checkin: "Check-in", sleep: "Sleep", radiation: "Radiation", crew: "Crew", report: "Report" },
  due: "due",
  language: "Language",
  device: {
    waiting: "Waiting for the server",
    noLinkFor: (min: number) => `No link for ${min} min`,
    noLink: "No link",
    notWorn: "Not worn",
    signalPoor: "Signal poor",
    connected: (signal: string) => `Connected · signal ${signal}`,
    wristband: "Wristband",
    battery: (v: string) => `Battery ${v}`,
  },
  flightDay: (n: number) => `Flight day ${n}`,
  liveOpen: "Live link open",
  serverUnreachable: "Server unreachable",
  liveReconnecting: "Live link reconnecting…",
  levelAlert: "Alert",
  levelCritical: "Critical",
  showReadings: "Show readings",
  criticalFor: (min: number) => `Critical · for ${min} min`,
  yourUsual: (range: string) => `Your usual ${range}`,
  limitValue: (v: string) => `Limit ${v}`,
  fixedLimit: "Fixed safety limit",
  trendWord: { rising: "rising", falling: "falling" } as Record<Trend, string>,
  acknowledge: "Acknowledge",
  acknowledged: "Acknowledged",
  addedToReport: "Added to today’s report.",

  loading: {
    noConnection: "No connection to the server.",
    connecting: "Connecting…",
    cannotReach: (url: string, err: string) => `Vigil could not reach ${url}. It keeps trying every few seconds. (${err})`,
    reading: "Reading your record from the station server.",
  },

  notices: {
    title: "Notices",
    nothing: "Nothing needs your attention.",
    checkedAt: (hhmm: string) => `Checked at ${hhmm} GMT.`,
    explained: "Explained by the language model",
  },

  // ---- Today ----
  today: {
    liveNoLink: "No link to wristband · showing last values",
    liveNotWorn: "Wristband not worn",
    live: (signal: string, ctx: string | null) => `Live from wristband · signal ${signal}${ctx ? ` · ${ctx}` : ""}`,
    learningBaseline: (day: number, of: number) => `Learning your baseline · day ${day} of ${of}`,
    vitalSigns: "Vital signs",
    you: "You",
    cabinAir: "Cabin air",
    record: "The day’s record",
    checkin: "Check-in",
    filedAt: (hhmm: string) => `Filed at ${hhmm}`,
    notFiled: "Not yet filed",
    checkinSummary: (sleep: number, mood: number, energy: number) => `Sleep ${sleep} · mood ${mood} · energy ${energy}`,
    aboutMinute: "About one minute",
    sleep: "Sleep",
    lastNight: (dur: string) => `${dur} last night`,
    noNights: "No nights recorded yet",
    baseline: "Baseline",
    learned: "Learned",
    learning: "Learning",
    cellsReady: (pct: number) => `${pct} % of cells ready`,
    dayOf: (day: number, of: number) => `Day ${day} of ${of}`,
    radiation: "Radiation",
    perDay: (v: string) => `${v} mGy/day`,
    noStation: "No station data yet",
    radiationSource: "ISS, measured 2019 · NASA OSDR",
    radiationApp: "NASA OSDR Environmental Data App",
    report: "Report",
    queued: "Queued for next signal",
    notSent: "Not yet sent",
  },

  // ---- Check-in ----
  checkin: {
    scales: {
      sleep: { label: "How well did you sleep?", lo: "Poorly", hi: "Very well" },
      mood: { label: "Mood", lo: "Low", hi: "Good" },
      energy: { label: "Energy", lo: "Drained", hi: "Full" },
    },
    symptoms: {
      headache: "Headache",
      congestion: "Nasal congestion",
      back: "Back pain",
      vision: "Blurred near vision",
      nausea: "Nausea",
      skin: "Skin irritation",
    } as Record<string, string>,
    eyebrow: "Daily check-in · about one minute",
    title: "How are you today?",
    lede: "Sensors miss what you feel. Your answers are compared with your own earlier entries, not with a crew average.",
    anything: "Anything to note since yesterday?",
    ownWords: "In your own words (optional)",
    placeholder: "e.g. Woke twice, stuffy after the reboost",
    update: "Update check-in",
    file: "File check-in",
    filedAt: (hhmm: string) => `Filed at ${hhmm} GMT and added to your record.`,
  },

  // ---- Crew ----
  crew: {
    topic: {
      hr: "heart rate", spo2: "oxygen", rr: "breathing", skin_t: "temperature", co2: "CO₂", pressure: "pressure", amb_t: "cabin",
    } as Record<string, string>,
    eyebrow: (n: number | null) => `Crew summary · ${n == null ? "…" : `${n} aboard`}`,
    title: "The crew at a glance",
    lede: "Each crewmember chooses what appears here. Detail stays private to them and the flight surgeon; this page shows status only, and a blank is shown as a blank.",
    cols: ["Crewmember", "Status", "Baseline", "Check-in", "Sleep, 7-night mean", "Data today"],
    noDataToday: "No data today",
    notShared: "Not shared",
    notFiled: "Not filed",
    learned: "Learned",
    learning: (day: number, of: number) => `Learning · day ${day} of ${of}`,
    you: " (you)",
  },

  // ---- Device ----
  devicePage: {
    eyebrow: "Device",
    noLink: (forDur: string | null) => `No link to the wristband${forDur ? ` for ${forDur}` : ""}.`,
    notWorn: (since: string | null) => `Wristband not worn${since ? ` since ${since}` : ""}.`,
    connected: "Wristband connected.",
    dataToday: "Data today",
    coverage: (withData: string, without: string) => `${withData} of data · ${without} without · last 24 hours`,
    noReadings: "No readings in this period.",
    link: "Link",
    connectedWord: "Connected",
    noLinkWord: "No link",
    lastReading: (s: number) => `Last reading ${s} s ago`,
    noLive: "No live reading yet",
    signal: "Signal",
    notWorn2: "Not worn",
    optical: "Optical contact",
    battery: "Battery",
    wristband: "Wristband",
    minutesSince: "Of minutes since 00:00 GMT",
    sensors: "Sensors",
    cols: ["Sensor", "Measures", "Status"],
    working: "Working",
    notInstalled: "Not installed",
    rows: {
      optical: ["Optical", "Heart rate, blood oxygen, respiration"],
      motion: ["Motion", "Activity, sleep"],
      skin: ["Skin temperature", "Skin temperature"],
      cabin: ["Cabin air", "CO₂, temperature"],
      press: ["Pressure", "Cabin pressure"],
    } as Record<"optical" | "motion" | "skin" | "cabin" | "press", [string, string]>,
  },

  // ---- Metric ----
  metricPage: {
    ranges: { "1h": "1 h", "24h": "24 h", "7d": "7 d" } as Record<"1h" | "24h" | "7d", string>,
    notMeasured: (label: string) => `${label} is not measured by this device.`,
    noReading: (lower: string) => `No ${lower} reading right now.`,
    co2: (value: string, above: boolean) => `${value}, ${above ? "above" : "under"} the 3.0 mmHg limit.`,
    cabin: (value: string) => `${value} in the cabin.`,
    exercising: (value: string) => `${value}, not compared during exercise.`,
    learning: (lower: string, day: number, of: number) => `Still learning your usual ${lower} — day ${day} of ${of}.`,
    within: (value: string) => `${value}, within your usual range.`,
    outside: (value: string, dir: Dir, sinceMin: number | null) =>
      `${value}, ${dir} your usual range${sinceMin ? ` for ${sinceMin} minutes` : ""}.`,
    vitalLede: " · compared with your own readings at this time of day",
    cabinLede: " · cabin air, same for the whole crew",
    period: "Period",
    noReadings: "No readings in this period.",
    now: "Now",
    current: "Current",
    usualNow: "Your usual now",
    stillLearning: "Still learning",
    difference: "Difference",
    withinRange: "Within range",
    diff: (v: string, below: boolean) => `${v} ${below ? "below" : "above"}`,
    limit: "Limit",
    context: "Context",
    signal: "Signal",
    events: "Events",
    noDeviations: "No deviations in this period.",
    ongoing: (dur: string) => `ongoing · ${dur}`,
    acked: "acknowledged",
    notAcked: "not acknowledged",
    vitalFoot:
      "Your usual range is learned from the last 14 days of your own readings, separately for sleep, rest and time of day. Readings taken during an alert are not learned.",
    cabinFoot: "Cabin limits are fixed and the same for everyone aboard.",
  },

  chart: {
    limit: (v: string) => `Limit ${v}`,
    criticalBelow: (v: string) => `Critical at ${v} or below`,
    criticalAbove: (v: string) => `Critical at ${v} or above`,
    noData: "No data",
    noReadings: "No readings in this period.",
    usual: (range: string) => `Usual ${range}`,
    asleep: "Asleep",
    resting: "Resting",
    exercise: "Exercise",
  },

  // ---- Sleep ----
  sleep: {
    tonight: [
      ["16:00", "Finish exercise. Late sessions push sleep onset back."],
      ["20:00", "Switch crew-quarters lighting to the warm pre-sleep setting."],
      ["21:00", "Screens off, window shades closed."],
      ["06:00", "Bright, blue-enriched light for the first hour awake."],
    ] as [string, string][],
    unavailable: "Sleep data is not available.",
    loading: "Loading…",
    notShared: "Sleep is not shared.",
    lastNight: (dur: string) => `${dur} asleep last night.`,
    noNights: "No nights recorded yet.",
    eyebrow: "Sleep and circadian rhythm",
    lede: "With sixteen sunrises a day, cabin light is the main cue your body gets.",
    asleepFrom: (a: string, b: string) => ` Asleep from ${a} to ${b} GMT, estimated from wrist motion and heart rate.`,
    onceRecorded: " Once the wristband has recorded a night, it is shown here against the schedule.",
    inProgress: " The current night is still in progress and is not counted yet.",
    againstSchedule: "Last night against the schedule",
    asleepAria: (a: string, b: string) => `Asleep from ${a} to ${b} GMT`,
    sevenNights: (mean: string | null) => `Seven nights${mean ? ` · mean ${mean}` : ""}`,
    forTonight: "For tonight",
  },

  // ---- Radiation ----
  radiation: {
    mGy: "mGy",
    mGyDay: "mGy/day",
    lastDay: "Last recorded day",
    mean14: "Mean, fourteen days",
    total14: "Total, fourteen days",
    noStation: "No station data yet",
    days: (n: number) => `${n} days`,
    eyebrow: "Station dosimeter · ISS · NASA OSDR Environmental Data App",
    title: "Radiation",
    lede: "Dose on station runs many times higher than on the ground. Days with more South Atlantic Anomaly passes read higher.",
    measured: (when: string) => ` Measured on the ISS, ${when}.`,
    daily14: "Daily dose, fourteen days",
    couldNotLoad: (err: string) => `Could not load: ${err}`,
    noReadings: "No readings in this period.",
    aria: (n: number, lo: string, hi: string) => `Daily absorbed dose for ${n} days, from ${lo} to ${hi} mGy per day`,
    barTitle: (day: string, total: string, gcr: string, saa: string) =>
      `${day} · ${total} mGy · cosmic rays ${gcr}, South Atlantic Anomaly ${saa}`,
    foot: "mGy per day · absorbed dose · upper part of each bar: South Atlantic Anomaly passes; lower part: galactic cosmic rays.",
    source: (src: string) => ` Source: ${src}. These are recorded values, not a live reading.`,
  },

  // ---- Report ----
  report: {
    sections: {
      vitals: "Vital signs summary",
      alerts: "Alerts and notices",
      sleep: "Sleep",
      checkin: "Daily check-in",
      cabin: "Cabin air",
    },
    titles: { vitals: "Vital signs", alerts: "Alerts and notices", sleep: "Sleep", checkin: "Check-in", cabin: "Cabin air" },
    noVitals: "No vital-sign readings at the moment of writing.",
    outside: (list: string) => ` Outside personal baseline: ${list}.`,
    learning: (day: number, of: number) => ` Personal baseline still being learned (day ${day} of ${of}).`,
    allWithin: " All within personal baseline.",
    noAlerts: "No alerts today.",
    reading: "Reading",
    alertLine: (level: string, topic: string, at: string, dur: string, acked: boolean, ongoing: boolean) =>
      `${level} · ${topic} at ${at}, ${dur}${acked ? ", acknowledged" : ""}${ongoing ? ", ongoing" : ""}.`,
    noCabin: "No cabin readings.",
    co2Above: " CO₂ above the 3.0 mmHg limit.",
    co2Under: " CO₂ under the 3.0 mmHg limit.",
    noDataToday: "No data today.",
    coverage: (withData: string, without: string) => `${withData} of data, ${without} without.`,
    noNights: "No nights recorded yet.",
    checkinLine: (sleep: number, mood: number, energy: number) => `Sleep quality ${sleep}/5, mood ${mood}/5, energy ${energy}/5. `,
    reported: (list: string) => `Reported: ${list}.`,
    noSymptoms: "No symptoms reported.",
    checkinNotFiled: "Not filed today. No data.",
    eyebrow: "Report for Earth",
    title: "What the ground will read",
    lede: "You decide what goes into the daily health summary for your flight surgeon. It is sent at the next acquisition of signal.",
    include: "Include",
    coverageAlways: "Data coverage — always included",
    noteLabel: "Note to the flight surgeon",
    notePlaceholder: "Anything you want raised at the next private medical conference",
    withdraw: "Withdraw from queue",
    queue: "Queue for next downlink",
    queuedNote: "Queued. Sends at the next acquisition of signal.",
    sendsNote: "Sends at the next acquisition of signal.",
    to: "To: Flight Surgeon, Mission Control",
    from: (who: string) => `From: ${who}`,
    crewN: (id: number) => `Crew ${id}`,
    summary: "Daily health summary",
    notShared: "Not shared today.",
    coverageTitle: "Data coverage",
    noteFrom: "Note from crewmember",
  },

  // ---- Ask Vigil ----
  ask: {
    suggestions: [
      "Is anything outside my usual range right now?",
      "How did I sleep last night?",
      "What alerts did I have in the last 24 hours?",
    ],
    open: "Ask Vigil",
    close: "Close Ask Vigil",
    title: "Ask Vigil",
    disclaimer: "Answers come only from your own record. Not medical advice.",
    couldNotAsk: (err: string) => `Could not ask: ${err}`,
    reading: "Reading your record…",
    byModel: "Written by the language model from your record",
    yourQuestion: "Your question",
    placeholder: "Ask about your readings, alerts or sleep",
    send: "Ask",
  },

  // ---- Demo ----
  demo: {
    open: "Demo",
    close: "Close demo",
    aria: "Demo controls",
    crewmember: "Crewmember",
    crewN: (id: number) => `Crew ${id}`,
    scenario: "Scenario",
    choose: "Choose…",
    placeholder: "e.g. hypoxia",
    run: "Run",
    sent: (s: string) => `Scenario ${s} sent`,
    speed: "Speed",
    speedSet: (s: string) => `Speed ×${s}`,
    reset: "Reset",
    resetDone: "Reset done",
  },
};

export type Dict = typeof en;
