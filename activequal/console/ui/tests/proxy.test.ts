import assert from "node:assert/strict";
import { test } from "node:test";
import { proxyRequest, streamCampaignEvents, type ProxyDeps } from "../src/lib/server/proxy.ts";

const TOKEN = "operator-token-SECRET-0123456789abcdef";
const PASS = "reviewer-passphrase-SECRET";

type Seen = { url: string; method: string; headers: Record<string, string>; body: string | undefined };

function deps(respond: (seen: Seen) => Response | Promise<Response>, seen: Seen[] = []): ProxyDeps {
  return {
    baseUrl: "http://cp.test",
    getToken: async () => TOKEN,
    fetchImpl: (async (url: string | URL | Request, init?: RequestInit) => {
      const s: Seen = { url: String(url), method: init?.method ?? "GET", headers: init?.headers as Record<string, string>, body: init?.body as string | undefined };
      seen.push(s);
      return respond(s);
    }) as typeof fetch,
  };
}
const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
const req = (method: string, url: string, init: { actor?: string | null; passphrase?: string; body?: unknown } = {}) => {
  const headers: Record<string, string> = {};
  if (init.actor !== null) headers.cookie = `aq_actor=${encodeURIComponent(init.actor ?? "Ada Lovelace")}`;
  if (init.passphrase) headers["x-console-passphrase"] = init.passphrase;
  return new Request("http://console.test" + url, { method, headers, body: init.body !== undefined ? JSON.stringify(init.body) : undefined });
};

async function everything(res: Response): Promise<string> {
  const headers = [...res.headers.entries()].map(([k, v]) => `${k}: ${v}`).join("\n");
  return headers + "\n" + (await res.text());
}

test("forwards the operator token and actor to the control plane only", async () => {
  const seen: Seen[] = [];
  const res = await proxyRequest(req("GET", "/api/cp/v1/campaigns"), ["v1", "campaigns"], deps(() => json(200, { campaigns: [] }), seen));
  assert.equal(res.status, 200);
  assert.equal(seen[0].url, "http://cp.test/v1/campaigns");
  assert.equal(seen[0].headers["X-ActiveQual-Operator-Token"], TOKEN);
  assert.equal(seen[0].headers["X-ActiveQual-Actor"], "Ada Lovelace");
  assert.equal(seen[0].headers["X-ActiveQual-Reviewer-Passphrase"], undefined);
});

test("neither the operator token nor the passphrase reaches the browser, even when the upstream echoes them", async () => {
  const echoBody = (s: Seen) => json(200, { echoed: s.headers, note: `token ${TOKEN} and ${PASS}` });
  const ok = await proxyRequest(req("POST", "/x", { passphrase: PASS, body: {} }), ["v1", "contracts", "c1", "versions", "1:approve"], deps(echoBody));
  const okText = await everything(ok);
  assert.equal(ok.status, 200);
  assert.ok(!okText.includes(TOKEN), "token in success response");
  assert.ok(!okText.includes(PASS), "passphrase in success response");

  const failing = (s: Seen) => json(403, { error: { code: "PERMISSION_DENIED", message: `bad ${PASS} with ${TOKEN}`, details: { token: TOKEN, trace: "Traceback (most recent call last)" } } });
  const bad = await proxyRequest(req("POST", "/x", { passphrase: PASS, body: {} }), ["v1", "contracts", "c1", "versions", "1:approve"], deps(failing));
  const badText = await everything(bad);
  assert.equal(bad.status, 403);
  assert.ok(!badText.includes(TOKEN) && !badText.includes(PASS), "secret in error response");
  assert.ok(!badText.includes("Traceback"));
  assert.ok(!bad.headers.has("set-cookie"));

  const down = await proxyRequest(req("GET", "/x"), ["v1", "campaigns"], deps(() => { throw new Error(`connect failed with ${TOKEN}`); }));
  const downText = await everything(down);
  assert.equal(down.status, 502);
  assert.ok(!downText.includes(TOKEN));
  assert.match(downText, /bench state unknown/);
});

test("a missing token file yields a UI-safe configuration error and no upstream call", async () => {
  const seen: Seen[] = [];
  const d = deps(() => json(200, {}), seen);
  d.getToken = async () => { const { TokenError } = await import("../src/lib/server/config.ts"); throw new TokenError("no token configured"); };
  const res = await proxyRequest(req("GET", "/x"), ["v1", "campaigns"], d);
  assert.equal(res.status, 500);
  assert.equal(((await res.json()) as { error: { code: string } }).error.code, "CONSOLE_NOT_CONFIGURED");
  assert.equal(seen.length, 0);
});

