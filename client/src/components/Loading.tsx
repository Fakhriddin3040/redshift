"use client";

import { useI18n } from "@/i18n";
import { API_URL } from "@/lib/api";
import { useVigil } from "@/lib/store";

export function Loading() {
  const { error } = useVigil();
  const { t } = useI18n();
  return (
    <section className="page">
      <div>
        <div className="eyebrow">Vigil</div>
        <h1 className="h1">{error ? t.loading.noConnection : t.loading.connecting}</h1>
        <p className="lede">
          {error ? t.loading.cannotReach(API_URL, error) : t.loading.reading}
        </p>
      </div>
    </section>
  );
}
