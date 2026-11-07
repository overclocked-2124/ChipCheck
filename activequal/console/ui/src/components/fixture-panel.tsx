"use client";

import { benchStatus, ageSeconds, formatAge } from "@/lib/live";
import { HEALTH_MAX_AGE_S } from "@/lib/arming";
import { useNow } from "@/components/api";
import { KeyValues, Mono } from "@/components/ui";
import type { FixtureView } from "@/lib/types";

/** E-stop / watchdog / interlock / trip with the age of the report. A stale or missing report is never shown as healthy. */
export function BenchStatusPanel({ fixture }: { fixture: FixtureView | null }) {
  const now = useNow(1000);
  const lines = benchStatus(fixture);
  const age = ageSeconds(fixture?.healthAt, now);
  const stale = age === null || age > HEALTH_MAX_AGE_S;
  const h = fixture?.health ?? null;
  return (
    <div className="stack">
      <div className="bench" role="list" aria-label="Bench status">
        {lines.map(l => (
          <div key={l.id} role="listitem" className={l.ok === null ? "unk" : l.ok ? "ok" : "bad"}>
            {l.label}<small>{l.detail}</small>
          </div>
        ))}
        <div role="listitem" className={h === null ? "unk" : h.outputsInShutdown ? "ok" : "bad"}>Outputs<small>{h === null ? "not reported" : h.outputsInShutdown ? "in shutdown" : "NOT in shutdown"}</small></div>
        <div role="listitem" className={h === null ? "unk" : h.adaptersCompatible ? "ok" : "bad"}>Adapters<small>{h === null ? "not reported" : h.adaptersCompatible ? "compatible" : "INCOMPATIBLE"}</small></div>
      </div>
      <p className={stale ? "bad-text" : "hint"}>
        Bench health reported {formatAge(age)}{stale ? ` - older than ${HEALTH_MAX_AGE_S} s or never reported: the bench state is not known to be current.` : "."}
      </p>
      {h ? <KeyValues rows={[
        ["DUT firmware", <Mono key="d">{h.dutFirmwareSha256 ?? "not reported"}</Mono>],
        ["Test-controller firmware", <Mono key="m">{h.mcuFirmwareSha256 ?? "not reported"}</Mono>],
      ]} /> : null}
    </div>
  );
}
