export interface WorkflowStartRequest {
  conversation_id: string;
  order_item_id?: string | null;
}

export interface WorkflowResumeRequest {
  conversation_id: string;
  order_item_id: string;
}

export type ReturnEligibilityOutcome =
  | "eligible"
  | "ineligible"
  | "unavailable";

export interface ReturnEligibilityResult {
  outcome: ReturnEligibilityOutcome;
  reason: string;
}

export type WorkflowStatus =
  | "waiting_for_clarification"
  | "running"
  | "completed";

export interface WorkflowResponse {
  workflow_id: string;
  status: WorkflowStatus;
  clarification: string | null;
  return_eligibility: ReturnEligibilityResult | null;
}

export interface ReturnEligibilityCandidate {
  order_item_id: string;
  product_name: string;
  quantity: number;
  unit_price: string;
  order_created_at: string;
}

export interface CandidateListResponse {
  candidates: ReturnEligibilityCandidate[];
}
