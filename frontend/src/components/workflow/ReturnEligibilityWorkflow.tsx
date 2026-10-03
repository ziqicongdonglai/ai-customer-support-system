"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  ApiError,
  listReturnEligibilityCandidates,
  resumeWorkflow,
  startWorkflow,
} from "@/lib/api";
import type {
  ReturnEligibilityCandidate,
  ReturnEligibilityResult,
} from "@/types/workflow";

type Phase = "idle" | "starting" | "waiting" | "resuming" | "completed";

interface ReturnEligibilityWorkflowProps {
  conversationId: string | null;
  openRequestId: number | null;
  onOpenRequestConsumed: (requestId: number) => void;
}

const DATE_FORMATTER = new Intl.DateTimeFormat(undefined, { dateStyle: "medium" });

const RESULT_COPY: Record<string, string> = {
  "eligible:eligible": "This purchase is eligible for return.",
  "ineligible:product_not_eligible": "This product does not support no-reason returns.",
  "ineligible:outside_return_window": "This purchase is outside the return window.",
  "ineligible:not_delivered": "This purchase has not been delivered.",
  "ineligible:insufficient_delivery_evidence": "There is not enough delivery information to determine eligibility.",
  "ineligible:shipment_order_mismatch": "The shipment information does not match this purchase.",
  "unavailable:order_item_unavailable": "This purchase is unavailable.",
};

// localStorage 只保存 Conversation → workflowId correlation，方便同一浏览器恢复；
// authoritative Workflow persistence 与 lifecycle 始终属于 backend。
function correlationKey(conversationId: string): string {
  return `ai-chat:return-eligibility-workflow:${conversationId}`;
}

function readWorkflowCorrelation(conversationId: string): string | null {
  try {
    return window.localStorage.getItem(correlationKey(conversationId));
  } catch {
    return null;
  }
}

function writeWorkflowCorrelation(conversationId: string, workflowId: string): boolean {
  try {
    window.localStorage.setItem(correlationKey(conversationId), workflowId);
    return true;
  } catch {
    return false;
  }
}

function removeWorkflowCorrelation(conversationId: string): boolean {
  try {
    window.localStorage.removeItem(correlationKey(conversationId));
    return true;
  } catch {
    return false;
  }
}

function formatPurchaseDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "Date unavailable" : DATE_FORMATTER.format(date);
}

function resultCopy(result: ReturnEligibilityResult): string {
  return RESULT_COPY[`${result.outcome}:${result.reason}`] ?? {
    eligible: "This purchase is eligible for return.",
    ineligible: "This purchase is not eligible for return.",
    unavailable: "Return eligibility is unavailable for this purchase.",
  }[result.outcome];
}

