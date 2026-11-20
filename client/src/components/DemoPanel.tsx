"use client";

import { useState } from "react";
import { useI18n } from "@/i18n";
import { api } from "@/lib/api";
import { useVigil } from "@/lib/store";
import type { CrewItem } from "@/lib/types";

// Demo controls (DESIGN_TZ §14: built from existing components, no mock-up).
// Talks to /sim/* which the backend forwards to the virtual device.

function scenariosFrom(state: unknown): string[] {
  if (state && typeof state === "object") {
    const s = state as Record<string, unknown>;
    const list = s.scenarios ?? s.available ?? s.options;
    if (Array.isArray(list)) return list.map((x) => (typeof x === "string" ? x : String((x as { name?: string }).name ?? x)));
  }
  return [];
}

export function DemoPanel({ crew }: { crew: CrewItem[] }) {
  const { crewId, setCrewId, refresh } = useVigil();
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const [state, setState] = useState<unknown>(null);
  const [msg, setMsg] = useState<string>("");
  const [scenario, setScenario] = useState("");
  const [speed, setSpeed] = useState("1");

  const load = async () => {
    try {
      setState(await api.simState());
      setMsg("");
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    }
  };

  const run = async (fn: () => Promise<unknown>, done: string) => {
    setMsg("…");
    try {
      await fn();
      setMsg(done);
      await Promise.all([load(), refresh()]);
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    }
  };

  const options = scenariosFrom(state);

  return (
    <>
      <button className="btn btn-secondary demo-toggle" onClick={() => {
          if (!open) void load();
          setOpen(!open);
        }}>
        {open ? t.demo.close : t.demo.open}
      </button>
      {open && (
        <div className="demo" role="dialog" aria-label={t.demo.aria}>
          <div className="field">
            <label htmlFor="demo-crew">{t.demo.crewmember}</label>
            <select id="demo-crew" className="input" value={crewId} onChange={(e) => setCrewId(Number(e.target.value))}>
              {(crew.length ? crew : [{ id: crewId, name: t.demo.crewN(crewId) } as CrewItem]).map((c) => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="demo-scn">{t.demo.scenario}</label>
            <div className="row">
              {options.length ? (
                <select id="demo-scn" className="input" style={{ flex: 1 }} value={scenario} onChange={(e) => setScenario(e.target.value)}>
                  <option value="">{t.demo.choose}</option>
                  {options.map((o) => <option key={o} value={o}>{o}</option>)}
                </select>
              ) : (
                <input id="demo-scn" className="input" style={{ flex: 1 }} value={scenario} placeholder={t.demo.placeholder} onChange={(e) => setScenario(e.target.value)} />
              )}
              <button
                className="btn btn-primary"
                disabled={!scenario}
                onClick={() => run(() => api.simScenario({ crew: crewId, name: scenario, scenario }), t.demo.sent(scenario))}
              >
                {t.demo.run}
              </button>
            </div>
          </div>
          <div className="field">
            <label>{t.demo.speed}</label>
            <div className="row">
              <div className="seg">
                {["1", "10", "60"].map((s) => (
                  <button key={s} aria-pressed={speed === s} onClick={() => { setSpeed(s); void run(() => api.simSpeed({ speed: Number(s) }), t.demo.speedSet(s)); }}>
                    ×{s}
                  </button>
                ))}
              </div>
              <button className="btn btn-text" onClick={() => run(() => api.simReset(), t.demo.resetDone)}>{t.demo.reset}</button>
            </div>
          </div>
          {msg && <div className="mute" style={{ fontSize: 12 }}>{msg}</div>}
          {state != null && <pre>{JSON.stringify(state, null, 1)}</pre>}
        </div>
      )}
    </>
  );
}
