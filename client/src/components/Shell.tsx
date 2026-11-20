"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { LOCALES, useI18n, type Dict, type Locale } from "@/i18n";
import { fmt, fmtRange, hhmmss, levelColor } from "@/lib/format";
import { pageLevel, useVigil } from "@/lib/store";
import { bannerText, criticalSteps, criticalWhy, incidentOf } from "@/lib/text";
import type { CrewItem, Today } from "@/lib/types";
import { AskPanel } from "./AskPanel";
import { DemoPanel } from "./DemoPanel";

const NAV = [
  { href: "/", key: "today" },
  { href: "/checkin", key: "checkin" },
  { href: "/sleep", key: "sleep" },
  { href: "/radiation", key: "radiation" },
  { href: "/crew", key: "crew" },
  { href: "/report", key: "report" },
] as const;

/** `noLinkMin`: whole minutes since the last live tick, when the link is down. */
export function deviceLine(
  today: Today | null,
  lastTickAt: number | null,
  t: Dict
): { text: string; warn: boolean; noLinkMin?: number } {
  if (!today) return { text: t.device.waiting, warn: true };
  const d = today.device;
  if (d.link === "no_link") {
    const min = lastTickAt ? Math.floor((Date.now() - lastTickAt) / 60000) : null;
    return min && min >= 1 ? { text: t.device.noLinkFor(min), warn: true, noLinkMin: min } : { text: t.device.noLink, warn: true };
  }
  if (d.worn === false) return { text: t.device.notWorn, warn: true };
  if (d.signal === "poor") return { text: t.device.signalPoor, warn: true };
  return { text: t.device.connected(d.signal ? t.signalLower[d.signal] : "—"), warn: false };
}

function LocaleSwitch() {
  const { locale, setLocale, t } = useI18n();
  return (
    <div className="seg" role="group" aria-label={t.language} style={{ alignSelf: "flex-start", marginBottom: 6 }}>
      {(Object.keys(LOCALES) as Locale[]).map((l) => (
        <button key={l} lang={l} title={LOCALES[l].name} aria-pressed={locale === l} onClick={() => setLocale(l)}>
          {LOCALES[l].short}
        </button>
      ))}
    </div>
  );
}

function Sidebar({ me }: { me: CrewItem | undefined }) {
  const path = usePathname();
  const { today, lastTickAt, checkin, live, error } = useVigil();
  const { t } = useI18n();
  const open = today?.notices.filter((n) => n.ack_ts == null).length ?? 0;
  const dev = deviceLine(today, lastTickAt, t);

  return (
    <aside className="sidebar">
      <div className="brand">Vigil</div>
      <nav className="nav">
        {NAV.map((n) => {
          const active = n.href === "/" ? path === "/" || path.startsWith("/metric") : path.startsWith(n.href);
          let badge: React.ReactNode = null;
          if (n.href === "/" && open > 0) {
            badge = <span className="badge num" style={{ color: levelColor(today?.level) }}>{open}</span>;
          } else if (n.href === "/checkin" && today && !checkin) {
            badge = <span className="badge kick">{t.due}</span>;
          }
          return (
            <Link key={n.href} href={n.href} aria-current={active ? "page" : undefined}>
              <span>{t.nav[n.key]}</span>
              {badge}
            </Link>
          );
        })}
      </nav>

      <Link href="/device" className="device-block" aria-current={path === "/device" ? "page" : undefined}>
        <strong>{t.device.wristband}</strong>
        <span style={{ color: dev.warn ? "var(--kick)" : undefined }}>{dev.text}</span>
        <span>{t.device.battery(today?.device.batt != null ? `${today.device.batt} %` : "—")}</span>
      </Link>

      <div className="side-foot">
        <LocaleSwitch />
        <span>
          {today?.flight_day != null ? `${t.flightDay(today.flight_day)} · ` : ""}GMT {hhmmss(today?.now_ts)}
        </span>
        <span>{live === "open" ? t.liveOpen : error ? t.serverUnreachable : t.liveReconnecting}</span>
        {me && <span>{me.name}, {me.role}</span>}
      </div>
    </aside>
  );
}

