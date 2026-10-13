import { ProposalResponse, SetupDraft } from "./types";

// UI preview only. No candidate selection, safety approval, or oracle logic lives here.
export function previewProposal(draft: SetupDraft): ProposalResponse {
  return {
    source: "mock",
    setupName: draft.name,
    tests: [
      {
        id: "preview-1",
        title: "Nominal setup check",
        purpose: "Preview the first proposed experiment after configuration.",
        requested: [draft.railName ? `${draft.railName}: within entered range` : "Configured controls", draft.workloads || "Configured workload"],
        expectedObservations: [draft.observations || "Configured observations"]
      },
      {
        id: "preview-2",
        title: "Range exploration",
        purpose: "Show how a subsequent proposal could be presented.",
        requested: [draft.railName ? `${draft.railName}: another allowed setting` : "Another allowed setting", draft.ledStates || "Configured states"],
        expectedObservations: [draft.requirement || "Configured requirement"]
      }
    ]
  };
}
