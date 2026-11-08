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

// ---- Console read views (activequal/service/views.py) ----

export type LeaseView = {
  id: string; episodeId: string; owner: string; attempt: number; issuedAt: string; expiresAt: string;
  lastHeartbeatAt: string; state: "ACTIVE" | "RELEASED" | "NEEDS_RECONCILIATION";
};

export type EpisodeRecord = {
  episodeId: string; attempt: number; role: EpisodeRole; pool: "discovery" | "verification"; state: string;
  outcome: Outcome | null; linkedEpisodeId: string | null; plannerSequence: number; discoveryIndex: number | null;
  requested: Conditions; measured: Record<string, Measured>;
  verdict: Omit<VerdictView, "episodeId" | "state"> | null;
  planner: { method: string; reason: string; reasonCode: string; repeatReason: string | null };
  quality: Record<string, JsonValue> | null; createdAt: string; finalizedAt: string | null;
};
export type RejectedRecord = {
  candidateId: string; plannerSequence: number; role: string; conditions: Conditions;
  violations: { code: string; control?: string | null; message: string }[]; plannerReason: string; reasonCode: string;
};
export type RecordsResponse = { episodes: EpisodeRecord[]; rejected: RejectedRecord[] };

export type EpisodeDetail = EpisodeView & {
  planner: EpisodeRecord["planner"] | null; plannerSequence: number | null; discoveryIndex: number | null;
  quality: Record<string, JsonValue> | null; benchEvents: { type?: string; [k: string]: JsonValue | undefined }[];
  safetyTrip: string | null; manifestHash: string | null;
  traces: { sha256: string; mediaType: string; bytes: number }[]; leases: LeaseView[];
  createdAt: string | null; finalizedAt: string | null;
};

export type CampaignContract = {
  contractId: string; version: number; contractHash: string; contract: Record<string, JsonValue>;
  approvals: { reviewer: string; approvedAt: string }[]; approvalsRequired: number;
  armed: Record<string, JsonValue>; calibration: Record<string, JsonValue> | null;
  maxEpisodeS: number | null; expectedMaxRuntimeS: number | null;
};

export type Proportion = { numerator: number; denominator: number; rate: number | null; wilson95: [number, number] | null };
export type ReportCounterexample = {
  id: string; originalEpisodeId: string; origin: "seeded" | "natural" | "unknown"; originLabel: string;
  violated: { requirement: string; metric: string | null; margin: number | null; measuredValue: number | null; uncertainty: number | null; unit: string | null }[];
  original: { requested: Conditions; measured: Record<string, Measured>; discoveryIndex: number | null; plannerReason: string };
  minimized: Counterexample["minimized"];
  intervals: Record<string, Interval>; budgetExhausted: boolean;
  reproduction: Proportion & { unusableReplays: number; meetsTenReplays: boolean; note: string };
  verification: { episodes: { sequence: number; role: string; episodeId: string | null; outcome: string | null; conditions: Conditions }[] };
  nearbyPassing: { episodeId: string; role: string; conditions: Conditions }[];
};
export type ReportView = {
  campaignId: string; state: string; partial: boolean;
  identity: { contractId: string; contractVersion: number; contractHash: string; fixtureId: string; planner: { method: string; seed: number }; dut?: string | null };
  budget: { discovery: { allowed: number; used: number; remaining: number }; verification: { allowed: number; used: number; remaining: number } };
  outcomes: { total: number; valid: number; counts: Record<string, number>; invalidByReason: Record<string, number>;
    candidatesRejected: { count: number; byCode: Record<string, number> } };
  stop: { state: string; reasonCode: string; reason: string; backendTs: string; actorId: string } | null;
  metrics: { episodesToFirstConfirmedFailure: number | null; firstObservedFailureIndex: number | null; censoredAtBudget: number | null };
  requirements: { id: string; metric: string | null; op?: string; limit: Record<string, number>; evaluated: number; pass: number; fail: number;
    inconclusive: number; minMargin: number | null; minMarginEpisodeId: string | null }[];
  result: { kind: string; headline: string; statements: { text: string; episodeIds: string[] }[] };
  counterexamples: ReportCounterexample[];
  limitations: string[];
};

export type KaplanMeier = { n: number; events: number; censored: number; median: number | null; steps: { time: number; survival: number; atRisk: number; events: number; censored: number }[] };
export type CompareResponse = {
  campaigns: { campaignId: string; planner: string; seed: number; state: string; contract: string;
    firstConfirmedFailureAt: number | null; firstObservedFailureAt: number | null; censoredAt: number | null;
    discoveryUsed: number; discoveryBudget: number; verificationUsed: number; stoppedEarly: boolean; resultKind: string }[];
  comparison: { primaryMetric: string; checkpoints: number[];
    profiles: Record<string, { planners: Record<string, { campaigns: number; kaplanMeier: KaplanMeier;
      discoveryRates: Record<string, Proportion> }>; logRank: { a: string; b: string; chiSquare: number; p: number; pBonferroni: number }[] }> };
};
