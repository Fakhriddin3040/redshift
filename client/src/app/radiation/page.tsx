"use client";

// DESIGN_TZ §9.1. The backend stores `radiation_daily` but has no /radiation
// endpoint yet (IMPLEMENTATION §21, BE-7), so tiles and chart show empty states.

const TILES = ["Last 24 hours", "Mean, last 14 days", "Total, last 14 days"];

export default function RadiationPage() {
  return (
    <section className="page">
      <div>
        <div className="eyebrow">Station dosimeter · ISS · NASA OSDR RadLab</div>
        <h1 className="h1">Radiation</h1>
        <p className="lede">Dose on station runs many times higher than on the ground. Days with more South Atlantic Anomaly passes read higher.</p>
      </div>
      <div className="tiles">
        {TILES.map((k) => (
          <div key={k} className="tile">
            <div className="k">{k}</div>
            <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
              <span className="v mute">—</span>
              <span className="mute" style={{ fontSize: 12 }}>mGy</span>
            </div>
            <div className="n">No station data yet</div>
          </div>
        ))}
      </div>
      <div>
        <h2 className="h2" style={{ marginBottom: 12 }}>Daily dose, last fourteen days</h2>
        <div style={{ height: 160, borderBottom: "1px solid var(--color-text)", display: "grid", placeItems: "center" }}>
          <span className="mute" style={{ fontSize: 13 }}>No readings in this period.</span>
        </div>
        <p className="foot-note" style={{ marginTop: 10 }}>mGy per day · absorbed dose · days with more South Atlantic Anomaly passes read higher</p>
      </div>
    </section>
  );
}
