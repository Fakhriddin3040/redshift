"use client";

// UI language. To add a locale: copy ./en.ts to ./<code>.ts, translate it
// (typed as `Dict`, so a missing key fails the build) and add it to LOCALES.

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { en, type Dict } from "./en";
import { ru } from "./ru";

export type { Dict } from "./en";

export const LOCALES = { en, ru } satisfies Record<string, Dict>;
export type Locale = keyof typeof LOCALES;

const DEFAULT_LOCALE: Locale = "en";
const STORAGE_KEY = "vigil.locale";

const isLocale = (s: unknown): s is Locale => typeof s === "string" && s in LOCALES;

interface I18nState {
  locale: Locale;
  setLocale: (l: Locale) => void;
  t: Dict;
}

const Ctx = createContext<I18nState | null>(null);

export function I18nProvider({ children }: { children: React.ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(DEFAULT_LOCALE);

  useEffect(() => {
    // localStorage and navigator are only readable after hydration
    let saved: string | null = null;
    try {
      saved = localStorage.getItem(STORAGE_KEY);
    } catch {
      /* storage unavailable */
    }
    const browser = navigator.languages?.map((l) => l.slice(0, 2)).find(isLocale);
    const next = isLocale(saved) ? saved : browser ?? DEFAULT_LOCALE;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (next !== DEFAULT_LOCALE) setLocaleState(next);
  }, []);

  useEffect(() => {
    document.documentElement.lang = locale;
  }, [locale]);

  const setLocale = useCallback((l: Locale) => {
    try {
      localStorage.setItem(STORAGE_KEY, l);
    } catch {
      /* keep in memory only */
    }
    setLocaleState(l);
  }, []);

  const value = useMemo<I18nState>(() => ({ locale, setLocale, t: LOCALES[locale] }), [locale, setLocale]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useI18n(): I18nState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useI18n outside I18nProvider");
  return v;
}
