// The only code that talks to the control plane. It runs on the Console server, holds the operator token,
// and hands the browser nothing but translated JSON. Pure over (Request, deps) so tests and the smoke
// script can call it without Next.js.

import { notConfigured, translateError, unreachable } from "../errors.ts";
import type { UiError } from "../types.ts";
import { TokenError } from "./config.ts";

export const OPERATOR_TOKEN_HEADER = "X-ActiveQual-Operator-Token";
export const ACTOR_HEADER = "X-ActiveQual-Actor";
export const PASSPHRASE_HEADER = "X-ActiveQual-Reviewer-Passphrase";
/** Same-origin header the browser uses to hand one reviewer passphrase to this server for one request. */
export const BROWSER_PASSPHRASE_HEADER = "x-console-passphrase";
export const ACTOR_COOKIE = "aq_actor";
export const NAME_PATTERN = /^[A-Za-z0-9][A-Za-z0-9 ._-]{0,59}$/;

export type ProxyDeps = {
  baseUrl: string;
  getToken: () => Promise<string>;
  fetchImpl?: typeof fetch;
  timeoutMs?: number;
};

type Route = { method: string; pattern: RegExp; reviewer: boolean };
const ID = "[^/:]+";
/** Human routes of activequal/service/http_api.py. Bench routes, /metrics and PUT are deliberately absent. */
export const ALLOWED_ROUTES: Route[] = [
  { method: "GET", pattern: /^\/healthz$/, reviewer: false },
  { method: "POST", pattern: /^\/v1\/contracts$/, reviewer: false },
  { method: "POST", pattern: new RegExp(`^/v1/contracts/${ID}/versions/\\d+:approve$`), reviewer: true },
  { method: "GET", pattern: new RegExp(`^/v1/contracts/${ID}/versions/\\d+$`), reviewer: false },
  { method: "POST", pattern: /^\/v1\/fixtures$/, reviewer: true },
  { method: "GET", pattern: new RegExp(`^/v1/fixtures/${ID}$`), reviewer: false },
  { method: "POST", pattern: new RegExp(`^/v1/fixtures/${ID}/calibrations$`), reviewer: false },
  { method: "POST", pattern: new RegExp(`^/v1/fixtures/${ID}:rotate-token$`), reviewer: true },
  { method: "POST", pattern: /^\/v1\/campaigns$/, reviewer: false },
  { method: "GET", pattern: /^\/v1\/campaigns$/, reviewer: false },
  { method: "POST", pattern: new RegExp(`^/v1/campaigns/${ID}:clear-lockout$`), reviewer: true },
  { method: "POST", pattern: new RegExp(`^/v1/campaigns/${ID}:(validate|arm|start|pause|resume|abort|disarm)$`), reviewer: false },
  { method: "GET", pattern: new RegExp(`^/v1/campaigns/${ID}$`), reviewer: false },
  { method: "POST", pattern: new RegExp(`^/v1/campaigns/${ID}/manual-candidates$`), reviewer: false },
  { method: "GET", pattern: new RegExp(`^/v1/campaigns/${ID}/events$`), reviewer: false },
  { method: "GET", pattern: new RegExp(`^/v1/campaigns/${ID}/(episodes|counterexamples|export)$`), reviewer: false },
  { method: "GET", pattern: new RegExp(`^/v1/episodes/${ID}$`), reviewer: false },
  { method: "POST", pattern: new RegExp(`^/v1/leases/${ID}:reconcile$`), reviewer: true },
  { method: "POST", pattern: /^\/v1\/proposals$/, reviewer: false },
];

const SEGMENT = /^[A-Za-z0-9._:-]+$/;
const MAX_BODY = 2_000_000;

export function jsonResponse(status: number, body: unknown): Response {
  return new Response(status === 204 ? null : JSON.stringify(body), {
    status,
    headers: status === 204 ? { "cache-control": "no-store" } : { "content-type": "application/json", "cache-control": "no-store" },
  });
}
export const errorResponse = (error: UiError): Response => jsonResponse(error.status || 502, { error });

export function actorFromRequest(request: Request): string | null {
  const cookie = request.headers.get("cookie") ?? "";
  for (const part of cookie.split(";")) {
    const index = part.indexOf("=");
    if (index < 0 || part.slice(0, index).trim() !== ACTOR_COOKIE) continue;
    let value: string;
    try { value = decodeURIComponent(part.slice(index + 1).trim()); } catch { return null; }
    return NAME_PATTERN.test(value) ? value : null;
  }
  return null;
}

function redact(text: string, secrets: string[]): string {
  let out = text;
  for (const secret of secrets) if (secret.length >= 6) out = out.split(secret).join("[redacted]");
  return out;
}

const NO_ACTOR: UiError = {
  code: "UNAUTHENTICATED", status: 401,
  message: "Enter your name in the box at the top of the page first. ActiveQual records who did each action (letters, digits, space . _ -).",
};

