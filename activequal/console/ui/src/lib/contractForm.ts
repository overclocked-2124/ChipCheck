// Contract editing: a form for the common fields over a JSON text that stays the source of truth.
// Validation here is only "is this a JSON object of the right rough shape"; the Backend's validator has the last word
// and its error text is shown verbatim.

import type { JsonValue } from "./types.ts";

export type ContractForm = {
  dut: string; firmwareSha256: string; fixture: string; fixtureRev: string;
  budget: string; seed: string; maxTempC: string; maxEpisodeS: string;
};
export const EMPTY_FORM: ContractForm = { dut: "", firmwareSha256: "", fixture: "", fixtureRev: "", budget: "", seed: "", maxTempC: "", maxEpisodeS: "" };

export type ParseResult = { ok: true; value: Record<string, JsonValue> } | { ok: false; error: string };

const REQUIRED_SECTIONS = ["setup", "controls", "observations", "requirements", "safety", "campaign"] as const;

export function parseContractText(text: string): ParseResult {
  if (!text.trim()) return { ok: false, error: "The contract is empty." };
  let value: unknown;
  try { value = JSON.parse(text); }
  catch (e) { return { ok: false, error: `Not valid JSON: ${e instanceof Error ? e.message : "parse error"}` }; }
  if (typeof value !== "object" || value === null || Array.isArray(value)) return { ok: false, error: "A contract is a JSON object." };
  const obj = value as Record<string, JsonValue>;
  if (obj.contractVersion !== 2) return { ok: false, error: "contractVersion must be 2 (HLD 04 §12)." };
  const missing = REQUIRED_SECTIONS.filter(k => !(k in obj));
  if (missing.length) return { ok: false, error: `Missing section(s): ${missing.join(", ")}.` };
  return { ok: true, value: obj };
}

const asObj = (v: JsonValue | undefined): Record<string, JsonValue> => (typeof v === "object" && v !== null && !Array.isArray(v) ? v : {});
const str = (v: JsonValue | undefined): string => (v === undefined || v === null ? "" : String(v));

export function readForm(contract: Record<string, JsonValue>): ContractForm {
  const setup = asObj(contract.setup), campaign = asObj(contract.campaign), safety = asObj(contract.safety);
  return {
    dut: str(setup.dut), firmwareSha256: str(setup.firmwareSha256), fixture: str(setup.fixture), fixtureRev: str(setup.fixtureRev),
    budget: str(campaign.budget), seed: str(campaign.seed), maxTempC: str(safety.maxTempC), maxEpisodeS: str(safety.maxEpisodeS),
  };
}

function numberOrText(text: string): JsonValue {
  const n = Number(text);
  return text.trim() !== "" && Number.isFinite(n) ? n : text;
}

/** Apply form fields to the contract; empty fields are left untouched so the form never deletes JSON it does not show. */
export function applyForm(contract: Record<string, JsonValue>, form: ContractForm): Record<string, JsonValue> {
  const next: Record<string, JsonValue> = { ...contract };
  const section = (name: string, edits: Record<string, string | undefined>, numeric: string[]): void => {
    const base = { ...asObj(next[name]) };
    for (const [key, text] of Object.entries(edits)) {
      if (text === undefined || text === "") continue;
      base[key] = numeric.includes(key) ? numberOrText(text) : text;
    }
    next[name] = base;
  };
  section("setup", { dut: form.dut, firmwareSha256: form.firmwareSha256, fixture: form.fixture, fixtureRev: form.fixtureRev }, []);
  section("campaign", { budget: form.budget, seed: form.seed }, ["budget", "seed"]);
  section("safety", { maxTempC: form.maxTempC, maxEpisodeS: form.maxEpisodeS }, ["maxTempC", "maxEpisodeS"]);
  return next;
}

export const prettyJson = (v: unknown): string => JSON.stringify(v, null, 2);

export type ControlSummary = { name: string; type: string; range: string; nominal: string };
export function controlSummaries(contract: Record<string, JsonValue>): ControlSummary[] {
  return Object.entries(asObj(contract.controls)).map(([name, raw]) => {
    const c = asObj(raw);
    const range = Array.isArray(c.values) ? c.values.map(String).join(" | ") : c.min !== undefined ? `${str(c.min)} to ${str(c.max)}${c.unit ? " " + str(c.unit) : ""}, step ${str(c.step)}` : "";
    return { name, type: str(c.type), range, nominal: str(c.nominal) };
  });
}
