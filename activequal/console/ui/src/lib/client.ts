// Browser-side client for the Console's own /api/cp routes. It never sees the operator token. A reviewer passphrase
// is accepted as a call argument, copied into one request header, and not kept anywhere: no cookie, no storage, no state.

import { consoleUnreachable } from "./errors.ts";
import type { ApiResult, UiError } from "./types.ts";

export const API_PREFIX = "/api/cp";
export const PASSPHRASE_HEADER = "x-console-passphrase";

export type CallOptions = {
  method?: "GET" | "POST";
  body?: unknown;
  /** Reviewer passphrase for THIS request only. */
  passphrase?: string;
  signal?: AbortSignal;
  fetchImpl?: typeof fetch;
};

function isUiError(v: unknown): v is UiError {
  return typeof v === "object" && v !== null && typeof (v as UiError).code === "string" && typeof (v as UiError).message === "string";
}

export async function callApi<T>(path: string, options: CallOptions = {}): Promise<ApiResult<T>> {
  const headers: Record<string, string> = {};
  if (options.body !== undefined) headers["content-type"] = "application/json";
  if (options.passphrase) headers[PASSPHRASE_HEADER] = options.passphrase;
  let response: Response;
  try {
    response = await (options.fetchImpl ?? fetch)(API_PREFIX + path, {
      method: options.method ?? (options.body !== undefined ? "POST" : "GET"),
      headers,
      body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
      cache: "no-store",
      credentials: "same-origin",
      signal: options.signal,
    });
  } catch {
    return { ok: false, error: consoleUnreachable() };
  }
  let parsed: unknown = null;
  const text = await response.text().catch(() => "");
  if (text) { try { parsed = JSON.parse(text); } catch { parsed = null; } }
  if (response.ok) return { ok: true, data: parsed as T };
  const err = typeof parsed === "object" && parsed !== null ? (parsed as { error?: unknown }).error : null;
  if (isUiError(err)) return { ok: false, error: err };
  return { ok: false, error: { code: "INTERNAL", status: response.status, message: "The Console server returned an unreadable error." } };
}

export const path = {
  campaigns: () => "/v1/campaigns",
  campaign: (id: string) => `/v1/campaigns/${encodeURIComponent(id)}`,
  action: (id: string, action: string) => `/v1/campaigns/${encodeURIComponent(id)}:${action}`,
  events: (id: string, after = 0) => `/v1/campaigns/${encodeURIComponent(id)}/events?after=${after}`,
  episodes: (id: string) => `/v1/campaigns/${encodeURIComponent(id)}/episodes`,
  counterexamples: (id: string) => `/v1/campaigns/${encodeURIComponent(id)}/counterexamples`,
  manual: (id: string) => `/v1/campaigns/${encodeURIComponent(id)}/manual-candidates`,
  exportBundle: (id: string) => `/v1/campaigns/${encodeURIComponent(id)}/export`,
  episode: (id: string) => `/v1/episodes/${encodeURIComponent(id)}`,
  contract: (id: string, version: number) => `/v1/contracts/${encodeURIComponent(id)}/versions/${version}`,
  approve: (id: string, version: number) => `/v1/contracts/${encodeURIComponent(id)}/versions/${version}:approve`,
  fixture: (id: string) => `/v1/fixtures/${encodeURIComponent(id)}`,
  calibrations: (id: string) => `/v1/fixtures/${encodeURIComponent(id)}/calibrations`,
  rotate: (id: string) => `/v1/fixtures/${encodeURIComponent(id)}:rotate-token`,
  reconcile: (leaseId: string) => `/v1/leases/${encodeURIComponent(leaseId)}:reconcile`,
};

// ---- the operator's name: a plain cookie, not a secret (HLD 07: shared account, recorded name per action) ----

export const ACTOR_COOKIE = "aq_actor";
export const ACTOR_PATTERN = /^[A-Za-z0-9][A-Za-z0-9 ._-]{0,59}$/;

export function actorCookie(name: string): string | null {
  const trimmed = name.trim();
  if (!ACTOR_PATTERN.test(trimmed)) return null;
  return `${ACTOR_COOKIE}=${encodeURIComponent(trimmed)}; Path=/; SameSite=Strict; Max-Age=31536000`;
}

export function readActor(cookieString: string): string {
  for (const part of cookieString.split(";")) {
    const i = part.indexOf("=");
    if (i > 0 && part.slice(0, i).trim() === ACTOR_COOKIE) {
      try { return decodeURIComponent(part.slice(i + 1).trim()); } catch { return ""; }
    }
  }
  return "";
}
