"use client";

import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import { callApi, type CallOptions } from "@/lib/client";
import { isUnreachable } from "@/lib/errors";
import type { ApiResult, UiError } from "@/lib/types";

// ---- global reachability: any failed call to an unreachable control plane flips the shell banner ----
type Reach = { unreachable: boolean; lastOkAt: number | null };
let reach: Reach = { unreachable: false, lastOkAt: null };
const listeners = new Set<() => void>();
function setReach(next: Reach): void {
  if (next.unreachable === reach.unreachable && next.lastOkAt === reach.lastOkAt) return;
  reach = next; listeners.forEach(l => l());
}
export function useReachability(): Reach {
  return useSyncExternalStore(cb => { listeners.add(cb); return () => { listeners.delete(cb); }; }, () => reach, () => reach);
}

/** callApi that also feeds the reachability banner. */
export async function api<T>(path: string, options?: CallOptions): Promise<ApiResult<T>> {
  const result = await callApi<T>(path, options);
  if (result.ok) setReach({ unreachable: false, lastOkAt: Date.now() });
  else if (isUnreachable(result.error)) setReach({ unreachable: true, lastOkAt: reach.lastOkAt });
  return result;
}

export type Loaded<T> = {
  data: T | null; error: UiError | null; loading: boolean; lastOkAt: number | null; reload: () => Promise<void>;
};

/** Fetch once, then every `everyMs` (0 = once). Keeps the last good data on failure but always exposes the error. */
export function useLoad<T>(path: string | null, everyMs = 0): Loaded<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<UiError | null>(null);
  const [loading, setLoading] = useState<boolean>(path !== null);
  const [lastOkAt, setLastOkAt] = useState<number | null>(null);
  const alive = useRef(true);
  const reload = useCallback(async () => {
    if (path === null) return;
    const result = await api<T>(path);
    if (!alive.current) return;
    if (result.ok) { setData(result.data); setError(null); setLastOkAt(Date.now()); }
    else setError(result.error);
    setLoading(false);
  }, [path]);
  useEffect(() => {
    alive.current = true;
    setData(null); setError(null); setLoading(path !== null);
    void reload();
    const timer = everyMs > 0 ? setInterval(() => { void reload(); }, everyMs) : null;
    return () => { alive.current = false; if (timer) clearInterval(timer); };
  }, [path, everyMs, reload]);
  return { data, error, loading, lastOkAt, reload };
}

export function useNow(everyMs = 1000): number {
  const [now, setNow] = useState<number>(() => Date.now());
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), everyMs); return () => clearInterval(t); }, [everyMs]);
  return now;
}

// ---- per-viewer convenience: recently used ids (no secrets ever) ----
export function recentGet(kind: string): string[] {
  try { const raw = window.localStorage.getItem("aq_recent_" + kind); const v: unknown = raw ? JSON.parse(raw) : []; return Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : []; }
  catch { return []; }
}
export function recentAdd(kind: string, value: string): void {
  try { const next = [value, ...recentGet(kind).filter(v => v !== value)].slice(0, 8); window.localStorage.setItem("aq_recent_" + kind, JSON.stringify(next)); }
  catch { /* storage may be blocked; recents are a convenience only */ }
}
