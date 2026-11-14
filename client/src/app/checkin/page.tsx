"use client";

import { useState } from "react";
import { hhmm } from "@/lib/format";
import { useVigil } from "@/lib/store";
import { SCALES, SYMPTOMS } from "@/lib/checkin";

type ScaleKey = (typeof SCALES)[number][0];

export default function CheckinPage() {
  const { checkin } = useVigil();
  // remount the form when a saved entry appears so it starts from that entry
  return <CheckinForm key={checkin?.filedTs ?? "new"} />;
}

function CheckinForm() {
  const { checkin, saveCheckin, today } = useVigil();
  const [vals, setVals] = useState<Record<ScaleKey, number>>(
    checkin ? { sleep: checkin.sleep, mood: checkin.mood, energy: checkin.energy } : { sleep: 3, mood: 3, energy: 3 }
  );
  const [sym, setSym] = useState<string[]>(checkin?.symptoms ?? []);
  const [note, setNote] = useState(checkin?.note ?? "");

  return (
    <section className="page" style={{ maxWidth: 720, gap: 28 }}>
      <div>
        <div className="eyebrow">Daily check-in · about one minute</div>
        <h1 className="h1">How are you today?</h1>
        <p className="lede">Sensors miss what you feel. Your answers are compared with your own earlier entries, not with a crew average.</p>
      </div>
      <div>
        {SCALES.map(([k, label, lo, hi]) => (
          <div key={k} style={{ borderTop: "1px solid var(--color-divider)", padding: "16px 0", display: "flex", gap: 16, alignItems: "center", flexWrap: "wrap" }}>
            <span style={{ fontSize: 15, fontWeight: 500, flex: 1, minWidth: 180 }}>{label}</span>
            <span className="mute" style={{ fontSize: 12 }}>{lo}</span>
            <div style={{ display: "flex", gap: 6 }} role="radiogroup" aria-label={label}>
              {[1, 2, 3, 4, 5].map((n) => {
                const on = vals[k] === n;
                return (
                  <button
                    key={n}
                    role="radio"
                    aria-checked={on}
                    onClick={() => setVals((v) => ({ ...v, [k]: n }))}
                    className="num"
                    style={{
                      width: 38, height: 38, borderRadius: "var(--radius-md)", cursor: "pointer",
                      border: `1px solid ${on ? "var(--color-accent)" : "var(--color-divider)"}`,
                      background: on ? "color-mix(in srgb, var(--color-accent) 14%, transparent)" : "transparent",
                    }}
                  >
                    {n}
                  </button>
                );
              })}
            </div>
            <span className="mute" style={{ fontSize: 12 }}>{hi}</span>
          </div>
        ))}
        <div style={{ borderTop: "1px solid var(--color-divider)", padding: "16px 0", display: "flex", flexDirection: "column", gap: 12 }}>
          <span style={{ fontSize: 15, fontWeight: 500 }}>Anything to note since yesterday?</span>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: "10px 24px" }}>
            {SYMPTOMS.map(([k, label]) => {
              const on = sym.includes(k);
              return (
                <button
                  key={k}
                  role="checkbox"
                  aria-checked={on}
                  onClick={() => setSym((s) => (on ? s.filter((x) => x !== k) : [...s, k]))}
                  style={{ display: "flex", gap: 10, alignItems: "center", background: "none", border: 0, padding: "4px 0", cursor: "pointer", textAlign: "left" }}
                >
                  <span className="check" data-on={on} />
                  <span>{label}</span>
                </button>
              );
            })}
          </div>
        </div>
        <div className="field" style={{ borderTop: "1px solid var(--color-divider)", padding: "16px 0" }}>
          <label htmlFor="ci-note">In your own words (optional)</label>
          <textarea id="ci-note" className="input" value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. Woke twice, stuffy after the reboost" />
        </div>
      </div>
      <div style={{ display: "flex", gap: 16, alignItems: "center", flexWrap: "wrap" }}>
        <button
          className="btn btn-primary"
          disabled={!today}
          onClick={() => saveCheckin({ ...vals, symptoms: sym, note })}
        >
          {checkin ? "Update check-in" : "File check-in"}
        </button>
        <span className="mute" style={{ fontSize: 13 }}>
          {checkin ? `Filed at ${hhmm(checkin.filedTs)} GMT and added to your record.` : ""}
        </span>
      </div>
    </section>
  );
}
