"use client";

import { useEffect, useRef, useState } from "react";
import { useI18n } from "@/i18n";
import { api } from "@/lib/api";
import { useVigil } from "@/lib/store";
import type { AskAnswer, AskTurn } from "@/lib/types";

// Ask Vigil: questions about the crew member's own record (POST /crew/{id}/ask).
// The server answers only from that record and checks every number in the answer;
// when the check fails it sends a fixed sentence instead (src "none").

const MAX_QUESTION = 300; // same limit as the server
const HISTORY_PAIRS = 3;

interface Exchange {
  id: number;
  question: string;
  reply: AskAnswer | null; // null while waiting
  error?: string;
}

export function AskPanel({ hidden = false }: { hidden?: boolean }) {
  const { crewId } = useVigil();
  const { t } = useI18n();
  const [available, setAvailable] = useState(false);
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  // Kept with the crew member they belong to, so a change of crew starts empty.
  const [log, setLog] = useState<{ crew: number; items: Exchange[] }>({ crew: crewId, items: [] });
  const nextId = useRef(1);
  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const items = log.crew === crewId ? log.items : [];
  const busy = items.some((x) => x.reply === null && !x.error);

  useEffect(() => {
    let alive = true;
    api
      .health()
      .then((h) => alive && setAvailable(h.ask === true))
      .catch(() => alive && setAvailable(false));
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    if (open) endRef.current?.scrollIntoView({ block: "end" });
  }, [open, items.length, busy]);

  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  if (!available || hidden) return null;

  const patch = (crew: number, id: number, change: Partial<Exchange>) =>
    setLog((prev) =>
      prev.crew === crew ? { crew, items: prev.items.map((x) => (x.id === id ? { ...x, ...change } : x)) } : prev
    );

  const send = async (raw: string) => {
    const question = raw.replace(/\s+/g, " ").trim();
    if (!question || busy) return;
    // Only answers that passed the server's check are sent back as context.
    const history: AskTurn[] = items
      .filter((x) => x.reply?.src === "llm")
      .slice(-HISTORY_PAIRS)
      .flatMap((x) => [
        { role: "user" as const, content: x.question },
        { role: "assistant" as const, content: x.reply!.answer },
      ]);
    const id = nextId.current++;
    const crew = crewId;
    setLog({ crew, items: [...items, { id, question, reply: null }] });
    setText("");
    try {
      patch(crew, id, { reply: await api.ask(crew, question, history) });
    } catch (e) {
      patch(crew, id, { error: e instanceof Error ? e.message : String(e) });
    }
  };

  return (
    <>
      <button
        className="btn btn-secondary ask-toggle"
        aria-expanded={open}
        aria-controls="ask-panel"
        onClick={() => setOpen(!open)}
      >
        {open ? t.ask.close : t.ask.open}
      </button>
      {open && (
        <div className="ask" id="ask-panel" role="dialog" aria-label={t.ask.title}>
          <div>
            <div className="h2">{t.ask.title}</div>
            <div className="mute" style={{ fontSize: 12 }}>
              {t.ask.disclaimer}
            </div>
          </div>

          <div className="ask-log" aria-live="polite">
            {items.length === 0 && (
              <div className="ask-suggest">
                {t.ask.suggestions.map((s) => (
                  <button key={s} className="btn btn-text" onClick={() => void send(s)}>
                    {s}
                  </button>
                ))}
              </div>
            )}
            {items.map((x) => (
              <div key={x.id} className="ask-turn">
                <div className="q">{x.question}</div>
                {x.error ? (
                  <div className="a offline">{t.ask.couldNotAsk(x.error)}</div>
                ) : x.reply === null ? (
                  <div className="a mute">{t.ask.reading}</div>
                ) : (
                  <>
                    <div className={x.reply.src === "llm" ? "a" : "a mute"}>{x.reply.answer}</div>
                    {x.reply.src === "llm" && (
                      <div className="src">{t.ask.byModel}</div>
                    )}
                  </>
                )}
              </div>
            ))}
            <div ref={endRef} />
          </div>

          <form
            className="ask-form"
            onSubmit={(e) => {
              e.preventDefault();
              void send(text);
            }}
          >
            <label htmlFor="ask-input" className="sr-only">
              {t.ask.yourQuestion}
            </label>
            <input
              id="ask-input"
              ref={inputRef}
              className="input"
              value={text}
              maxLength={MAX_QUESTION}
              placeholder={t.ask.placeholder}
              autoComplete="off"
              onChange={(e) => setText(e.target.value)}
            />
            <button className="btn btn-primary" type="submit" disabled={busy || !text.trim()}>
              {t.ask.send}
            </button>
          </form>
        </div>
      )}
    </>
  );
}
