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

export type SortField = "lastVisitedAt" | "createdAt" | "overallScore";
export type SortDirection = "asc" | "desc";

export interface SortFieldOption {
  field: SortField;
  label: string;
}

export const SORT_FIELD_OPTIONS: readonly SortFieldOption[] = [
  { field: "lastVisitedAt", label: "最近访问" },
  { field: "createdAt", label: "创建时间" },
  { field: "overallScore", label: "面试分数" },
] as const;

export const DEFAULT_SORT_FIELD: SortField = "lastVisitedAt";
export const DEFAULT_SORT_DIRECTION: SortDirection = "desc";

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
