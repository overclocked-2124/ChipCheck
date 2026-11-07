// Shapes returned by the ActiveQual control plane (activequal/service/http_api.py, backend.py, queries.py).
// The Console never invents state: every field below comes from a control-plane response.

export type JsonValue = string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue };
export type Conditions = Record<string, JsonValue>;

export type CampaignState =
  | "DRAFT" | "VALIDATING" | "READY" | "ARMED" | "RUNNING" | "PAUSING" | "PAUSED"
  | "ABORTING" | "ABORTED" | "COMPLETED" | "LOCKED_OUT";

export const PLANNERS = ["tpe", "gp", "random", "grid", "fixed_corner", "coverage", "manual"] as const;
export type Planner = (typeof PLANNERS)[number];

export type Outcome = "PASS" | "DUT_FAILURE" | "INVALID_EXPERIMENT" | "SAFETY_ABORT";
export type EpisodeRole = "discovery" | "confirm" | "minimize" | "bracket" | "necessity_probe";

export type Reason = { code: string; message: string };

export type CampaignView = {
  id: string;
  state: CampaignState;
  version: number;
  contractVersionId: string;
  contractHash: string;
  fixtureId: string;
  planner: { method: string; config: Record<string, JsonValue> };
  seed: number;
  plan: Record<string, JsonValue>;
  budget: { discovery: number; verification: number; discoveryUsed: number; verificationUsed: number };
  episodesByOutcome: Record<string, number>;
  candidatesRejected: number;
  softwareVersion: string;
  agentError?: string;
  /** Present on a validate response only. */
  reasons?: Reason[];
};

export type ContractSummary = {
  id: string; contractId: string; version: number; contractHash: string;
  approvalsRequired: number; approvedBy: string[]; approved: boolean;
};
export type ContractDetail = ContractSummary & { contract: Record<string, JsonValue> };

export type Calibration = {
  id: string; channels: Record<string, { gain: number; offset: number; uncertainty: number }>;
  meter: string; operator: string; createdAt: string; validUntil: string;
};
export type BenchHealth = {
  estopReleased: boolean; interlockHealthy: boolean; watchdogHealthy: boolean; outputsInShutdown: boolean;
  adaptersCompatible: boolean; tripActive: boolean;
  dutFirmwareSha256?: string | null; mcuFirmwareSha256?: string | null;
};
export type FixtureView = {
  id: string; revision: string; capabilities: string[]; calibration: Calibration | null;
  health: BenchHealth | null; healthAt: string | null; approvedMcuFirmwareSha256: string | null;
};

export type CampaignEvent = {
  id: number; entity: string; episodeId: string | null; attempt: number | null;
  previousState: string | null; newState: string; actorType: string; actorId: string;
  reasonCode: string; reason: string; backendTs: string; contractHash: string | null; fixtureId: string | null;
};

export type HistoryEpisode = {
  episodeId: string; role: EpisodeRole; outcome: Outcome | null; linkedEpisodeId: string | null;
  conditions: Conditions; robustness: number | null;
};
export type RejectedCandidate = { conditions: Conditions; violations: { code: string; control?: string | null; message: string }[] };
export type EpisodesResponse = { episodes: HistoryEpisode[]; rejected: RejectedCandidate[] };

export type Measured = { value: number; uncertainty: number | null; requested: number | null };
export type VerdictView = {
  episodeId: string; state: string; outcome: Outcome; reasonCode: string; reason: string;
  margins: Record<string, number>; robustness: number | null; requirements: JsonValue;
};
export type EpisodeView = {
  id: string; campaignId: string; state: string; role: EpisodeRole; attempt: number; linkedEpisodeId: string | null;
  requested: Conditions; contractHash: string; fixtureId: string; outcome: Outcome | null;
  measured: Record<string, Measured>; verdict?: VerdictView;
};

export type IntervalSide = { lastFail: number; firstPass: number | null; resolution: number | null; note: string };
export type Interval = { low: number; high: number; step: number; sides: { low: IntervalSide; high: IntervalSide } };
export type Counterexample = {
  id: string; originalEpisodeId: string;
  minimized: { conditions: Conditions; removed: string[]; kept: string[]; necessity: Record<string, string> };
  intervals: { intervals: Record<string, Interval>; budgetExhausted: boolean };
  reproductions: number; attempts: number; origin: "seeded" | "natural" | "unknown";
};

export type CandidateResult = {
  candidateId: string; state: string; plannerSequence: number; episodeId: string | null;
  violations: { code: string; control?: string | null; message: string }[];
};

export type ProposalResponse = {
  source: string; method: string; setupName: string; historyUsed: number;
  tests: { id: string; conditions: Conditions; reason: string; reasonCode?: string }[];
};

/** What the browser receives for any failure. Never contains a stack trace, token or passphrase. */
export type UiError = {
  code: string;
  message: string;
  status: number;
  reasons?: Reason[];
  currentVersion?: number;
};
export type ApiResult<T> = { ok: true; data: T } | { ok: false; error: UiError };