/** Resolve a request's secrets and build the control-plane call. Returns an error response instead of throwing. */
async function prepare(request: Request, reviewer: boolean, deps: ProxyDeps):
  Promise<{ headers: Record<string, string>; secrets: string[] } | Response> {
  const actor = actorFromRequest(request);
  if (!actor) return errorResponse(NO_ACTOR);
  const passphrase = request.headers.get(BROWSER_PASSPHRASE_HEADER) ?? "";
  if (reviewer && !passphrase) {
    return errorResponse({ code: "PERMISSION_DENIED", status: 403, message: "This action needs the reviewer passphrase." });
  }
  let token: string;
  try { token = await deps.getToken(); }
  catch (e) { return errorResponse(notConfigured(e instanceof TokenError ? e.message : "The Console server could not load the operator token.")); }
  const headers: Record<string, string> = { [OPERATOR_TOKEN_HEADER]: token, [ACTOR_HEADER]: actor };
  const secrets = [token];
  if (reviewer) { headers[PASSPHRASE_HEADER] = passphrase; secrets.push(passphrase); }
  return { headers, secrets };
}

export async function proxyRequest(request: Request, segments: string[], deps: ProxyDeps): Promise<Response> {
  if (!segments.length || !segments.every(s => SEGMENT.test(s) && s !== "." && s !== "..")) {
    return errorResponse({ code: "NOT_FOUND", status: 404, message: "Unknown Console API path." });
  }
  const path = "/" + segments.join("/");
  const method = request.method.toUpperCase();
  const route = ALLOWED_ROUTES.find(r => r.pattern.test(path) && r.method === method);
  if (!route) {
    const known = ALLOWED_ROUTES.some(r => r.pattern.test(path));
    return errorResponse({ code: known ? "METHOD_NOT_ALLOWED" : "NOT_FOUND", status: known ? 405 : 404, message: known ? "Method not allowed here." : "Unknown Console API path." });
  }
  const prepared = await prepare(request, route.reviewer, deps);
  if (prepared instanceof Response) return prepared;

  let body: string | undefined;
  if (method === "POST") {
    body = await request.text();
    if (body.length > MAX_BODY) return errorResponse({ code: "INVALID_ARGUMENT", status: 400, message: "Request body is too large." });
  }
  const url = new URL(request.url);
  const after = url.searchParams.get("after");
  const query = after !== null && /^\d+$/.test(after) ? `?after=${after}` : "";
  const doFetch = deps.fetchImpl ?? fetch;
  let upstream: Response;
  try {
    upstream = await doFetch(deps.baseUrl + path + query, {
      method,
      headers: { ...prepared.headers, ...(body !== undefined ? { "content-type": "application/json" } : {}), accept: "application/json" },
      body,
      cache: "no-store",
      signal: AbortSignal.timeout(deps.timeoutMs ?? 15_000),
    });
  } catch {
    return errorResponse(unreachable());
  }

  const text = redact(await upstream.text().catch(() => ""), prepared.secrets);
  let parsed: unknown = null;
  if (text) { try { parsed = JSON.parse(text); } catch { parsed = undefined; } }
  if (!upstream.ok) return errorResponse(translateError(upstream.status, parsed));
  if (upstream.status === 204) return jsonResponse(204, null);
  if (parsed === undefined) return errorResponse({ code: "INTERNAL", status: 502, message: "The control plane sent a response the Console cannot read." });
  return jsonResponse(upstream.status, parsed);
}

/** Relay the control plane's server-sent events for one campaign (HLD 09 §7). */
export async function streamCampaignEvents(request: Request, campaignId: string, deps: ProxyDeps): Promise<Response> {
  if (!/^[A-Za-z0-9._-]+$/.test(campaignId)) return errorResponse({ code: "NOT_FOUND", status: 404, message: "Unknown campaign." });
  const prepared = await prepare(request, false, deps);
  if (prepared instanceof Response) return prepared;
  const after = new URL(request.url).searchParams.get("after");
  const query = after !== null && /^\d+$/.test(after) ? `?after=${after}` : "";
  const doFetch = deps.fetchImpl ?? fetch;
  let upstream: Response;
  try {
    upstream = await doFetch(`${deps.baseUrl}/v1/campaigns/${campaignId}/events${query}`, {
      headers: { ...prepared.headers, accept: "text/event-stream" }, cache: "no-store", signal: request.signal,
    });
  } catch {
    return errorResponse(unreachable());
  }
  if (!upstream.ok || !upstream.body) {
    const text = await upstream.text().catch(() => "");
    let parsed: unknown = null;
    try { parsed = text ? JSON.parse(text) : null; } catch { parsed = null; }
    return errorResponse(translateError(upstream.status || 502, parsed));
  }
  return new Response(upstream.body, {
    status: 200,
    headers: { "content-type": "text/event-stream", "cache-control": "no-cache, no-transform", "x-accel-buffering": "no" },
  });
}

