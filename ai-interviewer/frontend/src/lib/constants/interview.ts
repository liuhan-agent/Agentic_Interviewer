import type { InterviewHistoryStatus } from "@/lib/storage/interviewHistory";
import type { PollStatus } from "@/lib/api/types";

export const DIMENSION_LABELS: Record<string, string> = {
  technical_depth: "技术深度",
  problem_solving: "问题解决",
  communication: "沟通表达",
  system_design: "系统设计",
  coding_quality: "代码质量",
  project_experience: "项目经验",
  product_thinking: "产品思维",
  architecture: "架构能力",
  behavioral: "行为面试",
  culture_fit: "文化匹配",
  leadership: "技术领导力",
  user_insight: "用户洞察",
  requirement_analysis: "需求分析",
  prioritization: "优先级判断",
  metrics_thinking: "指标思维",
  stakeholder_management: "协同推进",
  user_growth: "用户增长",
  content_operations: "内容运营",
  data_analysis: "数据分析",
  campaign_execution: "活动执行",
  process_optimization: "流程优化",
  customer_discovery: "客户发现",
  solution_matching: "方案匹配",
  objection_handling: "异议处理",
  negotiation: "商务谈判",
  pipeline_management: "销售漏斗管理",
  market_insight: "市场洞察",
  brand_strategy: "品牌策略",
  campaign_planning: "营销策划",
  channel_growth: "渠道增长",
  content_creativity: "内容创意",
  talent_acquisition: "人才招聘",
  employee_relations: "员工关系",
  organization_development: "组织发展",
  policy_compliance: "制度合规",
  service_orientation: "服务意识",
  customer_empathy: "客户同理心",
  issue_diagnosis: "问题诊断",
  solution_delivery: "方案交付",
  escalation_management: "升级管理",
  retention_growth: "留存增长",
  goal_setting: "目标设定",
  team_leadership: "团队领导",
  decision_making: "决策判断",
  execution_management: "执行管理",
  cross_functional_alignment: "跨部门协同",
};

export function formatDimensionName(id: string): string {
  return DIMENSION_LABELS[id] ?? id.replaceAll("_", " ");
}

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
