"use client";

import { useCallback, useEffect, useReducer, useRef } from "react";

import { ApiError } from "@/lib/api/client";
import { getReport, pollQuestion, resumeSession } from "@/lib/api/interview";
import type {
  FinalReport,
  PollQuestion,
  PollQuestionResponse,
  PreviousTurnEvaluation,
  LLMErrorKind,
} from "@/lib/api/types";
import { inferLLMErrorKind } from "@/lib/llm-config";

export type PollerPhase =
  | "idle"
  | "loading"
  | "waiting_for_answer"
  | "completed"
  | "error"
  | "cancelled";

export interface PollerState {
  phase: PollerPhase;
  question: PollQuestion | null;
  turnIdx: number | null;
  maxTurns: number | null;
  finalReport: FinalReport | null;
  error: string | null;
  errorKind: LLMErrorKind | null;
  retryable: boolean;
  /**
   * Compact projection of the candidate's most recently evaluated turn,
   * piped through from the long-poll response. ``null`` when there is
   * no displayable feedback (first ask, non-scoring intent, fallback
   * evaluator). Updated only on ``QUESTION`` so terminal frames
   * (completed / cancelled / error) preserve the last-shown card and
   * the ``SUBMITTING`` transition does not flicker the panel away.
   */
  previousEvaluation: PreviousTurnEvaluation | null;
}

type Action =
  | { type: "START" }
  | {
      type: "RESUMED";
      question: PollQuestion | null;
      turnIdx: number | null;
      maxTurns: number | null;
    }
  | {
      type: "QUESTION";
      question: PollQuestion;
      turnIdx: number | null;
      maxTurns: number | null;
      previousEvaluation: PreviousTurnEvaluation | null;
    }
  | { type: "COMPLETED"; report: FinalReport | null }
  | { type: "CANCELLED" }
  | {
      type: "ERROR";
      message: string;
      errorKind: LLMErrorKind | null;
      retryable?: boolean;
    }
  | { type: "SUBMITTING" };

const initial: PollerState = {
  phase: "idle",
  question: null,
  turnIdx: null,
  maxTurns: null,
  finalReport: null,
  error: null,
  errorKind: null,
  retryable: false,
  previousEvaluation: null,
};

const completedWithoutReportMessage =
  "这场面试还没有生成报告，可能是会话被取消或状态尚未同步。";

function reducer(state: PollerState, a: Action): PollerState {
  switch (a.type) {
    case "START":
      return {
        ...state,
        phase: "loading",
        error: null,
        errorKind: null,
        retryable: false,
      };
    case "RESUMED":
      return {
        ...state,
        phase: a.question ? "waiting_for_answer" : "loading",
        question: a.question,
        turnIdx: a.turnIdx,
        maxTurns: a.maxTurns,
        error: null,
        errorKind: null,
        retryable: false,
      };
    case "QUESTION":
      return {
        ...state,
        phase: "waiting_for_answer",
        question: a.question,
        turnIdx: a.turnIdx,
        maxTurns: a.maxTurns,
        previousEvaluation: a.previousEvaluation,
        error: null,
        errorKind: null,
        retryable: false,
      };
    case "COMPLETED":
      return {
        ...state,
        phase: "completed",
        finalReport: a.report,
        question: null,
        retryable: false,
      };
    case "CANCELLED":
      return { ...state, phase: "cancelled", question: null, retryable: false };
    case "SUBMITTING":
      return { ...state, phase: "loading", question: null, retryable: false };
    case "ERROR":
      return {
        ...state,
        phase: "error",
        error: a.message,
        errorKind: a.errorKind,
        retryable: Boolean(a.retryable),
      };
  }
}

/**
 * Drives the question/answer loop for a session.
 *
 * Flow on mount:
 * 1. Call /resume so we pick up the correct state whether this is a
 *    fresh session or the user is returning after a reload.
 * 2. If /resume says we already have a pending question, surface it.
 *    Otherwise begin long-polling for the next one.
 * 3. After ``submitAndRepoll`` is invoked, we re-enter the loop.
 */
