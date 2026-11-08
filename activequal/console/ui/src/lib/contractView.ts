// Contract detail helpers (HLD 09 §5): readable forbidden rules and requirements, and the diff between two versions.

import type { JsonValue } from "./types.ts";

type Obj = Record<string, JsonValue>;
const isObj = (v: JsonValue | undefined): v is Obj => !!v && typeof v === "object" && !Array.isArray(v);
const show = (v: JsonValue | undefined) => (v === undefined ? "—" : typeof v === "string" ? v : JSON.stringify(v));

const OPS: [string, string][] = [["eq", "="], ["ne", "≠"], ["gte", "≥"], ["gt", ">"], ["lte", "≤"], ["lt", "<"], ["in", "in"]];

/** {control, eq: x} -> "control = x"; {all: [...]} -> "a AND b"; {any: [...]} -> "a OR b". */
export function describeRule(rule: JsonValue): string {
  if (!isObj(rule)) return show(rule);
  if (Array.isArray(rule.all)) return rule.all.map(describeRule).join(" AND ");
  if (Array.isArray(rule.any)) return "(" + rule.any.map(describeRule).join(" OR ") + ")";
  if (rule.not !== undefined) return `NOT ${describeRule(rule.not)}`;
  const op = OPS.find(([k]) => rule[k] !== undefined);
  return op ? `${show(rule.control)} ${op[1]} ${show(rule[op[0]])}` : show(rule);
}

export function describeRequirement(req: JsonValue): string {
  if (!isObj(req)) return show(req);
  if (req.op === "band") return `${show(req.lo)} ≤ ${show(req.metric)} ≤ ${show(req.hi)}`;
  if (req.op === "exact") return `${show(req.metric)} = ${show(req.limit)}`;
  return `${show(req.metric)} ${show(req.op)} ${show(req.limit)}`;
}

export type DiffRow = { path: string; before: string; after: string };

/** Leaf-level differences between two JSON values, by dotted path. Arrays are compared element by element. */
export function jsonDiff(before: JsonValue | undefined, after: JsonValue | undefined, path = ""): DiffRow[] {
  const bothObj = isObj(before) && isObj(after);
  const bothArr = Array.isArray(before) && Array.isArray(after);
  if (bothObj) {
    const keys = [...new Set([...Object.keys(before), ...Object.keys(after)])].sort();
    return keys.flatMap(k => jsonDiff(before[k], after[k], path ? `${path}.${k}` : k));
  }
  if (bothArr) {
    const n = Math.max(before.length, after.length);
    return Array.from({ length: n }, (_, i) => jsonDiff(before[i], after[i], `${path}[${i}]`)).flat();
  }
  return JSON.stringify(before) === JSON.stringify(after) ? [] : [{ path: path || "(root)", before: show(before), after: show(after) }];
}
