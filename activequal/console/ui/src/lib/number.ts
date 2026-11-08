// Typed-number fields: the text stays as typed, and these rules replace the browser's type="number" checks.

export type NumberRule = { min?: number; max?: number; integer?: boolean; required?: boolean };

const NUMERIC = /^-?\d+(\.\d+)?$/;

/** Why the text is not an acceptable number, or null when it is. */
export function numberProblem(text: string, rule: NumberRule = {}): string | null {
  const t = text.trim();
  if (!t) return rule.required === false ? null : "Required";
  if (!NUMERIC.test(t)) return rule.integer ? "Whole number only" : "Number only";
  const n = Number(t);
  if (rule.integer && !Number.isInteger(n)) return "Whole number only";
  if (rule.min !== undefined && n < rule.min) return `At least ${rule.min}`;
  if (rule.max !== undefined && n > rule.max) return `At most ${rule.max}`;
  return null;
}

const decimals = (n: number) => (String(n).split(".")[1] ?? "").length;

/** One step up or down from the typed value, clamped to the rule and rounded to the step's precision. */
export function stepNumber(text: string, direction: 1 | -1, step: number, rule: NumberRule = {}): string {
  const current = NUMERIC.test(text.trim()) ? Number(text) : rule.min ?? 0;
  let next = current + direction * step;
  if (rule.min !== undefined) next = Math.max(rule.min, next);
  if (rule.max !== undefined) next = Math.min(rule.max, next);
  return next.toFixed(Math.max(decimals(step), decimals(current)));
}