export function useQuestionPoller(sessionId: string) {
  const [state, dispatch] = useReducer(reducer, initial);
  const abortRef = useRef<AbortController | null>(null);
  const mountedRef = useRef(true);

  const pollLoop = useCallback(
    async (ctrl: AbortController) => {
      while (!ctrl.signal.aborted) {
        try {
        const res: PollQuestionResponse = await pollQuestion(sessionId, {
          timeout: 30,
          signal: ctrl.signal,
        });
        if (ctrl.signal.aborted) return;
        if (res.status === "error") {
          dispatch({
            type: "ERROR",
            message: res.error ?? "面试过程中出现了问题。",
            errorKind: res.error_kind ?? inferLLMErrorKind(res.error),
            retryable: res.retryable,
          });
          return;
        }
        if (res.status === "completed") {
          const report = res.final_report ?? null;
          if (report) {
            dispatch({ type: "COMPLETED", report });
            } else {
              // Fallback: hit /report explicitly if the long-poll did
              // not include the payload (older server builds).
              try {
                const r = await getReport(sessionId);
                if (r.final_report) {
                  dispatch({ type: "COMPLETED", report: r.final_report });
                } else {
                  dispatch({
                    type: "ERROR",
                    message: r.error ?? completedWithoutReportMessage,
                    errorKind: r.error_kind ?? inferLLMErrorKind(r.error),
                  });
                }
              } catch {
                dispatch({
                  type: "ERROR",
                  message: completedWithoutReportMessage,
                  errorKind: null,
                });
              }
            }
            return;
          }
          if (res.status === "cancelled") {
            dispatch({ type: "CANCELLED" });
            return;
          }
          if (res.question && res.status === "waiting_for_answer") {
            dispatch({
              type: "QUESTION",
              question: res.question,
              turnIdx: res.turn_idx ?? null,
              maxTurns: res.max_turns ?? null,
              previousEvaluation: res.previous_turn_evaluation ?? null,
            });
            return;
          }
          // status === "pending" => keep polling; tiny yield to keep
          // the event loop responsive between network hops.
          await new Promise((r) => setTimeout(r, 250));
        } catch (err) {
          if (ctrl.signal.aborted) return;
          const msg =
            err instanceof ApiError
              ? `${err.status}: ${err.message}`
              : err instanceof Error
                ? err.message
                : String(err);
          dispatch({
            type: "ERROR",
            message: msg,
            errorKind: inferLLMErrorKind(err),
            retryable: false,
          });
          return;
        }
      }
    },
    [sessionId],
  );

  const begin = useCallback(
    async (ctrl: AbortController) => {
      dispatch({ type: "START" });
      try {
        const r = await resumeSession(sessionId);
        if (ctrl.signal.aborted) return;
        if (r.status === "completed" && r.final_report) {
          dispatch({ type: "COMPLETED", report: r.final_report ?? null });
          return;
        }
        if (r.status === "completed") {
          dispatch({
            type: "ERROR",
            message: completedWithoutReportMessage,
            errorKind: null,
          });
          return;
        }
        if (r.status === "error") {
          dispatch({
            type: "ERROR",
            message: r.error ?? "面试过程中出现了问题。",
            errorKind: r.error_kind ?? inferLLMErrorKind(r.error),
            retryable: r.retryable,
          });
          return;
        }
        if (r.status === "cancelled") {
          dispatch({ type: "CANCELLED" });
          return;
        }
        if (r.question) {
          dispatch({
            type: "RESUMED",
            question: r.question,
            turnIdx: r.turn_idx ?? null,
            maxTurns: r.max_turns ?? null,
          });
          return;
        }
        // No question ready yet; fall through into the long-poll loop.
        await pollLoop(ctrl);
      } catch (err) {
        if (ctrl.signal.aborted) return;
        const msg =
          err instanceof ApiError
            ? `${err.status}: ${err.message}`
            : err instanceof Error
              ? err.message
              : String(err);
        dispatch({
          type: "ERROR",
          message: msg,
          errorKind: inferLLMErrorKind(err),
          retryable: false,
        });
      }
    },
    [sessionId, pollLoop],
  );

  useEffect(() => {
    mountedRef.current = true;
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    void begin(ctrl);
    return () => {
      mountedRef.current = false;
      ctrl.abort();
    };
  }, [begin]);

  const afterAnswerSubmitted = useCallback(() => {
    // Caller just POSTed /answer; discard current question and
    // re-enter the polling loop to fetch the next one.
    dispatch({ type: "SUBMITTING" });
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    void pollLoop(ctrl);
  }, [pollLoop]);

  const afterQuestionRetryRequested = useCallback(() => {
    dispatch({ type: "START" });
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    void pollLoop(ctrl);
  }, [pollLoop]);

  return { state, afterAnswerSubmitted, afterQuestionRetryRequested };
}
