"use client";

import { API_URL } from "@/lib/api";
import { useVigil } from "@/lib/store";

export function Loading() {
  const { error } = useVigil();
  return (
    <section className="page">
      <div>
        <div className="eyebrow">Vigil</div>
        <h1 className="h1">{error ? "No connection to the server." : "Connecting…"}</h1>
        <p className="lede">
          {error
            ? `Vigil could not reach ${API_URL}. It keeps trying every few seconds. (${error})`
            : "Reading your record from the station server."}
        </p>
      </div>
    </section>
  );
}
