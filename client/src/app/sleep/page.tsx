"use client";

// The backend has no sleep endpoint yet (IMPLEMENTATION §21, BE-6a): data blocks
// show the empty states from DESIGN_TZ §11; the evening advice is static guidance.

const TONIGHT = [
  ["16:00", "Finish exercise. Late sessions push sleep onset back."],
  ["20:00", "Switch crew-quarters lighting to the warm pre-sleep setting."],
  ["21:00", "Screens off, window shades closed."],
  ["06:00", "Bright, blue-enriched light for the first hour awake."],
];

export default function SleepPage() {
  return (
    <section className="page">
      <div>
        <div className="eyebrow">Sleep and circadian rhythm</div>
        <h1 className="h1">No nights recorded yet.</h1>
        <p className="lede">With sixteen sunrises a day, cabin light is the main cue your body gets. Once the wristband has recorded a night, it is shown here against the schedule.</p>
      </div>
      <div>
        <h2 className="h2" style={{ marginBottom: 12 }}>Last night against the schedule</h2>
        <div className="dayband" style={{ height: 64, display: "grid", placeItems: "center" }}>
          <span className="mute" style={{ fontSize: 13 }}>No nights recorded yet.</span>
        </div>
        <div className="axis"><span>18:00</span><span>22:00</span><span>02:00</span><span>06:00</span><span>10:00</span></div>
      </div>
      <div className="cols">
        <div>
          <h2 className="h2" style={{ marginBottom: 12 }}>Seven nights</h2>
          <div className="empty mute">No nights recorded yet.</div>
        </div>
        <div>
          <h2 className="h2" style={{ marginBottom: 4 }}>For tonight</h2>
          {TONIGHT.map(([t, s]) => (
            <div key={t} style={{ borderTop: "1px solid var(--color-divider)", padding: "12px 0", display: "flex", gap: 16, alignItems: "baseline" }}>
              <span className="num kick" style={{ width: 52, flex: "none" }}>{t}</span>
              <span>{s}</span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