function LevelBar({ onShow }: { onShow: (m: string) => void }) {
  const { today } = useVigil();
  const { t } = useI18n();
  if (!today || today.level < 2) return null;
  const inc = incidentOf(today);
  const crit = today.level === 3;
  return (
    <div className="banner" data-tone={crit ? "critical" : undefined}>
      <span className="lvl">{crit ? t.levelCritical : t.levelAlert}</span>
      <span className="why">{bannerText(today, t)}</span>
      {inc?.primary && (
        <button className="btn btn-secondary" onClick={() => onShow(inc.primary!)}>
          {crit ? t.showReadings : t.text.openMetric(t.metric[inc.primary].lower)}
        </button>
      )}
    </div>
  );
}

function CriticalScreen({ onShow }: { onShow: (m: string) => void }) {
  const { today, ack } = useVigil();
  const { t } = useI18n();
  const [busy, setBusy] = useState(false);
  if (!today) return null;
  const inc = incidentOf(today);
  if (!inc) return null;
  const m = inc.primary;
  const am = inc.metrics.find((x) => x.m === m);
  const card = [...today.vitals, ...today.cabin].find((c) => c.m === m);
  const value = card?.value ?? am?.value ?? null;
  const usual = am?.usual ?? card?.usual ?? null;
  const unit = m ? t.metric[m].unit : "";
  const steps = criticalSteps(inc, t);

  return (
    <div className="critical" role="alertdialog" aria-labelledby="crit-metric" aria-describedby="crit-why">
      <div className="col">
        <div className="lvl num">{t.criticalFor(Math.max(1, inc.since_min))}</div>
        {m && (
          <>
            <div className="metric" id="crit-metric">{t.metric[m].label}</div>
            <div className="huge">
              {fmt(value, m)}
              <span style={{ fontSize: 32, marginLeft: 10 }}>{unit}</span>
            </div>
            <div className="num" style={{ fontSize: 16 }}>
              {usual ? t.yourUsual(fmtRange(usual, m)) : card?.limit != null ? t.limitValue(`${card.limit} ${unit}`) : t.fixedLimit}
              {am?.trend && am.trend !== "stable" ? ` · ${t.trendWord[am.trend]}` : ""}
            </div>
          </>
        )}
        <p className="why" id="crit-why">{criticalWhy(inc, today, t)}</p>
        <ol>
          {steps.map((s) => <li key={s}>{s}</li>)}
        </ol>
        <div style={{ display: "flex", gap: 10, marginTop: 8 }}>
          <button
            className="btn btn-primary"
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              try {
                await ack(inc.id);
              } finally {
                setBusy(false);
              }
            }}
          >
            {t.acknowledge}
          </button>
          {m && <button className="btn btn-secondary" onClick={() => onShow(m)}>{t.showReadings}</button>}
        </div>
        <div className="foot">{t.addedToReport}</div>
      </div>
    </div>
  );
}

export function Shell({ children }: { children: React.ReactNode }) {
  const { today, crewId } = useVigil();
  const router = useRouter();
  const [crew, setCrew] = useState<CrewItem[]>([]);
  // "Show readings" hides the red screen for this incident without acknowledging it
  const [peekId, setPeekId] = useState<number | null>(null);

  useEffect(() => {
    api.crew().then(setCrew).catch(() => setCrew([]));
  }, [crewId]);

  const level = pageLevel(today);
  const inc = incidentOf(today);
  const showCritical = level === "critical" && inc != null && inc.id !== peekId;

  useEffect(() => {
    document.documentElement.dataset.level = level === "critical" ? "critical-acked" : level;
  }, [level]);

  const onShow = (m: string) => {
    if (inc) setPeekId(inc.id);
    router.push(`/metric/${m}`);
  };

  return (
    <div className="shell">
      {!showCritical && <Sidebar me={crew.find((c) => c.id === crewId)} />}
      <main className="main">
        {today?.level === 1 && <div className="watch-strip" aria-hidden />}
        <div className="content">
          <LevelBar onShow={onShow} />
          {children}
        </div>
      </main>
      {showCritical && <CriticalScreen onShow={onShow} />}
      {/* The Critical screen hides everything except what it asks for. */}
      <AskPanel hidden={showCritical} />
      <DemoPanel crew={crew} />
    </div>
  );
}

