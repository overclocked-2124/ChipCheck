import type { Reason, UiError } from "./types.ts";

const MAX_MESSAGE = 500;
const GENERIC: Record<number, [string, string]> = {
  400: ["INVALID_ARGUMENT", "The control plane rejected the request."],
  401: ["UNAUTHENTICATED", "The control plane did not accept the Console's credentials. Check the operator token file and your name."],
  403: ["PERMISSION_DENIED", "This action needs the reviewer passphrase."],
  404: ["NOT_FOUND", "Not found."],
  409: ["STALE_VERSION", "The record changed since you loaded it. Refresh and try again."],
  412: ["FAILED_PRECONDITION", "The control plane refused the action in the current state."],
  503: ["UNAVAILABLE", "The control plane reports this is not available yet."],
};

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function parseReasons(v: unknown): Reason[] | undefined {
  if (!Array.isArray(v)) return undefined;
  const out: Reason[] = [];
  for (const item of v) {
    if (isRecord(item) && typeof item.code === "string" && typeof item.message === "string") {
      out.push({ code: item.code.slice(0, 80), message: item.message.slice(0, MAX_MESSAGE) });
    }
  }
  return out;
}

function safeMessage(text: unknown): string | null {
  if (typeof text !== "string" || !text.trim()) return null;
  // Python tracebacks and file paths are not for researchers.
  if (/Traceback \(most recent call last\)|\n\s+File "/.test(text)) return null;
  return text.length > MAX_MESSAGE ? text.slice(0, MAX_MESSAGE) + "..." : text;
}

/** Map a control-plane error response onto the small UI-safe shape. Keeps code, message, reasons and the current version. */
export function translateError(status: number, body: unknown): UiError {
  const [fallbackCode, fallbackMessage] = GENERIC[status] ?? ["INTERNAL", "The control plane reported an internal error. Nothing was changed by this request."];
  const err = isRecord(body) && isRecord(body.error) ? body.error : null;
  if (!err) return { code: fallbackCode, message: fallbackMessage, status };
  const code = typeof err.code === "string" && /^[A-Z_]{3,40}$/.test(err.code) ? err.code : fallbackCode;
  const result: UiError = { code, message: safeMessage(err.message) ?? fallbackMessage, status };
  if (isRecord(err.details)) {
    const reasons = parseReasons(err.details.reasons);
    if (reasons) result.reasons = reasons;
    if (typeof err.details.currentVersion === "number") result.currentVersion = err.details.currentVersion;
  }
  return result;
}

export const unreachable = (): UiError => ({
  code: "CONTROL_PLANE_UNREACHABLE", status: 502,
  message: "Control plane unreachable: bench state unknown. Do not assume the bench has stopped or is safe; check the fixture and the E-stop in person.",
});

export const consoleUnreachable = (): UiError => ({
  code: "CONSOLE_UNREACHABLE", status: 0,
  message: "Cannot reach the Console server, so the control plane and bench state are unknown. Do not assume the bench has stopped or is safe.",
});

export const notConfigured = (what: string): UiError => ({ code: "CONSOLE_NOT_CONFIGURED", status: 500, message: what });

export function isUnreachable(error: UiError | null | undefined): boolean {
  return !!error && (error.code === "CONTROL_PLANE_UNREACHABLE" || error.code === "CONSOLE_UNREACHABLE");
}

export function errorText(error: UiError): string {
  const extra = error.reasons?.length ? " " + error.reasons.map(r => r.message).join("; ") : "";
  return `${error.message}${extra}`;
}
