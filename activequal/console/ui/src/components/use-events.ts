"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/components/api";
import { readActor } from "@/lib/client";
import { lastEventId, mergeEvents } from "@/lib/live";
import type { CampaignEvent, UiError } from "@/lib/types";

/** The whole event log, fetched incrementally with ?after= so it never stops at the server's 500-event page. */
export function useCampaignEvents(campaignId: string, everyMs = 2000) {
  const [events, setEvents] = useState<CampaignEvent[]>([]);
  const [error, setError] = useState<UiError | null>(null);
  const ref = useRef<CampaignEvent[]>([]);
  const busy = useRef(false);
  const reload = useCallback(async () => {
    if (busy.current) return;                       // never let an older poll land after a newer one
    busy.current = true;
    try {
      for (let page = 0; page < 50; page++) {
        const after = lastEventId(ref.current);
        const r = await api<{ events: CampaignEvent[] }>(`/v1/campaigns/${encodeURIComponent(campaignId)}/events?after=${after}`);
        if (!r.ok) { setError(r.error); return; }
        setError(null);
        if (!r.data.events.length) break;
        ref.current = mergeEvents(ref.current, r.data.events);
        setEvents(ref.current);
        if (r.data.events.length < 500) break;
      }
    } finally { busy.current = false; }
  }, [campaignId]);
  useEffect(() => {
    ref.current = []; setEvents([]);
    void reload();
    const t = setInterval(() => { if (readActor(document.cookie)) void reload(); }, everyMs);
    return () => clearInterval(t);
  }, [reload, everyMs]);
  return { events, error, reload };
}
