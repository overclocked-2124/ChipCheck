// Form inputs for the manual challenge, read from the contract's controls. Range limits shape the slider only;
// the typed value is sent as entered so the server's safety rules, not this page, decide what is allowed.

import type { JsonValue } from "./types.ts";

export type ControlInput =
  | { name: string; kind: "boolean"; nominal: boolean }
  | { name: string; kind: "choice"; values: string[]; nominal: string }
  | { name: string; kind: "number"; min: number; max: number; step: number; unit: string; nominal: number; activeWhen: string | null };

const isObj = (v: JsonValue | undefined): v is Record<string, JsonValue> => !!v && typeof v === "object" && !Array.isArray(v);
const num = (v: JsonValue | undefined, fallback: number) => (typeof v === "number" && Number.isFinite(v) ? v : fallback);

export function controlInputs(contract: Record<string, JsonValue>): ControlInput[] {
  const controls = isObj(contract.controls) ? contract.controls : {};
  const out: ControlInput[] = [];
  for (const [name, spec] of Object.entries(controls)) {
    if (!isObj(spec)) continue;
    if (spec.type === "boolean") out.push({ name, kind: "boolean", nominal: spec.nominal === true });
    else if (spec.type === "categorical" && Array.isArray(spec.values)) {
      const values = spec.values.map(String);
      out.push({ name, kind: "choice", values, nominal: typeof spec.nominal === "string" ? spec.nominal : values[0] ?? "" });
    } else {
      const min = num(spec.min, 0), max = num(spec.max, min), step = num(spec.step, 1);
      const when = isObj(spec.activeWhen) ? `${spec.activeWhen.control} = ${String(spec.activeWhen.eq)}` : null;
      out.push({ name, kind: "number", min, max, step, unit: typeof spec.unit === "string" ? spec.unit : "", nominal: num(spec.nominal, min), activeWhen: when });
    }
  }
  return out;
}