test("the passphrase is forwarded for reviewer routes only, as a header for that one request", async () => {
  const seen: Seen[] = [];
  const d = deps(() => json(200, { ok: true }), seen);
  await proxyRequest(req("POST", "/x", { passphrase: PASS, body: {} }), ["v1", "campaigns", "c1:clear-lockout"], d);
  assert.equal(seen[0].headers["X-ActiveQual-Reviewer-Passphrase"], PASS);
  await proxyRequest(req("POST", "/x", { passphrase: PASS, body: { campaignVersion: 1 } }), ["v1", "campaigns", "c1:pause"], d);
  assert.equal(seen[1].headers["X-ActiveQual-Reviewer-Passphrase"], undefined, "passphrase leaked to a researcher route");
  assert.ok(!JSON.stringify(seen[1]).includes(PASS));
});

test("reviewer routes without a passphrase never reach the control plane", async () => {
  const seen: Seen[] = [];
  for (const path of [["v1", "fixtures"], ["v1", "contracts", "c", "versions", "2:approve"], ["v1", "fixtures", "f:rotate-token"], ["v1", "leases", "l:reconcile"]]) {
    const res = await proxyRequest(req("POST", "/x", { body: {} }), path, deps(() => json(200, {}), seen));
    assert.equal(res.status, 403);
  }
  assert.equal(seen.length, 0);
});

test("a request without a recorded name is refused locally", async () => {
  const seen: Seen[] = [];
  const res = await proxyRequest(req("GET", "/x", { actor: null }), ["v1", "campaigns"], deps(() => json(200, {}), seen));
  assert.equal(res.status, 401);
  const evil = await proxyRequest(req("GET", "/x", { actor: "bad\nname" }), ["v1", "campaigns"], deps(() => json(200, {}), seen));
  assert.equal(evil.status, 401);
  assert.equal(seen.length, 0);
});

test("only human routes are reachable: no bench, metrics, traversal or wrong methods", async () => {
  const seen: Seen[] = [];
  const d = deps(() => json(200, {}), seen);
  for (const path of [["v1", "bench", "claim"], ["metrics"], ["v1", "..", "bench"], ["v1", "campaigns", "a/b"], []]) {
    const res = await proxyRequest(req("POST", "/x", { body: {} }), path, d);
    assert.ok([404, 405].includes(res.status), path.join("/"));
  }
  assert.equal((await proxyRequest(req("POST", "/x", { body: {} }), ["v1", "episodes", "e1"], d)).status, 405);
  assert.equal(seen.length, 0);
});

test("control-plane errors keep code, message and structured reasons", async () => {
  const body = { error: { code: "FAILED_PRECONDITION", message: "the campaign cannot be armed", details: { reasons: [{ code: "ESTOP_PRESSED", message: "the E-stop is pressed" }], internal: "drop me" } } };
  const res = await proxyRequest(req("POST", "/x", { body: { campaignVersion: 3 } }), ["v1", "campaigns", "c1:arm"], deps(() => json(412, body)));
  assert.equal(res.status, 412);
  const out = (await res.json()) as { error: { code: string; reasons: { code: string }[]; details?: unknown } };
  assert.equal(out.error.code, "FAILED_PRECONDITION");
  assert.equal(out.error.reasons[0].code, "ESTOP_PRESSED");
  assert.equal(out.error.details, undefined);
});

test("503 UNAVAILABLE (export not wired) comes through as a clean error", async () => {
  const res = await proxyRequest(req("GET", "/x"), ["v1", "campaigns", "c1", "export"], deps(() => json(503, { error: { code: "UNAVAILABLE", message: "report export is not configured", details: {} } })));
  assert.equal(res.status, 503);
  assert.equal(((await res.json()) as { error: { code: string } }).error.code, "UNAVAILABLE");
});

test("the event stream is relayed with the token added server-side and never leaked in the stream headers", async () => {
  const seen: Seen[] = [];
  const stream = new Response("id: 1\nevent: campaign\ndata: {\"id\":1}\n\n", { status: 200, headers: { "content-type": "text/event-stream", "x-leak": TOKEN } });
  const res = await streamCampaignEvents(req("GET", "/api/stream/c1?after=4"), "c1", deps(() => stream, seen));
  assert.equal(res.status, 200);
  assert.equal(res.headers.get("content-type"), "text/event-stream");
  assert.equal(seen[0].url, "http://cp.test/v1/campaigns/c1/events?after=4");
  assert.equal(seen[0].headers["X-ActiveQual-Operator-Token"], TOKEN);
  assert.equal(seen[0].headers.accept, "text/event-stream");
  assert.ok(!(await everything(res)).includes(TOKEN));
});

test("an unreachable control plane on the stream route is an explicit unknown-state error", async () => {
  const res = await streamCampaignEvents(req("GET", "/x"), "c1", deps(() => { throw new Error("ECONNREFUSED"); }));
  assert.equal(res.status, 502);
  assert.equal(((await res.json()) as { error: { code: string } }).error.code, "CONTROL_PLANE_UNREACHABLE");
});
