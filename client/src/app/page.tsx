"use client";

import Link from "next/link";
import { Notices } from "@/components/Notices";
import { VitalCard } from "@/components/VitalCard";
import { ctxWord, greeting, hhmm, longDate } from "@/lib/format";
import { useVigil } from "@/lib/store";
import { lede } from "@/lib/text";
import type { Today } from "@/lib/types";
import { Loading } from "@/components/Loading";

function liveLabel(t: Today): string {
  const d = t.device;
  if (d.link === "no_link") return "No link to wristband · showing last values";
  if (d.worn === false) return "Wristband not worn";
  return `Live from wristband · signal ${d.signal ?? "—"} · ${ctxWord(t.ctx)}`;
}

function LearningBar({ t }: { t: Today }) {
  if (t.baseline.state !== "learning") return null;
  return (
    <div className="learn">
      <div className="segs" aria-hidden>
        {Array.from({ length: t.baseline.of }, (_, i) => <span key={i} data-on={i < t.baseline.day} />)}
      </div>
      <span className="mute num" style={{ fontSize: 12 }}>
        Learning your baseline · day {t.baseline.day} of {t.baseline.of}
      </span>
    </div>
  );
}

export default function TodayPage() {
  const { today, checkin, report } = useVigil();
  if (!today) return <Loading />;

  const record = [
    {
      k: "Check-in",
      v: checkin ? `Filed at ${hhmm(checkin.filedTs)}` : "Not yet filed",
      n: checkin ? `Sleep ${checkin.sleep} · mood ${checkin.mood} · energy ${checkin.energy}` : "About one minute",
      href: "/checkin",
    },
    { k: "Sleep", v: "No nights recorded yet", n: "", href: "/sleep" },
    {
      k: "Baseline",
      v: today.baseline.state === "learned" ? "Learned" : "Learning",
      n: today.baseline.state === "learned" ? `${today.baseline.ready_pct ?? 100} % of cells ready` : `Day ${today.baseline.day} of ${today.baseline.of}`,
      href: null,
    },
    { k: "Radiation", v: "No station data yet", n: "NASA OSDR RadLab", href: "/radiation" },
    { k: "Report", v: report.queued ? "Queued for next signal" : "Not yet sent", n: "", href: "/report" },
  ];

  return (
    <section className="page">
      <div>
        <div className="eyebrow">{longDate(today.now_ts)}</div>
        <h1 className="h1">{greeting(today.now_ts)}.</h1>
        <p className="lede">{lede(today)}</p>
      </div>

      <LearningBar t={today} />

      <div>
        <div className="block-head">
          <h2 className="h2">Vital signs</h2>
          <span className="mute" style={{ fontSize: 12 }}>{liveLabel(today)}</span>
        </div>
        <div className="vitals-panel">
          <div className="vitals-row">
            <span className="row-label">You</span>
            <div className="cards">
              {today.vitals.map((c) => <VitalCard key={c.m} card={c} today={today} />)}
            </div>
          </div>
          <div className="vitals-row">
            <span className="row-label">Cabin air</span>
            <div className="cards">
              {today.cabin.map((c) => <VitalCard key={c.m} card={c} today={today} />)}
            </div>
          </div>
        </div>
      </div>

      <div className="cols">
        <Notices />
        <div>
          <h2 className="h2" style={{ marginBottom: 4 }}>The day’s record</h2>
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
