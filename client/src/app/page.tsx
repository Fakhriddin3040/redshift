"use client";

import Link from "next/link";
import { Notices } from "@/components/Notices";
import { VitalCard } from "@/components/VitalCard";
import { useI18n, type Dict } from "@/i18n";
import { ctxWord, greeting, hhmm, longDate } from "@/lib/format";
import { useVigil } from "@/lib/store";
import { lede } from "@/lib/text";
import type { Today } from "@/lib/types";
import { Loading } from "@/components/Loading";

function liveLabel(today: Today, t: Dict): string {
  const d = today.device;
  if (d.link === "no_link") return t.today.liveNoLink;
  if (d.worn === false) return t.today.liveNotWorn;
  // "off" is the state of the last full minute; the wristband may be on again by now.
  const state = today.ctx === "off" ? null : ctxWord(today.ctx, t);
  return t.today.live(d.signal ? t.signalLower[d.signal] : "—", state);
}

function LearningBar({ today: t }: { today: Today }) {
  const { t: tr } = useI18n();
  if (t.baseline.state !== "learning") return null;
  return (
    <div className="learn">
      <div className="segs" aria-hidden>
        {Array.from({ length: t.baseline.of }, (_, i) => <span key={i} data-on={i < t.baseline.day} />)}
      </div>
      <span className="mute num" style={{ fontSize: 12 }}>
        {tr.today.learningBaseline(t.baseline.day, t.baseline.of)}
      </span>
    </div>
  );
}

export default function TodayPage() {
  const { today, checkin, report } = useVigil();
  const { t } = useI18n();
  if (!today) return <Loading />;
  const d = t.today;

  const record = [
    {
      k: d.checkin,
      v: checkin ? d.filedAt(hhmm(checkin.filedTs)) : d.notFiled,
      n: checkin ? d.checkinSummary(checkin.sleep, checkin.mood, checkin.energy) : d.aboutMinute,
      href: "/checkin",
    },
    {
      k: d.sleep,
      v: today.record.sleep ? d.lastNight(t.minutes(today.record.sleep.asleep_min)) : d.noNights,
      n: today.record.sleep ? `${hhmm(today.record.sleep.onset_ts)}–${hhmm(today.record.sleep.wake_ts)}` : "",
      href: "/sleep",
    },
    {
      k: d.baseline,
      v: today.baseline.state === "learned" ? d.learned : d.learning,
      n: today.baseline.state === "learned" ? d.cellsReady(today.baseline.ready_pct ?? 100) : d.dayOf(today.baseline.day, today.baseline.of),
      href: null,
    },
    {
      k: d.radiation,
      v: today.record.radiation ? d.perDay(today.record.radiation.total.toFixed(2)) : d.noStation,
      n: today.record.radiation ? d.radiationSource : d.radiationApp,
      href: "/radiation",
    },
    { k: d.report, v: report.queued ? d.queued : d.notSent, n: "", href: "/report" },
  ];

  return (
    <section className="page">
      <div>
        <div className="eyebrow">{longDate(today.now_ts, t)}</div>
        <h1 className="h1">{greeting(today.now_ts, t)}.</h1>
        <p className="lede">{lede(today, t)}</p>
      </div>

      <LearningBar today={today} />

      <div>
        <div className="block-head">
          <h2 className="h2">{d.vitalSigns}</h2>
          <span className="mute" style={{ fontSize: 12 }}>{liveLabel(today, t)}</span>
        </div>
        <div className="vitals-panel">
          <div className="vitals-row">
            <span className="row-label">{d.you}</span>
            <div className="cards">
              {today.vitals.map((c) => <VitalCard key={c.m} card={c} today={today} />)}
            </div>
          </div>
          <div className="vitals-row">
            <span className="row-label">{d.cabinAir}</span>
            <div className="cards">
              {today.cabin.map((c) => <VitalCard key={c.m} card={c} today={today} />)}
            </div>
          </div>
        </div>
      </div>

      <div className="cols">
        <Notices />
        <div>
          <h2 className="h2" style={{ marginBottom: 4 }}>{d.record}</h2>
          {record.map((r) =>
            r.href ? (
              <Link key={r.k} href={r.href} className="record-row">
                <span className="k">{r.k}</span>
                <span className="v">{r.v}</span>
                <span className="n">{r.n}</span>
              </Link>
            ) : (
              <div key={r.k} className="record-row">
                <span className="k">{r.k}</span>
                <span className="v">{r.v}</span>
                <span className="n">{r.n}</span>
              </div>
            )
          )}
        </div>
      </div>
    </section>
  );
}