export default function ReturnEligibilityWorkflow({
  conversationId,
  openRequestId,
  onOpenRequestConsumed,
}: ReturnEligibilityWorkflowProps) {
  // phase 是 frontend operation state；workflowId 是 durable Workflow 的相关标识。
  // panelOpen 仅表示 UI visibility，不代表 Workflow 已创建或状态发生变化。
  const [workflowId, setWorkflowId] = useState<string | null>(() =>
    typeof window !== "undefined" && conversationId
      ? readWorkflowCorrelation(conversationId)
      : null,
  );
  const [phase, setPhase] = useState<Phase>(() => workflowId ? "waiting" : "idle");
  const [panelOpen, setPanelOpen] = useState(false);
  // candidates 与 terminalResult 都是 transient current response，不写入 localStorage。
  const [candidates, setCandidates] = useState<ReturnEligibilityCandidate[] | null>(null);
  const [terminalResult, setTerminalResult] = useState<ReturnEligibilityResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  // storageWarning 只报告浏览器 correlation 持久化失败，不冒充 backend operation failure。
  const [storageWarning, setStorageWarning] = useState<string | null>(null);
  const resumeInFlightRef = useRef(false);
  const consumedOpenRequestIdRef = useRef<number | null>(null);

  const loadCandidates = useCallback(async () => {
    setCandidates(null);
    setError(null);
    try {
      const response = await listReturnEligibilityCandidates();
      if (!Array.isArray(response.candidates)) throw new Error("Invalid candidate response");
      setCandidates(response.candidates);
    } catch {
      setError("Purchases could not be loaded. Please try again.");
    }
  }, []);

  const handleOpen = useCallback(() => {
    // 打开面板只改变可见性；已有 WAITING correlation 时重新读取 current candidates。
    setPanelOpen(true);
    if (workflowId && phase === "waiting") void loadCandidates();
  }, [loadCandidates, phase, workflowId]);

  useEffect(() => {
    // openRequestId 是一次性 handoff event token，不是持久 panelOpen 状态；
    // consumed ref 防止同一个 render/effect 周期重复消费。
    if (
      openRequestId === null
      || consumedOpenRequestIdRef.current === openRequestId
    ) {
      return;
    }

    consumedOpenRequestIdRef.current = openRequestId;
    handleOpen();
    onOpenRequestConsumed(openRequestId);
  }, [handleOpen, onOpenRequestConsumed, openRequestId]);

  function handleClose() {
    if (phase === "completed") {
      handleDone();
      return;
    }

    setPanelOpen(false);
    if (phase === "waiting") {
      setCandidates(null);
      setError(null);
    }
  }

  function handleDone() {
    setPanelOpen(false);
    setWorkflowId(null);
    setPhase("idle");
    setCandidates(null);
    setTerminalResult(null);
    setError(null);
    setStorageWarning(null);
  }

  async function handleStart() {
    // Human 点击 Start check 才是 durable Workflow creation point；
    // AI handoff 或打开面板都不会提前创建 Workflow。
    if (!conversationId || phase !== "idle") return;
    setPhase("starting");
    setError(null);
    setStorageWarning(null);

    try {
      const response = await startWorkflow({ conversation_id: conversationId });
      if (response.status !== "waiting_for_clarification" || !response.workflow_id) {
        setPhase("idle");
        setError("The server returned an unexpected workflow response.");
        return;
      }

      setWorkflowId(response.workflow_id);
      setPhase("waiting");
      if (!writeWorkflowCorrelation(conversationId, response.workflow_id)) {
        setStorageWarning("This check can continue now, but it cannot be restored after a refresh or conversation switch.");
      }
      await loadCandidates();
    } catch (requestError) {
      setPhase("idle");
      setError(
        requestError instanceof ApiError && requestError.status === 409
          ? "A return eligibility check is already active for this conversation, but this browser cannot recover it."
          : "The return eligibility check could not be started.",
      );
    }
  }

  async function handleResume(orderItemId: string) {
    // candidate 只解决 purchase identification；backend Resume 仍会校验 ownership、
    // 重读 current Business State，并由 BusinessService 执行 deterministic rule。
    if (!conversationId || !workflowId || phase !== "waiting" || resumeInFlightRef.current) return;
    resumeInFlightRef.current = true;
    setPhase("resuming");
    setError(null);

    try {
      const response = await resumeWorkflow(workflowId, {
        conversation_id: conversationId,
        order_item_id: orderItemId,
      });
      if (response.status !== "completed") {
        setError("The server returned an unexpected workflow response.");
        return;
      }

      setPhase("completed");
      // COMPLETED 表示 Workflow 已产生 terminal outcome，不等于 eligible。
      setCandidates(null);
      setStorageWarning(null);
      if (!removeWorkflowCorrelation(conversationId)) {
        setStorageWarning("The result is confirmed, but the saved browser correlation could not be removed.");
      }
      if (!response.return_eligibility) {
        setError("The completed workflow did not include an eligibility result.");
        return;
      }
      setTerminalResult(response.return_eligibility);
    } catch (requestError) {
      setCandidates(null);
      setError(
        requestError instanceof ApiError && requestError.status === 404
          ? "This saved check can no longer be resumed."
          : "The result could not be confirmed. This check will not be retried automatically.",
      );
    } finally {
      resumeInFlightRef.current = false;
    }
  }

  const actionLabel = phase === "starting"
    ? "Starting..."
    : phase === "waiting"
      ? "Return check in progress"
      : phase === "resuming"
        ? error ? "Return check needs attention" : "Checking..."
        : phase === "completed"
          ? "Return check complete"
          : "Return eligibility";

  return (
    <div className="relative">
      <button
        type="button"
        onClick={panelOpen ? handleClose : handleOpen}
        disabled={!conversationId}
        aria-expanded={panelOpen}
        aria-haspopup="dialog"
        className="rounded border border-gray-300 px-3 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-100 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {actionLabel}
      </button>

      {panelOpen && (
        <section
          role="dialog"
          aria-label="Return eligibility"
          aria-busy={phase === "starting" || (phase === "resuming" && !error)}
          className="absolute right-0 top-full z-20 mt-2 flex max-h-[min(32rem,calc(100vh-8rem))] w-[min(24rem,calc(100vw-2rem))] flex-col overflow-hidden rounded-lg border border-gray-200 bg-white shadow-xl"
        >
          <div className="flex shrink-0 items-center justify-between border-b border-gray-200 px-4 py-3">
            <h3 className="text-sm font-semibold text-gray-900">Return eligibility</h3>
            <button
              type="button"
              onClick={handleClose}
              aria-label="Hide return eligibility"
              className="rounded px-2 py-1 text-lg leading-none text-gray-500 hover:bg-gray-100 hover:text-gray-900"
            >
              ×
            </button>
          </div>

          <div className="min-h-0 overflow-y-auto p-4">
            {storageWarning && <p className="mb-3 text-sm text-amber-700">{storageWarning}</p>}

            {phase === "idle" && (
              <div className="space-y-4">
                <p className="text-sm text-gray-700">Check whether one of your purchases is eligible for return.</p>
                {error && <p role="alert" className="text-sm text-red-600">{error}</p>}
                <div className="flex justify-end">
                <button type="button" onClick={() => void handleStart()} className="rounded bg-gray-900 px-3 py-2 text-sm font-medium text-white hover:bg-gray-700">Start check</button>
                </div>
              </div>
            )}

            {phase === "starting" && <p className="text-sm text-gray-600">Starting eligibility check...</p>}

            {phase === "waiting" && (
              <div className="space-y-3">
              <p className="text-sm font-medium text-gray-900">Select a purchase to check its return eligibility.</p>
              {error && <p role="alert" className="text-sm text-red-600">{error}</p>}
              {candidates === null && !error && <p className="text-sm text-gray-500">Loading purchases...</p>}
              {candidates === null && error && (
                <button type="button" onClick={() => void loadCandidates()} className="rounded border border-gray-300 px-3 py-2 text-sm hover:bg-gray-50">Try again</button>
              )}
              {candidates?.length === 0 && <p className="text-sm text-gray-500">No purchases available to check.</p>}
              {candidates && candidates.length > 0 && (
                <ul className="space-y-2">
                  {candidates.map((candidate) => (
                    <li key={candidate.order_item_id} className="rounded border border-gray-200 p-3">
                      <p className="text-sm font-medium text-gray-900">{candidate.product_name}</p>
                      <p className="mt-1 text-sm text-gray-600">
                        Purchased {formatPurchaseDate(candidate.order_created_at)}
                        {" · "}Quantity: {candidate.quantity}
                        {" · "}Unit price: {candidate.unit_price}
                      </p>
                      <button type="button" onClick={() => void handleResume(candidate.order_item_id)} className="mt-2 rounded bg-gray-900 px-3 py-2 text-sm font-medium text-white hover:bg-gray-700">
                        Check this purchase
                      </button>
                    </li>
                  ))}
                </ul>
              )}
              </div>
            )}

            {phase === "resuming" && (
              <div className="space-y-4">
              {error ? (
                <>
                  <p className="text-sm font-medium text-gray-900">Return check needs attention</p>
                  <p role="alert" className="text-sm text-red-600">{error}</p>
                </>
              ) : (
                <p className="text-sm text-gray-600">Checking the selected purchase...</p>
              )}
              </div>
            )}

            {phase === "completed" && (
              <div aria-live="polite" className="space-y-4">
              {terminalResult && <p className="text-sm font-medium text-gray-900">{resultCopy(terminalResult)}</p>}
              {error && <p role="alert" className="text-sm text-red-600">{error}</p>}
              <div className="flex justify-end">
                <button type="button" onClick={handleDone} className="rounded bg-gray-900 px-3 py-2 text-sm font-medium text-white hover:bg-gray-700">Done</button>
              </div>
              </div>
            )}
          </div>
        </section>
      )}
    </div>
  );
}
