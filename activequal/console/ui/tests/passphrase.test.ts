import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { actorCookie, callApi, readActor } from "../src/lib/client.ts";

const PASS = "correct horse battery staple";

test("callApi puts the passphrase in one request header and writes it nowhere else", async () => {
  const writes: string[] = [];
  const spy = (name: string) => ({ setItem: (k: string, v: string) => writes.push(`${name}:${k}=${v}`), getItem: () => null, removeItem() {} });
  const g = globalThis as Record<string, unknown>;
  const saved = { localStorage: g.localStorage, sessionStorage: g.sessionStorage, document: g.document };
  g.localStorage = spy("local"); g.sessionStorage = spy("session");
  const doc = { _c: "", get cookie() { return this._c; }, set cookie(v: string) { writes.push(`cookie:${v}`); this._c = v; } };
  g.document = doc;
  const calls: { url: string; headers: Record<string, string>; body: unknown }[] = [];
  const fetchImpl = (async (url: string, init: RequestInit) => {
    calls.push({ url, headers: init.headers as Record<string, string>, body: init.body });
    return new Response(JSON.stringify({ approved: true }), { status: 200 });
  }) as unknown as typeof fetch;
  try {
    const res = await callApi("/v1/contracts/c/versions/1:approve", { method: "POST", body: {}, passphrase: PASS, fetchImpl });
    assert.equal(res.ok, true);
    assert.equal(calls[0].headers["x-console-passphrase"], PASS);
    assert.ok(!String(calls[0].url).includes(PASS));
    assert.ok(!String(calls[0].body).includes(PASS));
    await callApi("/v1/campaigns", { fetchImpl });
    assert.equal(calls[1].headers["x-console-passphrase"], undefined);
    assert.deepEqual(writes, [], "something was stored while a passphrase was in use");
  } finally {
    g.localStorage = saved.localStorage; g.sessionStorage = saved.sessionStorage; g.document = saved.document;
  }
});

test("a network failure reads as 'state unknown', not as a stopped bench", async () => {
  const res = await callApi("/v1/campaigns", { fetchImpl: (async () => { throw new TypeError("fetch failed"); }) as typeof fetch });
  assert.equal(res.ok, false);
  if (!res.ok) { assert.equal(res.error.code, "CONSOLE_UNREACHABLE"); assert.match(res.error.message, /unknown/i); assert.doesNotMatch(res.error.message.replace(/Do not assume[^.;]*[.;]/, ""), /stopped|safe/i); }
});

test("the actor cookie holds a validated name and nothing else", () => {
  assert.equal(actorCookie("bad;name"), null);
  const c = actorCookie("Ada Lovelace");
  assert.ok(c && c.startsWith("aq_actor=Ada%20Lovelace"));
  assert.equal(readActor("a=b; aq_actor=Ada%20Lovelace"), "Ada Lovelace");
  assert.equal(readActor(""), "");
});

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap(f => {
    const p = join(dir, f);
    return statSync(p).isDirectory() ? sources(p) : /\.(ts|tsx)$/.test(f) ? [p] : [];
  });
}

test("no source file can persist a passphrase or read the operator token in client code", () => {
  const root = new URL("../src", import.meta.url).pathname;
  for (const file of sources(root)) {
    const text = readFileSync(file, "utf-8");
    const clientCode = /^["']use client["']/m.test(text);
    if (/passphrase/i.test(text)) {
      assert.ok(!/(localStorage|sessionStorage|indexedDB|document\.cookie)[^\n]*passphrase|passphrase[^\n]*(localStorage|sessionStorage|indexedDB|document\.cookie)/i.test(text), `${file} stores a passphrase`);
    }
    if (clientCode || file.includes("/components/") || file.endsWith("client.ts")) {
      assert.ok(!/OPERATOR_TOKEN|operator[-_ ]?token/i.test(text.replace(/\/\/.*$/gm, "").replace(/\{\/\*[\s\S]*?\*\/\}/g, "").replace(/"[^"\n]*(operator token|operator-token)[^"\n]*"/gi, "")), `${file} touches the operator token`);
    }
  }
});
