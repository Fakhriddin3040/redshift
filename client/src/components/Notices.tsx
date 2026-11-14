"use client";

import Link from "next/link";
import { useState } from "react";
import { hhmm } from "@/lib/format";
import { useVigil } from "@/lib/store";
import { noticeText } from "@/lib/text";

export function Notices() {
  const { today, ack } = useVigil();
  const [busy, setBusy] = useState<number | null>(null);
  if (!today) return null;
  const list = [...today.notices].sort((a, b) => Number(a.ack_ts != null) - Number(b.ack_ts != null));

  return (
    <div>
      <h2 className="h2" style={{ marginBottom: 4 }}>Notices</h2>
      {list.length === 0 && (
        <div className="empty">
          <div>Nothing needs your attention.</div>
          <div className="mute" style={{ fontSize: 13 }}>Checked at {hhmm(today.now_ts)} GMT.</div>
        </div>
      )}
      {list.map((n) => {
        const t = noticeText(n, today);
        const acked = n.ack_ts != null;
        return (
          <div key={n.id} className="notice" data-acked={acked}>
            <span className="lvl" style={{ color: t.tone }}>{t.label}</span>
            <span className="title">{t.title}</span>
            <span className="body">{t.body}</span>
            {t.explained && <span className="src">Explained on board</span>}
            <div className="actions">
              {t.action && <Link className="btn btn-primary" href={t.action.href}>{t.action.label}</Link>}
              <button
                className="btn btn-text"
                disabled={acked || busy === n.id}
                onClick={async () => {
                  setBusy(n.id);
                  try {
                    await ack(n.id);
                  } finally {
                    setBusy(null);
                  }
                }}
              >
                {acked ? "Acknowledged" : "Acknowledge"}
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}
