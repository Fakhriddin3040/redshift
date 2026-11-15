import type { Alert, CrewItem, MetricKey, MetricResponse, RadiationResponse, RangeKey, SleepResponse, Today } from "./types";

export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1").replace(/\/$/, "");

export function liveUrl(crew: number): string {
  const u = new URL(`${API_URL}/live`);
  u.protocol = u.protocol === "https:" ? "wss:" : "ws:";
  u.searchParams.set("crew", String(crew));
  return u.toString();
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    cache: "no-store",
    ...init,
    headers: { "content-type": "application/json", ...init?.headers },
  });
  const text = await res.text();
  const body = text ? JSON.parse(text) : null;
  if (!res.ok) {
    const detail = body?.detail ?? res.statusText;
    throw new ApiError(res.status, typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return body as T;
}

export const api = {
  crew: () => request<CrewItem[]>("/crew"),
  today: (crew: number) => request<Today>(`/crew/${crew}/today`),
  metric: (crew: number, m: MetricKey, range: RangeKey) =>
    request<MetricResponse>(`/crew/${crew}/metric/${m}?range=${range}`),
  alerts: (crew: number, openOnly = false) =>
    request<Alert[]>(`/crew/${crew}/alerts${openOnly ? "?open=1" : ""}`),
  sleep: (crew: number) => request<SleepResponse>(`/crew/${crew}/sleep`),
  checkin: (crew: number, body: unknown) =>
    request<{ day: string; filed_ts: number }>(`/crew/${crew}/checkin`, { method: "POST", body: JSON.stringify(body) }),
  radiation: () => request<RadiationResponse>("/radiation"),
  ack: (id: number) => request<Alert>(`/alerts/${id}/ack`, { method: "POST" }),

  simState: () => request<unknown>("/sim/state"),
  simScenario: (body: unknown) => request<unknown>("/sim/scenario", { method: "POST", body: JSON.stringify(body) }),
  simSpeed: (body: unknown) => request<unknown>("/sim/speed", { method: "POST", body: JSON.stringify(body) }),
  simReset: () => request<unknown>("/sim/reset", { method: "POST", body: "{}" }),
};
