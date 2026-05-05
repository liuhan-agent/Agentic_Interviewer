import type { InterviewHistoryStatus } from "@/lib/storage/interviewHistory";
import type { PollStatus } from "@/lib/api/types";

export interface StatusFilterOption {
  id: InterviewHistoryStatus | "all";
  label: string;
}

export const STATUS_FILTER_OPTIONS: readonly StatusFilterOption[] = [
  { id: "all", label: "全部" },
  { id: "running", label: "进行中" },
  { id: "done", label: "已完成" },
  { id: "failed", label: "需处理" },
  { id: "cancelled", label: "已取消" },
] as const;

export type SortField = "createdAt" | "overallScore" | "lastVisitedAt" | "status";
export type SortDirection = "asc" | "desc";

export interface SortOption {
  field: SortField;
  direction: SortDirection;
  label: string;
}

export const SORT_OPTIONS: readonly SortOption[] = [
  { field: "createdAt", direction: "desc", label: "最新创建" },
  { field: "createdAt", direction: "asc", label: "最早创建" },
  { field: "overallScore", direction: "desc", label: "分数最高" },
  { field: "overallScore", direction: "asc", label: "分数最低" },
  { field: "lastVisitedAt", direction: "desc", label: "最近访问" },
] as const;

export const DEFAULT_SORT: SortOption = SORT_OPTIONS[0];

export function mapPollStatusToLocal(status: PollStatus | string): InterviewHistoryStatus {
  switch (status) {
    case "completed":
      return "done";
    case "cancelled":
      return "cancelled";
    case "error":
      return "failed";
    case "pending":
    case "waiting_for_answer":
    case "running":
    default:
      return "running";
  }
}

export const DEFAULT_DIMENSIONS = [
  { id: "technical_depth", label: "技术深度" },
  { id: "problem_solving", label: "问题解决" },
  { id: "communication", label: "沟通表达" },
] as const;
