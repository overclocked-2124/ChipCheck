import type { CampaignState } from "./types.ts";

export type CampaignAction = "validate" | "arm" | "start" | "pause" | "resume" | "abort" | "disarm" | "clear-lockout";

export type ActionSpec = {
  action: CampaignAction;
  label: string;
  reviewer: boolean;
  danger: boolean;
  /** Arm is never offered as a plain button: it lives on the arming checklist. */
  checklistOnly?: boolean;
};

const SPECS: Record<CampaignAction, ActionSpec> = {
  validate: { action: "validate", label: "Validate", reviewer: false, danger: false },
  arm: { action: "arm", label: "Arm", reviewer: false, danger: false, checklistOnly: true },
  start: { action: "start", label: "Start", reviewer: false, danger: false },
  pause: { action: "pause", label: "Pause after this episode", reviewer: false, danger: false },
  resume: { action: "resume", label: "Resume", reviewer: false, danger: false },
  abort: { action: "abort", label: "Stop and de-energize (abort)", reviewer: false, danger: true },
  disarm: { action: "disarm", label: "Disarm", reviewer: false, danger: true },
  "clear-lockout": { action: "clear-lockout", label: "Clear lockout", reviewer: true, danger: false },
};

/** HLD 03 §6 transition table, restricted to what a researcher may request in each state. */
const ALLOWED: Record<CampaignState, CampaignAction[]> = {
  DRAFT: ["validate"],
  VALIDATING: [],
  READY: ["validate", "arm"],
  ARMED: ["start", "disarm"],
  RUNNING: ["pause", "abort"],
  PAUSING: ["abort"],
  PAUSED: ["resume", "abort"],
  ABORTING: [],
  ABORTED: [],
  COMPLETED: [],
  LOCKED_OUT: ["clear-lockout"],
};

export function allowedActions(state: CampaignState): ActionSpec[] {
  return (ALLOWED[state] ?? []).map(a => SPECS[a]);
}

export function actionSpec(action: CampaignAction): ActionSpec {
  return SPECS[action];
}

/** Terminal states cannot change again. */
export const TERMINAL_STATES: CampaignState[] = ["ABORTED", "COMPLETED"];

export type Tone = "ok" | "info" | "warn" | "bad" | "muted";

/** Badge colour class. A tone never claims the bench is safe; it only labels the campaign's state. */
export function stateTone(state: CampaignState): Tone {
  switch (state) {
    case "RUNNING": return "info";
    case "ARMED": case "READY": case "PAUSING": case "PAUSED": case "VALIDATING": case "ABORTING": return "warn";
    case "LOCKED_OUT": return "bad";
    case "COMPLETED": return "ok";
    default: return "muted";
  }
}

export const STATE_MEANING: Record<CampaignState, string> = {
  DRAFT: "Editable; not approved for execution.",
  VALIDATING: "The Backend is checking contract, fixture and budget.",
  READY: "Valid, but the bench is not armed.",
  ARMED: "Armed; no episode runs until you start it.",
  RUNNING: "Episodes are being planned, leased and run.",
  PAUSING: "No new episode will start; the active one is finishing and shutting down.",
  PAUSED: "Paused with its state kept; no physical work is available.",
  ABORTING: "Stopping active work and moving the bench to shutdown. Waiting for the bench to confirm.",
  ABORTED: "Ended before normal completion.",
  COMPLETED: "A budget or stopping rule ended the campaign normally.",
  LOCKED_OUT: "A safety event needs physical inspection and a reviewer reset.",
};
