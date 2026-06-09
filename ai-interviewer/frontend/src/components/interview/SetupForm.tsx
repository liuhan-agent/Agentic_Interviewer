"use client";

/**
 * Job-seeker-facing setup flow.
 *
 * Three visible steps + a tucked-away "advanced" panel for power users.
 * Engineering jargon (rubric_dimensions, quality_threshold, turn budget)
 * is hidden behind sensible defaults; the dimensions list is inferred
 * from the optional JD via the backend `jd/parse` endpoint, with a
 * clean default trio when no JD is provided.
 *
 * Step 1: What direction
 *   - Internet roles are supported now.
 *   - Other industries are shown as future placeholders.
 * Step 2: Who are you
 *   - Drag/drop or paste resume.
 *   - "AI 已读懂你的简历" preview card with three sub-tabs
 *     (summary / skills / highlights), all editable inline.
 * Step 3: What role
 *   - Title + level (dropdown).
 *   - Optional JD textarea -> auto-extracts required_skills +
 *     rubric_dimensions, rendered as removable pill chips.
 *   - Depth picker (quick / standard / deep) -> max_turns.
 *   - Collapsed advanced panel (numeric controls).
 */

import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { useForm, type FieldErrors } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import {
  AlertCircle,
  ArrowRight,
  Briefcase,
  CheckCircle2,
  ChevronDown,
  Clock,
  FileText,
  Info,
  Key,
  Loader2,
  Sparkles,
  Upload,
  User,
  Wand2,
  X,
} from "lucide-react";
import { AnimatePresence, motion } from "framer-motion";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { AuthDialog } from "@/components/auth/AuthDialog";
import { LLMSettingsDialog } from "@/components/layout/LLMSettingsDialog";
import { ApiError } from "@/lib/api/client";
import { getAccountCreditPolicy, getAccountCredits } from "@/lib/api/account";
import {
  createResumeParseJob,
  getJobTemplate,
  getResumeParseJob,
  getSessionSetupSnapshot,
  listDirections,
  listDimensions,
  parseJobSpec,
  startSession,
} from "@/lib/api/interview";
import { jobTemplateAutofillValue } from "@/lib/job-template";
import {
  candidateNameAutofillValue,
  createResumeParseJobForSetup,
  resumeReuploadInputValue,
  resumeJobAutofillValues,
  resumeParsedForSession,
  resumeSourceIdForSession,
  resumeSourceRefFromParseResult,
  type ResumeSourceRef,
} from "@/lib/resume-upload";
import type {
  DimensionOption,
  InterviewDirection,
  ParseJobSpecResponse,
  ParseResumeStatus,
  ParseResumeResponse,
  ResumeParseAudit,
  ResumeParseJobResponse,
  ResumeCandidateProfile,
  ResumeFocusArea,
  ResumeProject,
  SessionSetupSnapshotResponse,
  StartSessionRequest,
} from "@/lib/api/types";
import { useAuth } from "@/lib/auth/useAuth";
import { getCreditStartGateState } from "@/lib/credits";
import {
  buildLLMPayload,
  getLLMConfigStatus,
  LLM_CONFIG_EVENT,
  loadLLMConfig,
  loadLLMTestStatus,
  type LLMConfigStatus,
} from "@/lib/llm-config";
import {
  getResumeSetupSnapshot,
  upsertEntry,
  type ResumeSetupSnapshot,
} from "@/lib/storage/interviewHistory";
import {
  getSetupDraft,
  removeSetupDraft,
  upsertSetupDraft,
  type SetupDraftStatus,
} from "@/lib/storage/setupDrafts";

// ---------------------------------------------------------------------------
// Schema & defaults
// ---------------------------------------------------------------------------

const lengthEnum = z.enum(["short", "standard", "deep"]);
type JobLevel = "junior" | "mid" | "senior" | "staff" | "principal";
type DirectionId = string;
type DirectionCategoryId =
  | "internet_tech"
  | "product_ops"
  | "sales_marketing"
  | "functions_service"
  | "management";

const JOB_LEVEL_VALUES: readonly JobLevel[] = [
  "junior",
  "mid",
  "senior",
  "staff",
  "principal",
];

const CANDIDATE_SUMMARY_MAX_LENGTH = 1200;
const CANDIDATE_SKILLS_MAX_COUNT = 40;
const CANDIDATE_SKILL_MAX_LENGTH = 80;
const CANDIDATE_HIGHLIGHTS_MAX_COUNT = 20;
const CANDIDATE_HIGHLIGHT_MAX_LENGTH = 240;
const RESUME_PROJECTS_MAX_COUNT = 12;
const RESUME_PROJECT_NAME_MAX_LENGTH = 120;
const RESUME_PROJECT_ROLE_MAX_LENGTH = 80;
const RESUME_PROJECT_ANCHOR_MAX_COUNT = 8;
const RESUME_PROJECT_ANCHOR_MAX_LENGTH = 160;
const RESUME_FOCUS_AREAS_MAX_COUNT = 20;
const RESUME_FOCUS_LABEL_MAX_LENGTH = 160;
const START_INTERVIEW_PREFETCH_SESSION_ID = "__warmup_interview__";

const emptyStringToUndefined = (value: unknown) =>
  value === "" ? undefined : value;

const requiredTrimmedString = (message: string) =>
  z.string().trim().min(1, message);

function optionalIntegerNumber(min: number, max: number, message: string) {
  return z.preprocess(
    emptyStringToUndefined,
    z.coerce
      .number({ invalid_type_error: message })
      .int(message)
      .min(min, message)
      .max(max, message)
      .optional(),
  );
}

function numberWithEmptyDefault(
  defaultValue: number,
  min: number,
  max: number,
  message: string,
) {
  return z.preprocess(
    (value) => (value === "" ? defaultValue : value),
    z.coerce
      .number({ invalid_type_error: message })
      .min(min, message)
      .max(max, message),
  );
}

type SetupDirection = {
  id: DirectionId;
  industry?: string;
  label: string;
  desc: string;
  defaultTitle: string;
  level: JobLevel;
  dimensions: DimensionOption[];
  skills: string[];
};

const DIRECTION_CATEGORIES: ReadonlyArray<{
  id: DirectionCategoryId;
  label: string;
  desc: string;
}> = [
  {
    id: "internet_tech",
    label: "互联网技术",
    desc: "开发、算法、架构、运维",
  },
  {
    id: "product_ops",
    label: "产品 / 运营",
    desc: "产品规划、用户增长、内容运营",
  },
  {
    id: "sales_marketing",
    label: "销售 / 市场",
    desc: "客户开拓、商务谈判、品牌增长",
  },
  {
    id: "functions_service",
    label: "职能 / 服务",
    desc: "HR、客服、客户成功",
  },
  {
    id: "management",
    label: "管理",
    desc: "团队管理、协作推进、经营决策",
  },
];

const DIRECTION_CATEGORY_BY_ID: Record<string, DirectionCategoryId> = {
  java_backend: "internet_tech",
  frontend: "internet_tech",
  ai_fullstack: "internet_tech",
  mobile: "internet_tech",
  ai_agent: "internet_tech",
  sre: "internet_tech",
  ai_algorithm: "internet_tech",
  architect: "internet_tech",
  product_manager: "product_ops",
  operations: "product_ops",
  sales_business: "sales_marketing",
  marketing_brand: "sales_marketing",
  hr_function: "functions_service",
  customer_success: "functions_service",
  general_management: "management",
};

const DIRECTION_CARD_DESC_BY_ID: Record<string, string> = {
  java_backend: "适合后端业务、接口、数据库和分布式系统相关岗位",
  frontend: "适合 Web、H5、管理后台、小程序等前端岗位",
  ai_fullstack: "适合需要前后端和 AI 能力结合的岗位",
  mobile: "适合 iOS、Android、Flutter、React Native 等移动端岗位",
  ai_agent: "适合 Agent、RAG、工具调用和 AI 应用工程岗位",
  sre: "适合运维、稳定性、监控、发布和故障处理岗位",
  ai_algorithm: "适合机器学习、深度学习、模型评估和算法落地岗位",
  architect: "适合架构设计、技术方案、技术管理和专家岗",
  product_manager: "适合产品规划、需求分析、用户体验和业务推进岗位",
  operations: "适合用户运营、内容运营、活动运营和数据运营岗位",
  sales_business: "适合客户拓展、方案销售、商务谈判和回款推进岗位",
  marketing_brand: "适合市场推广、品牌、渠道增长和内容传播岗位",
  hr_function: "适合招聘、员工关系、组织发展和职能支持岗位",
  customer_success: "适合客服、客户成功、售后支持和续约增长岗位",
  general_management: "适合团队管理、目标推进、跨部门协作和经营决策岗位",
};

const INTERNET_DIRECTIONS: ReadonlyArray<SetupDirection> = [
  {
    id: "java_backend",
    label: "Java 后端开发",
    desc: "Spring、微服务、数据库、稳定性和系统设计",
    defaultTitle: "Java 后端开发工程师",
    level: "senior",
    dimensions: [
      { id: "technical_depth", label: "技术深度" },
      { id: "system_design", label: "系统设计" },
      { id: "problem_solving", label: "问题解决" },
      { id: "coding_quality", label: "代码质量" },
      { id: "communication", label: "沟通表达" },
    ],
    skills: ["java", "spring", "mysql", "redis", "microservices"],
  },
  {
    id: "frontend",
    label: "前端开发",
    desc: "React/Vue、工程化、性能体验和协作交付",
    defaultTitle: "前端开发工程师",
    level: "senior",
    dimensions: [
      { id: "technical_depth", label: "技术深度" },
      { id: "coding_quality", label: "代码质量" },
      { id: "problem_solving", label: "问题解决" },
      { id: "project_experience", label: "项目经验" },
      { id: "communication", label: "沟通表达" },
    ],
    skills: ["javascript", "typescript", "react", "vue", "frontend"],
  },
  {
    id: "ai_fullstack",
    label: "AI 全栈开发",
    desc: "前后端、LLM 接入、产品落地和端到端交付",
    defaultTitle: "AI 全栈开发工程师",
    level: "senior",
    dimensions: [
      { id: "technical_depth", label: "技术深度" },
      { id: "system_design", label: "系统设计" },
      { id: "product_thinking", label: "产品思维" },
      { id: "project_experience", label: "项目经验" },
      { id: "communication", label: "沟通表达" },
    ],
    skills: ["typescript", "python", "llm", "rag", "fullstack"],
  },
  {
    id: "mobile",
    label: "移动端开发",
    desc: "iOS/Android、跨端、性能、稳定性和体验",
    defaultTitle: "移动端开发工程师",
    level: "senior",
    dimensions: [
      { id: "technical_depth", label: "技术深度" },
      { id: "problem_solving", label: "问题解决" },
      { id: "coding_quality", label: "代码质量" },
      { id: "project_experience", label: "项目经验" },
      { id: "communication", label: "沟通表达" },
    ],
    skills: ["android", "ios", "flutter", "react native", "mobile"],
  },
  {
    id: "ai_agent",
    label: "AI Agent 开发",
    desc: "Agent 架构、工具调用、记忆、评测和工程可靠性",
    defaultTitle: "AI Agent 开发工程师",
    level: "senior",
    dimensions: [
      { id: "technical_depth", label: "技术深度" },
      { id: "system_design", label: "系统设计" },
      { id: "problem_solving", label: "问题解决" },
      { id: "product_thinking", label: "产品思维" },
      { id: "communication", label: "沟通表达" },
    ],
    skills: ["llm", "agent", "rag", "python", "tool calling"],
  },
  {
    id: "sre",
    label: "运维 / SRE",
    desc: "可观测性、故障处理、容量、发布和稳定性治理",
    defaultTitle: "运维 / SRE 工程师",
    level: "senior",
    dimensions: [
      { id: "technical_depth", label: "技术深度" },
      { id: "system_design", label: "系统设计" },
      { id: "problem_solving", label: "问题解决" },
      { id: "project_experience", label: "项目经验" },
      { id: "communication", label: "沟通表达" },
    ],
    skills: ["linux", "kubernetes", "observability", "devops", "sre"],
  },
  {
    id: "ai_algorithm",
    label: "AI 算法",
    desc: "模型能力、实验设计、数据、评测和业务落地",
    defaultTitle: "AI 算法工程师",
    level: "senior",
    dimensions: [
      { id: "technical_depth", label: "技术深度" },
      { id: "problem_solving", label: "问题解决" },
      { id: "project_experience", label: "项目经验" },
      { id: "product_thinking", label: "产品思维" },
      { id: "communication", label: "沟通表达" },
    ],
    skills: ["python", "machine learning", "deep learning", "llm", "evaluation"],
  },
  {
    id: "architect",
    label: "架构师 / 技术专家",
    desc: "复杂系统设计、技术决策、治理、影响力和团队协同",
    defaultTitle: "架构师 / 技术专家",
    level: "staff",
    dimensions: [
      { id: "system_design", label: "系统设计" },
      { id: "technical_depth", label: "技术深度" },
      { id: "leadership", label: "领导力" },
      { id: "problem_solving", label: "问题解决" },
      { id: "communication", label: "沟通表达" },
    ],
    skills: ["architecture", "distributed systems", "scalability", "leadership"],
  },
];

function directionById(id: DirectionId) {
  return INTERNET_DIRECTIONS.find((item) => item.id === id) ?? INTERNET_DIRECTIONS[0];
}

function setupDirectionFromApi(item: InterviewDirection): SetupDirection {
  return {
    id: item.direction,
    industry: item.industry,
    label: item.label,
    desc: DIRECTION_CARD_DESC_BY_ID[item.direction] || item.default_title,
    defaultTitle: item.default_title,
    level: item.default_level,
    dimensions: item.dimension_catalog.map((dim) => ({
      id: dim.id,
      label: dim.label,
    })),
    skills: item.skills,
  };
}

function directionByIdFrom(
  directions: ReadonlyArray<SetupDirection>,
  id: DirectionId,
) {
  return directions.find((item) => item.id === id) ?? directions[0] ?? directionById(id);
}

function categoryForDirection(direction: SetupDirection): DirectionCategoryId {
  const configured = DIRECTION_CATEGORY_BY_ID[direction.id];
  if (configured) return configured;
  if (direction.industry === "internet") return "internet_tech";
  return "management";
}

function groupedDirections(directions: ReadonlyArray<SetupDirection>) {
  return DIRECTION_CATEGORIES.map((category) => ({
    ...category,
    directions: directions.filter(
      (direction) => categoryForDirection(direction) === category.id,
    ),
  })).filter((group) => group.directions.length > 0);
}

const schema = z.object({
  // Step 1
  interview_industry: z.string().min(1),
  interview_direction: z.string().min(1),

  // Step 2
  candidate_name: requiredTrimmedString("请填写称呼"),
  candidate_summary: z
    .string()
    .max(CANDIDATE_SUMMARY_MAX_LENGTH, "简历概要太长，请精简到 1200 字以内")
    .optional()
    .default(""),
  candidate_skills: z.string().optional().default(""),
  candidate_highlights: z.string().optional().default(""),

  // Step 3
  job_title: requiredTrimmedString("请填写岗位名称"),
  job_level: z.enum(["junior", "mid", "senior", "staff", "principal"]),
  job_description: z.string().max(50000, "JD 过长，请精简后再试").optional().default(""),

  // Advanced (numeric overrides). Hidden behind a disclosure panel.
  length: lengthEnum.default("standard"),
  max_turns_override: optionalIntegerNumber(1, 20, "请输入 1-20 的整数"),
  quality_threshold: numberWithEmptyDefault(7, 0, 10, "请输入 0-10 的数字"),
  turn_budget_override: optionalIntegerNumber(1, 30, "请输入 1-30 的整数"),
});

type FormValues = z.infer<typeof schema>;

const DEFAULTS: FormValues = {
  interview_industry: "internet",
  interview_direction: "java_backend",
  candidate_name: "",
  candidate_summary: "",
  candidate_skills: "",
  candidate_highlights: "",
  job_title: "Java 后端开发工程师",
  job_level: "senior",
  job_description: "",
  length: "standard",
  quality_threshold: 7,
};

const LENGTH_OPTIONS: ReadonlyArray<{
  id: "short" | "standard" | "deep";
  label: string;
  desc: string;
  turns: number;
}> = [
  { id: "short", label: "快速练习", desc: "目标 5 轮 · 快速校准", turns: 5 },
  { id: "standard", label: "标准面试", desc: "目标 8 轮 · 核心覆盖", turns: 8 },
  { id: "deep", label: "深度追问", desc: "目标 12 轮 · 压力追问", turns: 12 },
];

const STEPS = [
  { id: 0, label: "面试方向", icon: <Briefcase className="h-4 w-4" /> },
  { id: 1, label: "你是谁", icon: <User className="h-4 w-4" /> },
  { id: 2, label: "面试岗位", icon: <Wand2 className="h-4 w-4" /> },
] as const;

const ACCEPTED_TYPES =
  ".pdf,.docx,.txt,.md,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain,text/markdown";
const MAX_UPLOAD_BYTES = 5 * 1024 * 1024;
const ACCEPTED_FILE_EXTENSIONS = [".pdf", ".docx", ".txt", ".md", ".markdown"];
const ACCEPTED_MIME_TYPES = new Set([
  "application/pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "text/plain",
  "text/markdown",
]);
const RESUME_DRAFT_KEY = "resume_draft";
const STEP_FIELDS: (keyof FormValues)[][] = [
  ["interview_industry", "interview_direction"],
  ["candidate_name"],
  ["job_title", "job_level"],
];
const ADVANCED_FIELD_NAMES: (keyof FormValues)[] = [
  "max_turns_override",
  "quality_threshold",
  "turn_budget_override",
];

// Default dimension trio when no JD is supplied. Matches the backend
// fallback so behaviour is consistent across both call sites.
const DEFAULT_DIMENSIONS: DimensionOption[] = [
  { id: "technical_depth", label: "技术深度" },
  { id: "problem_solving", label: "问题解决" },
  { id: "communication", label: "沟通表达" },
];

const FIELD_STEP: Partial<Record<keyof FormValues, number>> = {
  interview_industry: 0,
  interview_direction: 0,
  candidate_name: 1,
  job_title: 2,
  job_level: 2,
  length: 2,
  max_turns_override: 2,
  quality_threshold: 2,
  turn_budget_override: 2,
};

const FIELD_LABEL: Partial<Record<keyof FormValues, string>> = {
  interview_direction: "面试方向",
  candidate_name: "称呼",
  job_title: "岗位名称",
  job_level: "目标级别",
  length: "面试深度",
  max_turns_override: "问题轮数",
  quality_threshold: "通过阈值",
  turn_budget_override: "追问预算",
};

const ERROR_FIELD_PRIORITY: (keyof FormValues)[] = [
  "interview_direction",
  "candidate_name",
  "job_title",
  "job_level",
  "length",
  "max_turns_override",
  "quality_threshold",
  "turn_budget_override",
];

// ---------------------------------------------------------------------------
// Local helpers
// ---------------------------------------------------------------------------

function splitCsv(s: string): string[] {
  return s
    .split(/[\n,，]/)
    .map((x) => x.trim())
    .filter(Boolean);
}

function joinCsv(items: string[]): string {
  return items.join(", ");
}

function firstFormError(
  formErrors: FieldErrors<FormValues>,
): { field: keyof FormValues; message: string; step: number } | null {
  const firstKey =
    ERROR_FIELD_PRIORITY.find((key) => Boolean(formErrors[key])) ??
    (Object.keys(formErrors)[0] as keyof FormValues | undefined);
  if (!firstKey) return null;

  const error = formErrors[firstKey];
  const label = FIELD_LABEL[firstKey] ?? "必填信息";
  const message =
    typeof error?.message === "string"
      ? error.message
      : `请先补全${label}`;
  return {
    field: firstKey,
    message,
    step: FIELD_STEP[firstKey] ?? 0,
  };
}

function isAcceptedResumeFile(file: File): boolean {
  const name = file.name.toLowerCase();
  const hasAcceptedExtension = ACCEPTED_FILE_EXTENSIONS.some((ext) =>
    name.endsWith(ext),
  );
  return hasAcceptedExtension || ACCEPTED_MIME_TYPES.has(file.type);
}

function fieldErrorId(field: keyof FormValues): string {
  return `${String(field)}-error`;
}

function safeSessionGetItem(key: string): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.sessionStorage.getItem(key);
  } catch {
    return null;
  }
}

function safeSessionSetItem(key: string, value: string): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(key, value);
  } catch {
    /* Storage can be unavailable in private mode; never block the form. */
  }
}

function safeSessionRemoveItem(key: string): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.removeItem(key);
  } catch {
    /* ignore storage cleanup failures */
  }
}

function normaliseProjects(projects?: ResumeProject[]): ResumeProject[] {
  return (projects ?? [])
    .filter((project) => project.name?.trim())
    .map((project, idx) => ({
      ...project,
      id: project.id || `proj-${idx + 1}`,
      name: project.name.trim(),
      role: project.role?.trim() || undefined,
      tech_stack: project.tech_stack ?? [],
      responsibilities: project.responsibilities ?? [],
      achievements: project.achievements ?? [],
      question_anchors: project.question_anchors ?? [],
    }));
}

function normaliseFocusAreas(focusAreas?: ResumeFocusArea[]): ResumeFocusArea[] {
  return (focusAreas ?? [])
    .filter((focus) => focus.label?.trim())
    .map((focus, idx) => ({
      ...focus,
      id: focus.id || `focus-${idx + 1}`,
      label: focus.label.trim(),
      project_id: focus.project_id ?? null,
      dimensions: focus.dimensions ?? [],
      skills: focus.skills ?? [],
      priority: focus.priority ?? idx + 1,
    }));
}

function resumeSetupSnapshotFromSession(
  response: SessionSetupSnapshotResponse,
): ResumeSetupSnapshot {
  const parsed = response.candidate.resume_parsed ?? {};
  return {
    candidate_name: response.candidate.name,
    candidate_summary: parsed.summary ?? "",
    candidate_skills: joinCsv(parsed.skills ?? []),
    candidate_highlights: (parsed.highlights ?? []).join("\n"),
    resumeProjects: parsed.projects as unknown as Record<string, unknown>[] | undefined,
    resumeFocusAreas: parsed.focus_areas as
      | Record<string, unknown>[]
      | undefined,
    resumeConcerns: parsed.concerns ?? [],
    resumeCandidateProfile: (parsed.candidate_profile ?? {}) as unknown as Record<
      string,
      unknown
    >,
    resumeParseAudit: response.candidate.resume_parse_audit as unknown as
      | Record<string, unknown>
      | undefined,
  };
}

function asJobLevel(value: string | undefined): JobLevel | null {
  return JOB_LEVEL_VALUES.includes(value as JobLevel)
    ? (value as JobLevel)
    : null;
}

type UploadStatus =
  | { kind: "idle" }
  | {
      kind: "parsing";
      filename: string;
      draftId?: string;
      jobId?: string;
      expiresAt?: string;
    }
  | {
      kind: "success";
      filename: string;
      parseStatus?: ParseResumeStatus;
      draftId?: string;
    }
  | {
      kind: "error";
      filename: string;
      message: string;
      draftId?: string;
      jobId?: string;
      expiresAt?: string;
    };

type JdStatus =
  | { kind: "idle" }
  | { kind: "parsing" }
  | { kind: "success"; rationale: string }
  | { kind: "error"; message: string };

function createSetupDraftId(): string {
  if (
    typeof crypto !== "undefined" &&
    typeof crypto.randomUUID === "function"
  ) {
    return crypto.randomUUID();
  }
  return `draft-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

function uploadDraftId(status: UploadStatus): string | undefined {
  return status.kind === "idle" ? undefined : status.draftId;
}

function setupDraftStatusFromResult(result: ParseResumeResponse): SetupDraftStatus {
  return result.parse_status?.mode === "basic" ? "basic_ready" : "ready";
}

function setupDraftStatusFromJob(job: ResumeParseJobResponse): SetupDraftStatus {
  if (job.status === "expired") return "expired";
  if (job.status === "failed") return "failed";
  if (job.status === "completed" && job.result) {
    return setupDraftStatusFromResult(job.result);
  }
  return "parsing";
}

function isUsingByokConfig(payload: StartSessionRequest["llm_config"]): boolean {
  if (!payload) return false;
  if (payload.api_key?.trim()) return true;
  const roleOverrides = payload.role_overrides;
  if (!roleOverrides) return false;
  return Object.values(roleOverrides).some((override) =>
    Boolean(override?.api_key?.trim()),
  );
}

// ---------------------------------------------------------------------------
// SetupForm root
// ---------------------------------------------------------------------------

export function SetupForm() {
  const router = useRouter();
  const auth = useAuth();
  const searchParams = useSearchParams();
  const draftIdFromQuery = searchParams.get("draft_id");
  const [step, setStep] = useState(0);
  const [serverError, setServerError] = useState<string | null>(null);
  const [enableVideoAnalysis, setEnableVideoAnalysis] = useState(false);
  const [llmStatus, setLlmStatus] = useState<LLMConfigStatus>("missing");
  const [currentLlmPayload, setCurrentLlmPayload] =
    useState<StartSessionRequest["llm_config"]>(undefined);
  const [serverDirections, setServerDirections] = useState<SetupDirection[]>([]);
  const [isInterviewStartPending, setInterviewStartPending] = useState(false);
  const [creditPolicy, setCreditPolicy] = useState<{
    enforced: boolean;
    free_grant: number;
    requires_login_for_platform_hosted?: boolean;
  } | null>(null);
  const [creditBalance, setCreditBalance] = useState<number | null>(null);
  const [startCreditNotice, setStartCreditNotice] = useState<string | null>(null);

  // Resume upload state
  const [upload, setUpload] = useState<UploadStatus>({ kind: "idle" });
  const [resumeProjects, setResumeProjects] = useState<ResumeProject[]>([]);
  const [resumeFocusAreas, setResumeFocusAreas] = useState<ResumeFocusArea[]>([]);
  const [resumeConcerns, setResumeConcerns] = useState<string[]>([]);
  const [resumeCandidateProfile, setResumeCandidateProfile] =
    useState<ResumeCandidateProfile>({});
  const [resumeParseAudit, setResumeParseAudit] = useState<ResumeParseAudit | null>(null);
  const [resumeSource, setResumeSource] = useState<ResumeSourceRef | null>(null);
  const [candidateNameFromResume, setCandidateNameFromResume] = useState(false);
  const [jobTitleFromResume, setJobTitleFromResume] = useState(false);
  const [jobLevelFromResume, setJobLevelFromResume] = useState(false);
  const [jobTitleEdited, setJobTitleEdited] = useState(false);
  const [jobLevelEdited, setJobLevelEdited] = useState(false);
  const jobTitleEditedRef = useRef(false);
  const jobLevelEditedRef = useRef(false);
  const [isDragging, setIsDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const uploadRequestRef = useRef(0);
  const restoredDraftRef = useRef<string | null>(null);
  const restoredResumeFromRef = useRef<string | null>(null);

  const [hasDraft, setHasDraft] = useState(false);

  useEffect(() => {
    const draft = safeSessionGetItem(RESUME_DRAFT_KEY);
    if (draft && upload.kind === "idle") {
      setHasDraft(true);
    }
  }, [upload.kind]);

  function loadDraft() {
    try {
      const draft = JSON.parse(safeSessionGetItem(RESUME_DRAFT_KEY) || "{}");
      if (draft.candidate_summary) setValue("candidate_summary", draft.candidate_summary, { shouldValidate: true });
      if (draft.candidate_skills) setValue("candidate_skills", draft.candidate_skills, { shouldValidate: true });
      if (draft.candidate_highlights) setValue("candidate_highlights", draft.candidate_highlights, { shouldValidate: true });
      if (draft.resumeProjects) setResumeProjects(draft.resumeProjects);
      if (draft.resumeFocusAreas) setResumeFocusAreas(draft.resumeFocusAreas);
      if (draft.resumeCandidateProfile) setResumeCandidateProfile(draft.resumeCandidateProfile);
      if (draft.resumeParseAudit) setResumeParseAudit(draft.resumeParseAudit);
      const resumeSourceId =
        typeof draft.resumeSourceId === "string" ? draft.resumeSourceId.trim() : "";
      if (resumeSourceId) {
        setResumeSource({
          id: resumeSourceId,
          ...(typeof draft.resumeSourceExpiresAt === "string"
            ? { expiresAt: draft.resumeSourceExpiresAt }
            : {}),
        });
      }
      setHasDraft(false);
    } catch {}
  }

  function clearDraft() {
    safeSessionRemoveItem(RESUME_DRAFT_KEY);
    setHasDraft(false);
  }

  // JD parse state
  const [jdStatus, setJdStatus] = useState<JdStatus>({ kind: "idle" });
  const jdDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const jdTemplateRequestRef = useRef(0);
  const jdUserEditedRef = useRef(false);
  const practiceFocusAppliedRef = useRef(false);
  const [allDimensions, setAllDimensions] = useState<DimensionOption[]>([]);
  const [selectedDims, setSelectedDims] =
    useState<DimensionOption[]>(() => directionById(DEFAULTS.interview_direction).dimensions);
  const [practiceFocusDims, setPracticeFocusDims] = useState<DimensionOption[]>([]);
  // Required skills inferred by the JD parser. Kept separate from
  // candidate skills so the rubric reflects what the *role* demands,
  // not what the candidate has.
  const [jdRequiredSkills, setJdRequiredSkills] = useState<string[]>([]);

  // Advanced panel toggle
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const directionOptions =
    serverDirections.length > 0 ? serverDirections : INTERNET_DIRECTIONS;
  const resolveDirection = useCallback(
    (id: DirectionId) => directionByIdFrom(directionOptions, id),
    [directionOptions],
  );

  const {
    register,
    handleSubmit,
    setValue,
    setFocus,
    getValues,
    watch,
    trigger,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: DEFAULTS,
  });

  const watchedSummary = watch("candidate_summary");
  const watchedSkills = watch("candidate_skills");
  const watchedHighlights = watch("candidate_highlights");
  const resumeFieldsLocked = upload.kind === "parsing";
  const isStartingInterview = isSubmitting || isInterviewStartPending;
  const isByokStart = isUsingByokConfig(currentLlmPayload);
  const startGate = getCreditStartGateState({
    policy: creditPolicy,
    auth,
    creditBalance,
    isByok: isByokStart,
  });
  const shouldUsePlatformCredits = startGate.usesPlatformCredits;
  const platformCreditNotice = startGate.notice;

  useEffect(() => {
    if (step === STEPS.length - 1) {
      router.prefetch(`/interview/${START_INTERVIEW_PREFETCH_SESSION_ID}`);
    }
  }, [router, step]);

  useEffect(() => {
    if (!isStartingInterview) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, [isStartingInterview]);

  useEffect(() => {
    jobTitleEditedRef.current = jobTitleEdited;
  }, [jobTitleEdited]);

  useEffect(() => {
    jobLevelEditedRef.current = jobLevelEdited;
  }, [jobLevelEdited]);

  const applyResumeSetupSnapshot = useCallback(
    (snapshot: ResumeSetupSnapshot) => {
      if (snapshot.candidate_name) {
        setValue("candidate_name", snapshot.candidate_name, {
          shouldValidate: true,
        });
        setCandidateNameFromResume(true);
      }
      if (snapshot.candidate_summary !== undefined) {
        setValue("candidate_summary", snapshot.candidate_summary, {
          shouldValidate: true,
        });
      }
      if (snapshot.candidate_skills !== undefined) {
        setValue("candidate_skills", snapshot.candidate_skills, {
          shouldValidate: true,
        });
      }
      if (snapshot.candidate_highlights !== undefined) {
        setValue("candidate_highlights", snapshot.candidate_highlights, {
          shouldValidate: true,
        });
      }
      setResumeProjects(
        normaliseProjects(snapshot.resumeProjects as ResumeProject[] | undefined),
      );
      setResumeFocusAreas(
        normaliseFocusAreas(
          snapshot.resumeFocusAreas as ResumeFocusArea[] | undefined,
        ),
      );
      setResumeConcerns(snapshot.resumeConcerns ?? []);
      setResumeCandidateProfile(
        (snapshot.resumeCandidateProfile as ResumeCandidateProfile | undefined) ??
          {},
      );
      setResumeParseAudit(
        (snapshot.resumeParseAudit as ResumeParseAudit | undefined) ?? null,
      );
      setUpload({
        kind: "success",
        filename: "已沿用上一场简历解析结果",
      });
      setHasDraft(false);
    },
    [setValue],
  );

  const applySessionSetupSnapshot = useCallback(
    (response: SessionSetupSnapshotResponse) => {
      applyResumeSetupSnapshot(resumeSetupSnapshotFromSession(response));

      const { job_spec: jobSpec } = response;
      const title = jobSpec.title?.trim();
      if (title && !jobTitleEditedRef.current) {
        setValue("job_title", title, { shouldValidate: true });
        setJobTitleFromResume(false);
      }

      const level = asJobLevel(jobSpec.level);
      if (level && !jobLevelEditedRef.current) {
        setValue("job_level", level, { shouldValidate: true });
        setJobLevelFromResume(false);
      }

      if (jobSpec.interview_industry) {
        setValue("interview_industry", jobSpec.interview_industry, {
          shouldValidate: true,
        });
      }
      if (jobSpec.interview_direction) {
        setValue("interview_direction", jobSpec.interview_direction, {
          shouldValidate: true,
        });
      }
      if (jobSpec.required_skills.length > 0) {
        setJdRequiredSkills(jobSpec.required_skills);
      }
    },
    [applyResumeSetupSnapshot, setValue],
  );

  useEffect(() => {
    const sourceSessionId = searchParams.get("resume_from");
    if (!sourceSessionId || restoredResumeFromRef.current === sourceSessionId) {
      return;
    }
    restoredResumeFromRef.current = sourceSessionId;
    const localSnapshot = getResumeSetupSnapshot(sourceSessionId);
    if (localSnapshot) {
      applyResumeSetupSnapshot(localSnapshot);
      return;
    }
    let cancelled = false;
    void getSessionSetupSnapshot(sourceSessionId)
      .then((snapshot) => {
        if (!cancelled) {
          applySessionSetupSnapshot(snapshot);
        }
      })
      .catch(() => {
        /* Old sessions may not have setup snapshots; keep normal setup usable. */
      });
    return () => {
      cancelled = true;
    };
  }, [applyResumeSetupSnapshot, applySessionSetupSnapshot, searchParams]);

  useEffect(() => {
    const timer = setTimeout(() => {
      if (!hasDraft && (resumeProjects.length > 0 || resumeFocusAreas.length > 0 || watchedSummary)) {
        safeSessionSetItem(RESUME_DRAFT_KEY, JSON.stringify({
          candidate_summary: watchedSummary,
          candidate_skills: watchedSkills,
          candidate_highlights: watchedHighlights,
          resumeProjects,
          resumeFocusAreas,
          resumeCandidateProfile,
          resumeParseAudit,
          resumeSourceId: resumeSource?.id,
          resumeSourceExpiresAt: resumeSource?.expiresAt,
        }));
      }
    }, 1000);
    return () => clearTimeout(timer);
  }, [resumeProjects, resumeFocusAreas, resumeCandidateProfile, resumeParseAudit, resumeSource, watchedSummary, watchedSkills, watchedHighlights, hasDraft]);

  useEffect(() => {
    function refreshLlmStatus() {
      setLlmStatus(getLLMConfigStatus(loadLLMConfig(), loadLLMTestStatus()));
      setCurrentLlmPayload(buildLLMPayload());
    }
    refreshLlmStatus();
    window.addEventListener(LLM_CONFIG_EVENT, refreshLlmStatus);
    window.addEventListener("storage", refreshLlmStatus);
    return () => {
      window.removeEventListener(LLM_CONFIG_EVENT, refreshLlmStatus);
      window.removeEventListener("storage", refreshLlmStatus);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    void getAccountCreditPolicy()
      .then((policy) => {
        if (!cancelled) {
          setCreditPolicy({
            enforced: policy.enforced,
            free_grant: policy.free_grant,
            requires_login_for_platform_hosted:
              policy.requires_login_for_platform_hosted,
          });
        }
      })
      .catch(() => {
        if (!cancelled) setCreditPolicy(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    if (!auth.authenticated) {
      setCreditBalance(null);
      return;
    }
    void getAccountCredits()
      .then((credits) => {
        if (!cancelled) setCreditBalance(credits.balance);
      })
      .catch(() => {
        if (!cancelled) setCreditBalance(null);
      });
    return () => {
      cancelled = true;
    };
  }, [auth.authenticated, auth.user?.id]);

  useEffect(() => {
    return () => {
      if (jdDebounceRef.current) clearTimeout(jdDebounceRef.current);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    void listDirections()
      .then((res) => {
        if (cancelled) return;
        const mapped = res.directions.map(setupDirectionFromApi);
        setServerDirections(mapped);
        const current = directionByIdFrom(
          mapped,
          getValues("interview_direction"),
        );
        if (current) {
          setSelectedDims(current.dimensions.slice(0, 5));
          setJdRequiredSkills((prev) =>
            prev.length > 0 ? prev : current.skills,
          );
          setValue("interview_industry", current.industry ?? "internet", {
            shouldValidate: true,
          });
        }
      })
      .catch(() => {
        /* Keep local fallback directions if the endpoint is unavailable. */
      });
    return () => {
      cancelled = true;
    };
  }, [getValues, setValue]);

  // Lazy-load the full dimension catalog the first time the user
  // expands the picker. The catalog is small and static so this is a
  // one-shot fetch.
  useEffect(() => {
    let cancelled = false;
    void listDimensions()
      .then((res) => {
        if (!cancelled) setAllDimensions(res.dimensions);
      })
      .catch(() => {
        /* picker stays in default-only mode if this fails */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const markJobDescriptionEdited = useCallback(() => {
    jdUserEditedRef.current = true;
  }, []);

  const dimensionOptionsFromIds = useCallback(
    (ids: string[], directionId: DirectionId): DimensionOption[] => {
      const direction = resolveDirection(directionId);
      const labels = new Map(
        [...allDimensions, ...direction.dimensions, ...DEFAULT_DIMENSIONS].map(
          (option) => [option.id, option.label],
        ),
      );
      return ids
        .map((id) => id.trim())
        .filter(Boolean)
        .map((id) => ({
          id,
          label: labels.get(id) ?? id.replace(/_/g, " "),
        }));
    },
    [allDimensions, resolveDirection],
  );

  const loadJobTemplate = useCallback(
    async function loadJobTemplate(directionId: DirectionId) {
      const requestId = ++jdTemplateRequestRef.current;
      try {
        const res = await getJobTemplate({
          direction: directionId,
          level: getValues("job_level"),
        });
        if (requestId !== jdTemplateRequestRef.current) return;

        const template = jobTemplateAutofillValue({
          template: res.template,
          userEdited: jdUserEditedRef.current,
        });
        if (!template) return;

        setValue("job_description", template, { shouldValidate: false });
        if (res.skills.length > 0) {
          setJdRequiredSkills(res.skills);
        }
        const dims = dimensionOptionsFromIds(res.rubric_dimensions, directionId);
        if (dims.length > 0) {
          setSelectedDims(dims);
        }
      } catch {
        /* Keep direction defaults if the template endpoint is unavailable. */
      }
    },
    [dimensionOptionsFromIds, getValues, setValue],
  );

  const applyPracticeFocusQuery = useCallback(() => {
    if (practiceFocusAppliedRef.current) return;
    const focusValue = searchParams.get("focus") ?? "";
    const queryLength = searchParams.get("length");
    const queryJobTitle = searchParams.get("job_title");
    const queryJobLevel = searchParams.get("job_level");

    if (queryLength && lengthEnum.options.includes(queryLength as any)) {
      setValue("length", queryLength as FormValues["length"], {
        shouldValidate: true,
      });
    }
    if (queryJobTitle?.trim()) {
      setValue("job_title", queryJobTitle.trim(), { shouldValidate: true });
      setJobTitleEdited(true);
    }
    if (
      queryJobLevel &&
      ["junior", "mid", "senior", "staff", "principal"].includes(queryJobLevel)
    ) {
      setValue("job_level", queryJobLevel as JobLevel, { shouldValidate: true });
      setJobLevelEdited(true);
    }

    const focusIds = focusValue
      .split(",")
      .map((id) => id.trim())
      .filter(Boolean);
    if (focusIds.length > 0) {
      const knownIds = new Set(
        [
          ...allDimensions,
          ...DEFAULT_DIMENSIONS,
          ...directionOptions.flatMap((direction) => direction.dimensions),
        ].map((option) => option.id),
      );
      const validIds = focusIds.filter((id) => knownIds.has(id));
      const resolvedFocus = dimensionOptionsFromIds(
        validIds,
        getValues("interview_direction"),
      );
      if (resolvedFocus.length === 0 && allDimensions.length === 0) return;
      if (resolvedFocus.length > 0) {
        setPracticeFocusDims(resolvedFocus.slice(0, 5));
        setSelectedDims(resolvedFocus.slice(0, 5));
        setStep((prev) => Math.max(prev, 2));
      }
    }

    practiceFocusAppliedRef.current = true;
  }, [
    allDimensions,
    dimensionOptionsFromIds,
    directionOptions,
    getValues,
    searchParams,
    setValue,
  ]);

  useEffect(() => {
    applyPracticeFocusQuery();
  }, [applyPracticeFocusQuery]);

  const applyResumeResult = useCallback(
    (result: ParseResumeResponse) => {
      const candidateName = candidateNameAutofillValue(
        result,
        getValues("candidate_name"),
      );
      if (candidateName) {
        setValue("candidate_name", candidateName, { shouldValidate: true });
        setCandidateNameFromResume(true);
      } else {
        setCandidateNameFromResume(false);
      }
      setResumeCandidateProfile(result.candidate_profile ?? {});
      setResumeParseAudit(result.resume_parse_audit ?? null);
      setResumeSource(resumeSourceRefFromParseResult(result));
      const jobSuggestion = resumeJobAutofillValues({
        profile: result.candidate_profile,
        currentTitle: getValues("job_title"),
        titleDirty: jobTitleEdited,
        levelDirty: jobLevelEdited,
      });
      if (jobSuggestion.jobTitle) {
        setValue("job_title", jobSuggestion.jobTitle, { shouldValidate: true });
        setJobTitleFromResume(true);
      }
      if (jobSuggestion.jobLevel) {
        setValue("job_level", jobSuggestion.jobLevel, { shouldValidate: false });
        setJobLevelFromResume(true);
      }
      if (result.summary) {
        setValue("candidate_summary", result.summary, { shouldValidate: true });
      }
      if (result.skills.length > 0) {
        setValue("candidate_skills", joinCsv(result.skills), {
          shouldValidate: true,
        });
      }
      if (result.highlights.length > 0) {
        setValue("candidate_highlights", result.highlights.join("\n"), {
          shouldValidate: true,
        });
      }
      setResumeProjects(normaliseProjects(result.projects));
      setResumeFocusAreas(normaliseFocusAreas(result.focus_areas));
      setResumeConcerns(result.concerns ?? []);
    },
    [getValues, jobLevelEdited, jobTitleEdited, setValue],
  );

  const handleResumeJobSnapshot = useCallback(
    (
      job: ResumeParseJobResponse,
      draftId: string,
      fallbackFilename: string,
    ): boolean => {
      const filename = job.filename ?? fallbackFilename;
      if (job.status === "running") {
        upsertSetupDraft({
          draftId,
          jobId: job.job_id,
          filename,
          status: "parsing",
          expiresAt: job.expires_at,
        });
        return false;
      }
      if (job.status === "completed" && job.result) {
        applyResumeResult(job.result);
        upsertSetupDraft({
          draftId,
          jobId: job.job_id,
          filename,
          status: setupDraftStatusFromResult(job.result),
          expiresAt: job.expires_at,
        });
        setUpload({
          kind: "success",
          filename,
          parseStatus: job.result.parse_status,
          draftId,
        });
        return true;
      }
      const status = setupDraftStatusFromJob(job);
      upsertSetupDraft({
        draftId,
        jobId: job.job_id,
        filename,
        status,
        expiresAt: job.expires_at,
      });
      setUpload({
        kind: "error",
        filename,
        draftId,
        jobId: job.job_id,
        expiresAt: job.expires_at,
        message:
          job.status === "expired"
            ? "简历解析草稿已过期，请重新上传。"
            : job.error || "简历解析失败，请重新上传或手动填写。",
      });
      return true;
    },
    [applyResumeResult],
  );

  useEffect(() => {
    if (upload.kind !== "parsing" || !upload.jobId || !upload.draftId) return;
    let cancelled = false;
    let timer: number | null = null;
    const poll = async () => {
      try {
        const job = await getResumeParseJob(upload.jobId!);
        if (cancelled) return;
        const done = handleResumeJobSnapshot(
          job,
          upload.draftId!,
          upload.filename,
        );
        if (!done) {
          timer = window.setTimeout(poll, 2500);
        }
      } catch {
        if (!cancelled) {
          timer = window.setTimeout(poll, 5000);
        }
      }
    };
    timer = window.setTimeout(poll, 1200);
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [handleResumeJobSnapshot, upload]);

  useEffect(() => {
    if (!draftIdFromQuery || restoredDraftRef.current === draftIdFromQuery) return;
    restoredDraftRef.current = draftIdFromQuery;
    const draft = getSetupDraft(draftIdFromQuery);
    if (!draft) {
      setStep((prev) => Math.max(prev, 1));
      setUpload({
        kind: "error",
        filename: "resume",
        message: "简历解析草稿已失效，请重新上传。",
      });
      return;
    }
    setStep((prev) => Math.max(prev, 1));
    setUpload({
      kind: "parsing",
      filename: draft.filename,
      draftId: draft.draftId,
      jobId: draft.jobId,
      expiresAt: draft.expiresAt,
    });
    void getResumeParseJob(draft.jobId)
      .then((job) => handleResumeJobSnapshot(job, draft.draftId, draft.filename))
      .catch(() => {
        setUpload({
          kind: "error",
          filename: draft.filename,
          draftId: draft.draftId,
          jobId: draft.jobId,
          expiresAt: draft.expiresAt,
          message: "暂时无法恢复解析状态，请稍后重试或重新上传。",
        });
      });
  }, [draftIdFromQuery, handleResumeJobSnapshot]);

  // ---- Step 1: resume file upload --------------------------------------

  async function handleFile(file: File) {
    const requestId = ++uploadRequestRef.current;
    if (!isAcceptedResumeFile(file)) {
      setUpload({
        kind: "error",
        filename: file.name,
        message: "暂时只支持 PDF / DOCX / TXT / Markdown。可以换个格式再试。",
      });
      return;
    }
    if (file.size > MAX_UPLOAD_BYTES) {
      setUpload({
        kind: "error",
        filename: file.name,
        message: "文件过大（>5MB），请压缩或裁剪后再上传",
      });
      return;
    }
    const draftId = createSetupDraftId();
    setUpload({ kind: "parsing", filename: file.name, draftId });
    try {
      const job = await createResumeParseJobForSetup(file, {
        createResumeParseJob,
        buildLLMPayload,
      });
      if (requestId !== uploadRequestRef.current) return;
      const filename = job.filename ?? file.name;
      if (job.status === "running") {
        upsertSetupDraft({
          draftId,
          jobId: job.job_id,
          filename,
          status: "parsing",
          expiresAt: job.expires_at,
        });
        setUpload({
          kind: "parsing",
          filename,
          draftId,
          jobId: job.job_id,
          expiresAt: job.expires_at,
        });
      } else {
        handleResumeJobSnapshot(job, draftId, file.name);
      }
    } catch (err) {
      if (requestId !== uploadRequestRef.current) return;
      setUpload({
        kind: "error",
        filename: file.name,
        draftId,
        message: friendlyResumeUploadError(err),
      });
    }
  }

  function clearUpload() {
    const draftId = uploadDraftId(upload);
    if (draftId) {
      removeSetupDraft(draftId);
    }
    uploadRequestRef.current += 1;
    setUpload({ kind: "idle" });
    setResumeCandidateProfile({});
    setResumeParseAudit(null);
    setResumeSource(null);
    setCandidateNameFromResume(false);
    setJobTitleFromResume(false);
    setJobLevelFromResume(false);
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  function pickResumeFile() {
    if (fileInputRef.current) {
      fileInputRef.current.value = resumeReuploadInputValue();
      fileInputRef.current.click();
    }
  }

  // ---- Step 2: JD-driven dimension inference ----------------------------

  const applyJdResult = useCallback((res: ParseJobSpecResponse) => {
    setJdRequiredSkills(res.required_skills);
    if (res.rubric_dimension_labels.length > 0) {
      setSelectedDims(res.rubric_dimension_labels);
    }
  }, []);

  const scheduleJdParse = useCallback((text: string) => {
    if (jdDebounceRef.current) clearTimeout(jdDebounceRef.current);
    if (text.trim().length < 30) {
      // Too short to bother with the LLM. Reset to defaults.
      setJdStatus({ kind: "idle" });
      return;
    }
    setJdStatus({ kind: "parsing" });
    jdDebounceRef.current = setTimeout(async () => {
      try {
        const res = await parseJobSpec({
          text,
          direction: getValues("interview_direction"),
          title: getValues("job_title") || undefined,
          level: getValues("job_level"),
          llmConfig: buildLLMPayload(),
        });
        applyJdResult(res);
        setJdStatus({ kind: "success", rationale: res.rationale });
      } catch (err) {
        setJdStatus({
          kind: "error",
          message: friendlySetupError(err, "jd"),
        });
      }
    }, 700);
  }, [applyJdResult, getValues]);

  useEffect(() => {
    const subscription = watch((value, { name, type }) => {
      if (name === "job_description" && type === "change") {
        markJobDescriptionEdited();
        scheduleJdParse(value.job_description || "");
      }
    });
    return () => subscription.unsubscribe();
  }, [markJobDescriptionEdited, scheduleJdParse, watch]);

  useEffect(() => {
    void loadJobTemplate(DEFAULTS.interview_direction);
  }, [loadJobTemplate]);

  function toggleDim(option: DimensionOption) {
    setSelectedDims((prev) => {
      if (prev.some((d) => d.id === option.id)) {
        return prev.filter((d) => d.id !== option.id);
      }
      if (prev.length >= 5) return prev;
      return [...prev, option];
    });
  }

  function removeDim(id: string) {
    setSelectedDims((prev) => prev.filter((d) => d.id !== id));
  }

  function selectDirection(id: DirectionId) {
    const direction = resolveDirection(id);
    setValue("interview_industry", direction.industry ?? "internet", {
      shouldValidate: true,
    });
    setValue("interview_direction", id, { shouldValidate: true });
    setValue("job_title", direction.defaultTitle, { shouldValidate: true });
    setValue("job_level", direction.level, { shouldValidate: false });
    setJobTitleEdited(false);
    setJobLevelEdited(false);
    setJobTitleFromResume(false);
    setJobLevelFromResume(false);
    setSelectedDims(direction.dimensions.slice(0, 5));
    setJdRequiredSkills(direction.skills);
    void loadJobTemplate(id);
  }

  // ---- Submit -----------------------------------------------------------

  async function goNext() {
    const fields = STEP_FIELDS[step] ?? [];
    const ok = await trigger(fields);
    if (!ok) {
      const field = fields[0];
      const label = FIELD_LABEL[field] ?? "当前步骤信息";
      setServerError(`请先补全${label}`);
      if (field) setFocus(field);
      return;
    }
    setServerError(null);
    if (step < STEPS.length - 1) setStep(step + 1);
  }

  function goPrev() {
    if (step > 0) setStep(step - 1);
  }

  async function handleStepJump(targetStep: number) {
    if (targetStep <= step) {
      setStep(targetStep);
      return;
    }

    const fieldsToCheck = STEP_FIELDS.slice(0, targetStep).flat();
    const ok = await trigger(fieldsToCheck);
    if (ok) {
      setServerError(null);
      setStep(targetStep);
      return;
    }

    if (targetStep > 1 && !getValues("candidate_name").trim()) {
      setStep(1);
      setServerError("请先填写称呼");
      setFocus("candidate_name");
      return;
    }
    if (targetStep > 2 && !getValues("job_title").trim()) {
      setStep(2);
      setServerError("请先填写岗位名称");
      setFocus("job_title");
      return;
    }
    setServerError("请先补全前面步骤的必填信息");
  }

  const onSubmit = handleSubmit(
    async (values) => {
      setInterviewStartPending(true);
      setServerError(null);
      if (resumeFieldsLocked) {
        setInterviewStartPending(false);
        setServerError("AI 简历解析还在进行中，完成后会自动填入表单。");
        setStep(1);
        return;
      }
      if (selectedDims.length === 0) {
        setInterviewStartPending(false);
        setServerError("请至少保留一个考察维度");
        setStep(2);
        return;
      }
      if (startGate.disabled) {
        setInterviewStartPending(false);
        setServerError(startGate.notice ?? "当前额度状态还不能开始面试。");
        return;
      }

      const lengthChoice =
        LENGTH_OPTIONS.find((opt) => opt.id === values.length) ?? LENGTH_OPTIONS[1];
      const max_turns = values.max_turns_override ?? lengthChoice.turns;
      const turn_budget = values.turn_budget_override ?? max_turns + 2;

      // Required skills priority:
      //   1. JD-parsed list (what the role actually demands)
      //   2. Candidate skills as a reasonable proxy when no JD is filled
      const candidateSkills = splitCsv(values.candidate_skills ?? "");
      const selectedDirection = resolveDirection(values.interview_direction);
      const requiredSkills =
        jdRequiredSkills.length > 0
          ? jdRequiredSkills
          : candidateSkills.length > 0
            ? candidateSkills.slice(0, 8)
            : selectedDirection.skills;
      const projects = normaliseProjects(resumeProjects);
      const focusAreas = normaliseFocusAreas(resumeFocusAreas);
      const concerns = resumeConcerns.map((c) => c.trim()).filter(Boolean);
      const resumeSetupSnapshot: ResumeSetupSnapshot = {
        candidate_name: values.candidate_name,
        candidate_summary: values.candidate_summary,
        candidate_skills: values.candidate_skills,
        candidate_highlights: values.candidate_highlights,
        resumeProjects: projects as unknown as Record<string, unknown>[],
        resumeFocusAreas: focusAreas as unknown as Record<string, unknown>[],
        resumeConcerns: concerns,
        resumeCandidateProfile: resumeCandidateProfile as Record<string, unknown>,
        ...(resumeParseAudit
          ? { resumeParseAudit: resumeParseAudit as unknown as Record<string, unknown> }
          : {}),
      };
      const resumeSourceId = resumeSourceIdForSession(resumeSource);

      const payload: StartSessionRequest = {
        candidate: {
          name: values.candidate_name,
          resume_parsed: resumeParsedForSession({
            summary: values.candidate_summary || undefined,
            skills: candidateSkills,
            highlights: splitCsv(values.candidate_highlights ?? ""),
            projects,
            focus_areas: focusAreas,
            concerns,
            candidate_profile: resumeCandidateProfile,
          }),
          ...(resumeParseAudit ? { resume_parse_audit: resumeParseAudit } : {}),
        },
        job_spec: {
          title: values.job_title,
          level: values.job_level,
          required_skills: requiredSkills,
          rubric_dimensions: selectedDims.map((d) => d.id),
          interview_industry: values.interview_industry,
          interview_direction: values.interview_direction,
          interview_direction_label: selectedDirection.label,
        },
        max_turns,
        interview_depth: lengthChoice.id,
        quality_threshold: values.quality_threshold,
        turn_budget,
        focus_dimensions: practiceFocusDims.map((d) => d.id),
        mode: "mixed",
        enable_video_analysis: enableVideoAnalysis,
        llm_config: currentLlmPayload,
        ...(resumeSourceId ? { resume_source_id: resumeSourceId } : {}),
      };

      try {
        setStartCreditNotice(null);
        const res = await startSession(payload);
        const creditUpdate = { creditBalance: res.credit_balance };
        if (typeof creditUpdate.creditBalance === "number") {
          setCreditBalance(creditUpdate.creditBalance);
        }
        if (
          res.billing_mode === "platform_credits" &&
          res.credit_delta === -1 &&
          typeof res.credit_balance === "number"
        ) {
          setStartCreditNotice(`已扣 1 次，剩余 ${res.credit_balance} 次。`);
        }
        try {
          upsertEntry({
            sessionId: res.session_id,
            sessionToken: res.session_token,
            sessionTokenExpiresAt: res.session_token_expires_at,
            recoveryToken: res.recovery_token,
            recoveryTokenExpiresAt: res.recovery_token_expires_at,
            ownerUserId: res.owner_user_id ?? undefined,
            ownerClaimedAt: res.owner_user_id ? res.created_at : undefined,
            createdAt: res.created_at,
            updatedAt: res.updated_at,
            jdTitle: values.job_title,
            candidateName: values.candidate_name,
            jobLevel: values.job_level,
            rubricDimensions: selectedDims.map((d) => d.id),
            maxTurns: res.max_turns ?? max_turns,
            status: "running",
            resumeSetupSnapshot,
          });
        } catch {
          /* ignore */
        }
        const draftId = uploadDraftId(upload);
        if (draftId) {
          removeSetupDraft(draftId);
        }
        safeSessionRemoveItem(RESUME_DRAFT_KEY);
        router.push(`/interview/${res.session_id}`);
      } catch (err) {
        setInterviewStartPending(false);
        setServerError(friendlySetupError(err, "start"));
      }
    },
    (formErrors) => {
      setInterviewStartPending(false);
      const first = firstFormError(formErrors);
      setServerError(first?.message ?? "请先补全必填信息");
      if (first) {
        if (ADVANCED_FIELD_NAMES.includes(first.field)) {
          setAdvancedOpen(true);
        }
        setStep(first.step);
        window.setTimeout(() => setFocus(first.field), 0);
      }
    },
  );

  // ---- Render -----------------------------------------------------------

  return (
    <div className="relative">
      <form
        onSubmit={onSubmit}
        aria-busy={isStartingInterview}
        className={`space-y-6 ${
          isStartingInterview ? "pointer-events-none select-none" : ""
        }`}
      >
      <ExpectationBanner />
      {llmStatus === "missing" && <ApiKeyHintBanner />}
      {isProblemLLMStatus(llmStatus) && <ApiKeyProblemBanner status={llmStatus} />}
      {platformCreditNotice && (
        <div className="flex flex-col gap-2 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-sm sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-start gap-3">
            <Sparkles className="mt-0.5 h-4 w-4 flex-shrink-0 text-emerald-500" />
            <div>
              <p className="font-medium text-emerald-700 dark:text-emerald-300">
                {shouldUsePlatformCredits ? "平台托管免费次数" : "个人 API Key / BYOK"}
              </p>
              <p className="text-xs leading-relaxed text-muted-foreground">
                {shouldUsePlatformCredits &&
                auth.authenticated &&
                creditBalance !== null &&
                creditBalance > 0
                  ? <>剩余 {creditBalance} 次。本次将消耗 1 次平台面试次数。</>
                  : platformCreditNotice}
              </p>
            </div>
          </div>
          {shouldUsePlatformCredits && !auth.authenticated ? (
            <AuthDialog>
              <Button
                type="button"
                size="sm"
                variant="outline"
                className="shrink-0 gap-2"
              >
                登录领取免费次数
              </Button>
            </AuthDialog>
          ) : startGate.ctaLabel ? (
            <span className="shrink-0 rounded-full bg-background px-3 py-1 text-xs font-medium text-emerald-700 dark:text-emerald-300">
              {startGate.ctaLabel}
            </span>
          ) : null}
        </div>
      )}

      <StepIndicator current={step} onJump={(id) => void handleStepJump(id)} />

      <AnimatePresence mode="wait">
        {step === 0 && (
          <DirectionStep
            selected={watch("interview_direction")}
            directions={directionOptions}
            onSelect={selectDirection}
          />
        )}

        {step === 1 && (
          <motion.div
            key="step-1"
            initial={{ opacity: 0, x: -20 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: 20 }}
            transition={{ duration: 0.25 }}
          >
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <User className="h-5 w-5 text-emerald-400" />
                  介绍一下你自己
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-5">
                <div className="space-y-1.5">
                  <div className="flex items-center gap-2">
                    <Label className="text-sm">称呼 *</Label>
                    {candidateNameFromResume && (
                      <span className="text-xs text-emerald-400">
                        已从简历识别
                      </span>
                    )}
                  </div>
                  <Input
                    {...register("candidate_name", {
                      onChange: () => setCandidateNameFromResume(false),
                    })}
                    placeholder="请输入你的姓名或昵称"
                    aria-invalid={Boolean(errors.candidate_name)}
                    aria-describedby={
                      errors.candidate_name ? fieldErrorId("candidate_name") : undefined
                    }
                    disabled={resumeFieldsLocked}
                  />
                  {errors.candidate_name && (
                    <p id={fieldErrorId("candidate_name")} className="text-xs text-destructive">
                      {errors.candidate_name.message}
                    </p>
                  )}
                </div>

                <ResumeUploader
                  status={upload}
                  isDragging={isDragging}
                  onPick={pickResumeFile}
                  onDragEnter={(e) => {
                    e.preventDefault();
                    setIsDragging(true);
                  }}
                  onDragOver={(e) => {
                    e.preventDefault();
                    setIsDragging(true);
                  }}
                  onDragLeave={(e) => {
                    e.preventDefault();
                    setIsDragging(false);
                  }}
                  onDrop={async (e) => {
                    e.preventDefault();
                    setIsDragging(false);
                    const file = e.dataTransfer.files?.[0];
                    if (file) await handleFile(file);
                  }}
                  onClear={clearUpload}
                />
                <input
                  ref={fileInputRef}
                  type="file"
                  accept={ACCEPTED_TYPES}
                  className="hidden"
                  onChange={async (e) => {
                    const file = e.target.files?.[0];
                    if (file) await handleFile(file);
                  }}
                />

                <ResumePreviewCard
                  candidateProfile={resumeCandidateProfile}
                  summary={watch("candidate_summary") ?? ""}
                  skills={watch("candidate_skills") ?? ""}
                  highlights={watch("candidate_highlights") ?? ""}
                  projects={resumeProjects}
                  focusAreas={resumeFocusAreas}
                  concerns={resumeConcerns}
                  showHint={upload.kind === "success"}
                  readOnly={resumeFieldsLocked}
                  onChangeSummary={(v) =>
                    setValue("candidate_summary", v, { shouldValidate: true })
                  }
                  onChangeSkills={(v) =>
                    setValue("candidate_skills", v, { shouldValidate: true })
                  }
                  onChangeHighlights={(v) =>
                    setValue("candidate_highlights", v, { shouldValidate: true })
                  }
                  onChangeProjects={setResumeProjects}
                  onChangeFocusAreas={setResumeFocusAreas}
                />
              </CardContent>
            </Card>
          </motion.div>
        )}

        {step === 2 && (
          <motion.div
            key="step-2"
            initial={{ opacity: 0, x: -20 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: 20 }}
            transition={{ duration: 0.25 }}
            className="space-y-6"
          >
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Briefcase className="h-5 w-5 text-emerald-400" />
                  面试什么岗位
                </CardTitle>
              </CardHeader>
              <CardContent className="grid gap-4 md:grid-cols-2">
                <div className="space-y-1.5">
                  <div className="flex items-center gap-2">
                    <Label className="text-sm">岗位名称 *</Label>
                    {jobTitleFromResume && (
                      <span className="text-xs text-emerald-400">
                        已根据简历建议
                      </span>
                    )}
                  </div>
                  <Input
                    {...register("job_title", {
                      onChange: () => {
                        setJobTitleEdited(true);
                        setJobTitleFromResume(false);
                      },
                    })}
                    placeholder="例如：高级前端工程师"
                    aria-invalid={Boolean(errors.job_title)}
                    aria-describedby={
                      errors.job_title ? fieldErrorId("job_title") : undefined
                    }
                    disabled={resumeFieldsLocked}
                  />
                  {errors.job_title && (
                    <p id={fieldErrorId("job_title")} className="text-xs text-destructive">
                      {errors.job_title.message}
                    </p>
                  )}
                </div>
                <div className="space-y-1.5">
                  <div className="flex items-center gap-2">
                    <Label className="text-sm">目标级别 *</Label>
                    {jobLevelFromResume && (
                      <span className="text-xs text-emerald-400">
                        已根据履历阶段建议
                      </span>
                    )}
                  </div>
                  <select
                    {...register("job_level", {
                      onChange: () => {
                        setJobLevelEdited(true);
                        setJobLevelFromResume(false);
                      },
                    })}
                    disabled={resumeFieldsLocked}
                    className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm text-foreground shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                  >
                    <option value="junior" className="bg-background text-foreground">
                      初级
                    </option>
                    <option value="mid" className="bg-background text-foreground">
                      中级
                    </option>
                    <option value="senior" className="bg-background text-foreground">
                      高级
                    </option>
                    <option value="staff" className="bg-background text-foreground">
                      Staff / 技术专家
                    </option>
                    <option
                      value="principal"
                      className="bg-background text-foreground"
                    >
                      Principal / 资深专家
                    </option>
                  </select>
                  {jobLevelFromResume &&
                    resumeCandidateProfile.suggested_job_level_basis &&
                    resumeCandidateProfile.suggested_job_level_basis.length > 0 && (
                      <p className="text-xs text-muted-foreground">
                        级别建议依据：
                        {resumeCandidateProfile.suggested_job_level_basis.join("、")}
                      </p>
                    )}
                </div>

                <div className="md:col-span-2 space-y-1.5">
                  <div className="flex items-center justify-between">
                    <Label className="text-sm">岗位要求</Label>
                    <JdHint
                      status={jdStatus}
                      onRetry={() => scheduleJdParse(watch("job_description") || "")}
                    />
                  </div>
                  <p className="text-xs text-muted-foreground">
                    系统已根据目标岗位生成通用要求，可直接调整；如果你有真实 JD，也可以粘贴覆盖。
                  </p>
                  <Textarea
                    rows={5}
                    maxLength={50000}
                    {...register("job_description")}
                    placeholder="粘贴真实岗位 JD，或基于当前通用要求微调。系统会据此调整考察重点和技能范围，不用于判断目标级别。"
                    className="resize-none"
                  />
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-base">
                  <Wand2 className="h-4 w-4 text-emerald-400" />
                  AI 会重点考察
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <ResumeFocusSummary
                  focusAreas={resumeFocusAreas}
                  direction={resolveDirection(watch("interview_direction"))}
                />
                <DimensionPicker
                  selected={selectedDims}
                  catalog={
                    resolveDirection(watch("interview_direction")).dimensions.length > 0
                      ? resolveDirection(watch("interview_direction")).dimensions
                      : allDimensions.length > 0
                        ? allDimensions
                        : DEFAULT_DIMENSIONS
                  }
                  onToggle={toggleDim}
                  onRemove={removeDim}
                />
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-base">
                  <Clock className="h-4 w-4 text-emerald-400" />
                  面试深度
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <p className="text-sm text-muted-foreground">
                  控制最多提问轮数和追问空间，实际时长会根据回答长度和模型响应速度变化。
                </p>
                <LengthPicker
                  value={watch("length")}
                  onChange={(v) => setValue("length", v)}
                />
              </CardContent>
            </Card>

            <AdvancedPanel
              open={advancedOpen}
              onToggle={() => setAdvancedOpen((v) => !v)}
              register={register}
              errors={errors}
              enableVideoAnalysis={enableVideoAnalysis}
              onToggleVideo={() => setEnableVideoAnalysis((v) => !v)}
            />
          </motion.div>
        )}
      </AnimatePresence>

      {serverError && (
        <motion.div
          initial={{ opacity: 0, y: -8 }}
          animate={{ opacity: 1, y: 0 }}
          role="alert"
          aria-live="assertive"
          className="flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/10 p-4 text-sm text-destructive"
        >
          <AlertCircle className="mt-0.5 h-4 w-4 flex-shrink-0" />
          <span>{serverError}</span>
        </motion.div>
      )}

      {startCreditNotice && (
        <motion.div
          initial={{ opacity: 0, y: -8 }}
          animate={{ opacity: 1, y: 0 }}
          role="status"
          aria-live="polite"
          className="flex items-start gap-2 rounded-md border border-emerald-500/30 bg-emerald-500/10 p-4 text-sm text-emerald-700 dark:text-emerald-300"
        >
          <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0" />
          <span>{startCreditNotice}</span>
        </motion.div>
      )}


      <div className="flex items-center justify-between">
        <Button
          type="button"
          variant="ghost"
          onClick={goPrev}
          disabled={step === 0 || isStartingInterview}
          className="gap-1"
        >
          上一步
        </Button>
        <div className="flex items-center gap-2">
          {step < STEPS.length - 1 ? (
            <Button
              type="button"
              onClick={goNext}
              disabled={isStartingInterview}
              className="gap-1 bg-emerald-600 hover:bg-emerald-500 text-white"
            >
              下一步
              <ArrowRight className="h-4 w-4" />
            </Button>
          ) : (
            <Button
              type="submit"
              size="lg"
              disabled={isStartingInterview || resumeFieldsLocked || startGate.disabled}
              className="gap-2 bg-emerald-600 hover:bg-emerald-500 text-white"
            >
              {isStartingInterview && <Loader2 className="h-4 w-4 animate-spin" />}
              {isStartingInterview ? "正在创建面试环境" : "开始我的面试"}
              {!isStartingInterview && <ArrowRight className="h-4 w-4" />}
            </Button>
          )}
        </div>
      </div>
      </form>

      <AnimatePresence>
        {isStartingInterview && (
          <motion.div
            key="start-interview-pending"
            role="status"
            aria-live="polite"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-center justify-center bg-background/60 px-4 backdrop-blur-sm"
          >
            <motion.div
              initial={{ opacity: 0, y: 8, scale: 0.98 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: 4, scale: 0.99 }}
              className="flex min-h-40 w-full max-w-sm items-center rounded-lg border border-emerald-500/30 bg-card p-5 shadow-2xl"
            >
              <div className="flex items-center gap-4">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-emerald-500/10">
                  <Loader2 className="h-5 w-5 animate-spin text-emerald-400" />
                </div>
                <div>
                  <p className="font-medium text-foreground">正在创建面试环境</p>
                  <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
                    正在保存配置并打开面试页面，准备好后会自动进入。
                  </p>
                </div>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function DirectionStep({
  selected,
  directions,
  onSelect,
}: {
  selected: DirectionId;
  directions: ReadonlyArray<SetupDirection>;
  onSelect: (id: DirectionId) => void;
}) {
  const groups = groupedDirections(directions);
  const selectedDirection = directionByIdFrom(directions, selected);
  const selectedCategory = categoryForDirection(selectedDirection);
  const [activeCategory, setActiveCategory] =
    useState<DirectionCategoryId>(selectedCategory);
  const activeGroup =
    groups.find((group) => group.id === activeCategory) ?? groups[0];

  useEffect(() => {
    setActiveCategory(selectedCategory);
  }, [selectedCategory]);

  return (
    <motion.div
      key="step-0"
      initial={{ opacity: 0, x: -20 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: 20 }}
      transition={{ duration: 0.25 }}
      className="space-y-6"
    >
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Briefcase className="h-5 w-5 text-emerald-400" />
            先选目标岗位
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="rounded-md border border-emerald-500/20 bg-emerald-500/5 px-4 py-3 text-sm leading-relaxed text-muted-foreground">
            选一个最接近你目标岗位的方向，我们会先准备一份通用岗位要求，后面你还可以自己修改。
          </div>

          <div className="space-y-4">
            <div className="space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="secondary">岗位大类</Badge>
                <span className="text-xs text-muted-foreground">
                  先按工作类型缩小范围
                </span>
              </div>
              <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
                {groups.map((group) => {
                  const active = activeGroup?.id === group.id;
                  const selectedInGroup = group.directions.some(
                    (direction) => direction.id === selected,
                  );
                  return (
                    <button
                      key={group.id}
                      type="button"
                      onClick={() => setActiveCategory(group.id)}
                      className={[
                        "rounded-md border px-3 py-2.5 text-left transition-colors",
                        active
                          ? "border-emerald-400 bg-emerald-400/10"
                          : "border-border bg-secondary/10 hover:border-emerald-400/50 hover:bg-secondary/25",
                      ].join(" ")}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-sm font-medium">{group.label}</span>
                        {selectedInGroup && (
                          <CheckCircle2 className="h-3.5 w-3.5 text-emerald-300" />
                        )}
                      </div>
                      <p className="mt-1 line-clamp-2 text-xs leading-relaxed text-muted-foreground">
                        {group.desc}
                      </p>
                    </button>
                  );
                })}
              </div>
            </div>

            <div className="space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="outline">目标岗位</Badge>
                <span className="text-xs text-muted-foreground">
                  {activeGroup?.label ?? "选择最接近的一项"}
                </span>
              </div>
              <div className="grid gap-3 md:grid-cols-2">
                {(activeGroup?.directions ?? directions).map((item) => {
                  const active = selected === item.id;
                  return (
                    <button
                      key={item.id}
                      type="button"
                      onClick={() => onSelect(item.id)}
                      className={[
                        "rounded-md border p-3 text-left transition-colors",
                        active
                          ? "border-emerald-400 bg-emerald-400/10"
                          : "border-border bg-secondary/10 hover:border-emerald-400/50 hover:bg-secondary/25",
                      ].join(" ")}
                    >
                      <div className="flex items-center justify-between gap-3">
                        <span className="text-base font-medium">{item.label}</span>
                        {active && (
                          <CheckCircle2 className="h-4 w-4 text-emerald-300" />
                        )}
                      </div>
                      <p className="mt-1 line-clamp-2 text-xs leading-relaxed text-muted-foreground">
                        {item.desc}
                      </p>
                    </button>
                  );
                })}
              </div>
            </div>
          </div>
        </CardContent>
      </Card>
    </motion.div>
  );
}

function ExpectationBanner() {
  return (
    <div className="flex items-start gap-3 rounded-lg border border-emerald-500/20 bg-emerald-500/5 px-4 py-3 text-sm">
      <Info className="mt-0.5 h-4 w-4 flex-shrink-0 text-emerald-400" />
      <div className="space-y-0.5">
        <p>
          面试通常包含 <span className="font-medium">5-12 轮问题</span>，
          AI 会根据你的回答动态调整难度和追问方向。
        </p>
        <p className="text-xs text-muted-foreground">
          进度自动保存，你可以随时关闭页面继续。
        </p>
      </div>
    </div>
  );
}

function ApiKeyHintBanner() {
  return (
    <div className="flex flex-col gap-3 rounded-lg border border-amber-400/30 bg-amber-400/10 px-4 py-3 text-sm sm:flex-row sm:items-center sm:justify-between">
      <div className="flex items-start gap-3">
        <Key className="mt-0.5 h-4 w-4 flex-shrink-0 text-amber-300" />
        <div>
          <p className="font-medium text-amber-100">还没有配置 API Key</p>
          <p className="text-xs leading-relaxed text-muted-foreground">
            可以先填表，开始面试前建议配置自己的模型密钥；未配置时会使用系统默认的练习模式。
          </p>
        </div>
      </div>
      <LLMSettingsDialog>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="shrink-0 gap-2"
        >
          <Key className="h-4 w-4" />
          去配置
        </Button>
      </LLMSettingsDialog>
    </div>
  );
}

function friendlyResumeUploadError(err: unknown): string {
  const raw = err instanceof Error ? err.message : String(err);
  const lower = raw.toLowerCase();
  if (
    lower.includes("timeout") ||
    lower.includes("aborterror") ||
    lower.includes("timed out")
  ) {
    return "简历解析等太久了。可以再试一次；如果还是超时，也可以直接手动填写，后续面试仍可继续。";
  }
  if (lower.includes("scanned") || lower.includes("extract any text")) {
    return "这份文件没有提取到文字。如果是扫描版 PDF，建议上传 DOCX/Markdown，或把简历文本粘贴进来。";
  }
  if (lower.includes("too large") || lower.includes("文件过大")) {
    return "文件超过 5MB，请压缩、裁剪，或换成文本版简历后再上传。";
  }
  if (lower.includes("unsupported")) {
    return "暂时只支持 PDF / DOCX / TXT / Markdown。可以换个格式再试。";
  }
  return friendlySetupError(err, "resume");
}

function friendlySetupError(
  err: unknown,
  context: "resume" | "jd" | "start" | "general" = "general",
): string {
  const raw = err instanceof Error ? err.message : String(err);
  if (err instanceof ApiError) {
    if (
      err.code === "login_required_for_platform_credits" ||
      (err.status === 401 && raw.includes("login_required_for_platform_credits"))
    ) {
      return "请先登录领取免费次数，再开始平台托管面试；也可以使用个人 API Key。";
    }
    if (
      err.code === "platform_credits_exhausted" ||
      (err.status === 402 && raw.includes("platform_credits_exhausted"))
    ) {
      return "次数不足：可以使用个人 API Key，或联系管理员补充次数。";
    }
    if (err.status === 413) {
      return "文件超过大小限制，请压缩、裁剪，或换成文本版后再试。";
    }
    if (err.status === 415) {
      return "文件格式暂不支持，请上传 PDF / DOCX / TXT / Markdown。";
    }
    if (err.status === 409) {
      return "这场面试的会话标识已存在，请重新开始一次。";
    }
    if (err.status === 422) {
      if (raw.includes("llm_config")) {
        return "模型配置格式不正确，请检查 API Key、模型和 Base URL 后再试。";
      }
      return context === "jd"
        ? "岗位要求暂时无法自动分析，仍可继续使用默认考察维度。"
        : "有字段内容超出范围或格式不正确，请检查高亮提示后再试。";
    }
    if (err.status >= 500) {
      return "服务端暂时无法处理请求，请稍后重试；已填写内容不会丢失。";
    }
  }
  if (context === "resume") {
    return raw || "简历解析失败了。你可以重试，或直接手动填写。";
  }
  if (context === "jd") {
    return raw || "JD 分析失败，仍可继续使用默认考察维度。";
  }
  if (context === "start") {
    return raw || "暂时无法开始面试，请稍后重试。";
  }
  return raw || "操作失败，请稍后重试。";
}

function isProblemLLMStatus(status: LLMConfigStatus): boolean {
  return (
    status === "auth_failed" ||
    status === "quota_exhausted" ||
    status === "rate_limited" ||
    status === "transient" ||
    status === "misconfig" ||
    status === "error"
  );
}

function ApiKeyProblemBanner({ status }: { status: LLMConfigStatus }) {
  return (
    <div className="flex flex-col gap-3 rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm sm:flex-row sm:items-center sm:justify-between">
      <div className="flex items-start gap-3">
        <AlertCircle className="mt-0.5 h-4 w-4 flex-shrink-0 text-destructive" />
        <div>
          <p className="font-medium text-destructive">个人 API 配置需要检查</p>
          <p className="text-xs leading-relaxed text-muted-foreground">
            {apiKeyProblemMessage(status)}
          </p>
        </div>
      </div>
      <LLMSettingsDialog>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="shrink-0 gap-2"
        >
          <Key className="h-4 w-4" />
          检查设置
        </Button>
      </LLMSettingsDialog>
    </div>
  );
}

function apiKeyProblemMessage(status: LLMConfigStatus): string {
  switch (status) {
    case "auth_failed":
      return "保存的密钥可能已过期、被撤销，或没有当前模型权限。更新后再开始会更稳。";
    case "quota_exhausted":
      return "保存的配置额度不足或余额耗尽。可以换一个 Key，或检查厂商控制台余额。";
    case "rate_limited":
      return "保存的配置刚才被限流了。稍后再试，或换一个额度更充足的 Key。";
    case "transient":
      return "模型服务或网络刚才不稳定。配置不一定错，建议测试通过后再开始。";
    case "misconfig":
      return "模型名称、服务商或 Base URL 可能不匹配。检查后再测试一次。";
    default:
      return "上次连接测试没有通过。你仍可以填写表单，但开始前建议先检查 API 设置。";
  }
}

function StepIndicator({
  current,
  onJump,
}: {
  current: number;
  onJump: (id: number) => void;
}) {
  return (
    <div className="flex items-center justify-center gap-2">
      {STEPS.map((s, i) => (
        <div key={s.id} className="flex items-center">
          <button
            type="button"
            onClick={() => onJump(s.id)}
            className={`flex items-center gap-2 rounded-full px-4 py-2 text-sm transition-all ${
              current === s.id
                ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/30"
                : current > s.id
                  ? "text-emerald-400/60"
                  : "text-muted-foreground hover:text-foreground"
            }`}
          >
            {current > s.id ? (
              <CheckCircle2 className="h-4 w-4" />
            ) : (
              s.icon
            )}
            <span className="hidden sm:inline">{s.label}</span>
            <span className="sm:hidden">{i + 1}</span>
          </button>
          {i < STEPS.length - 1 && (
            <div
              className={`mx-2 h-px w-8 transition-colors ${
                current > i ? "bg-emerald-400/40" : "bg-border"
              }`}
            />
          )}
        </div>
      ))}
    </div>
  );
}

function ResumeUploader({
  status,
  isDragging,
  onPick,
  onDragEnter,
  onDragOver,
  onDragLeave,
  onDrop,
  onClear,
}: {
  status: UploadStatus;
  isDragging: boolean;
  onPick: () => void;
  onDragEnter: (e: React.DragEvent) => void;
  onDragOver: (e: React.DragEvent) => void;
  onDragLeave: (e: React.DragEvent) => void;
  onDrop: (e: React.DragEvent) => void;
  onClear: () => void;
}) {
  const isParsing = status.kind === "parsing";
  const isError = status.kind === "error";
  const isSuccess = status.kind === "success";
  const parseStatus = isSuccess ? status.parseStatus : undefined;
  const successIsBasic = parseStatus?.mode === "basic";

  if (isParsing) {
    return (
      <div className="space-y-2">
        <div className="flex items-center justify-between gap-3">
          <Label className="text-sm">从简历自动填写（推荐）</Label>
          <Button type="button" variant="ghost" size="sm" onClick={onClear}>
            取消解析
          </Button>
        </div>
        <div className="rounded-md border border-emerald-500/25 bg-emerald-500/[0.04] px-3 py-3">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex min-w-0 items-start gap-3">
              <div className="mt-0.5 rounded-full bg-emerald-500/10 p-2">
                <Loader2 className="h-4 w-4 animate-spin text-emerald-300" />
              </div>
              <div className="min-w-0 space-y-1">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge
                    variant="outline"
                    className="border-emerald-500/40 bg-emerald-500/10 text-emerald-200"
                  >
                    AI 解析中
                  </Badge>
                  <span className="truncate text-sm font-medium">
                    {status.filename}
                  </span>
                </div>
                <p className="text-xs text-muted-foreground">
                  解析可能需要几分钟。你可以离开当前页面，之后从首页“接着练”或“我的面试”继续回来。
                </p>
              </div>
            </div>
            <div className="grid shrink-0 grid-cols-3 gap-1 text-[11px] text-muted-foreground sm:w-[260px]">
              {["读取文件", "AI 精修", "自动补全"].map((label, idx) => (
                <div
                  key={label}
                  className="rounded border border-emerald-500/15 bg-background/30 px-2 py-1 text-center"
                >
                  <span className={idx === 1 ? "text-emerald-200" : ""}>
                    {label}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    );
  }

  if (isSuccess) {
    return (
      <div className="space-y-2">
        <Label className="text-sm">从简历自动填写（推荐）</Label>
        <div className="flex flex-col gap-3 rounded-md border border-emerald-500/20 bg-emerald-500/5 px-3 py-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex min-w-0 items-center gap-3">
            <Badge
              variant="outline"
              className={
                successIsBasic
                  ? "shrink-0 border-amber-500/40 bg-amber-500/10 text-amber-200"
                  : "shrink-0 border-emerald-500/40 bg-emerald-500/10 text-emerald-200"
              }
            >
              {successIsBasic ? "基础解析" : "AI 已解析"}
            </Badge>
            <FileText className="h-4 w-4 shrink-0 text-muted-foreground" />
            <div className="min-w-0">
              <div className="truncate text-sm font-medium">{status.filename}</div>
              <div className="truncate text-xs text-muted-foreground">
                {resumeParseStatusMessage(parseStatus)}
              </div>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <Button type="button" variant="outline" size="sm" onClick={onPick}>
              重新上传
            </Button>
            <Button type="button" variant="ghost" size="sm" onClick={onClear}>
              清除解析结果
            </Button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <Label className="text-sm">从简历自动填写（推荐）</Label>
        {(isSuccess || isError) && (
          <button
            type="button"
            onClick={onClear}
            className="flex items-center gap-1 text-xs text-muted-foreground transition-colors hover:text-foreground"
          >
            <X className="h-3 w-3" />
          清除解析结果
          </button>
        )}
      </div>

      <button
        type="button"
        onClick={onPick}
        onDragEnter={onDragEnter}
        onDragOver={onDragOver}
        onDragLeave={onDragLeave}
        onDrop={onDrop}
        className={`flex w-full flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed px-6 py-8 text-center transition-all ${
          isDragging
            ? "border-emerald-400 bg-emerald-500/10"
            : isError
              ? "border-destructive/40 bg-destructive/5"
              : "border-border hover:border-emerald-500/40 hover:bg-emerald-500/5"
        } cursor-pointer`}
      >
        {status.kind === "idle" && (
          <>
            <Upload className="h-6 w-6 text-muted-foreground" />
            <p className="text-sm font-medium">
              拖拽简历到这里，或点击选择文件
            </p>
            <p className="text-xs text-muted-foreground">
              支持 PDF / DOCX / TXT / Markdown，最大 5 MB
            </p>
          </>
        )}

        {isError && (
          <>
            <X className="h-6 w-6 text-destructive" />
            <p className="text-sm font-medium">{status.filename} 解析失败</p>
            <p className="max-w-md text-xs text-destructive">
              {status.message}
            </p>
            <p className="text-xs text-muted-foreground">
              你可以重试，或直接手动填写
            </p>
          </>
        )}
      </button>
    </div>
  );
}

function resumeParseStatusMessage(status?: ParseResumeStatus): string {
  if (!status) return "已更新简历内容确认区";
  if (status.cached) {
    return "已使用上次解析结果，可继续检查和微调";
  }
  if (status.mode === "ai_refined") {
    return "已生成概要、技能、项目和面试重点";
  }
  if (status.reason === "timeout") {
    return "已先完成基础整理，可继续检查和微调";
  }
  if (status.reason === "llm_failed") {
    return "已先完成基础整理，智能补全暂时未完成";
  }
  if (status.reason === "stub_mode") {
    return "已生成可编辑的基础简历信息";
  }
  return "已生成可编辑的基础简历信息";
}

function resumeCandidateProfileChips(profile: ResumeCandidateProfile) {
  const chips: Array<{ label: string; value: string }> = [];
  if (profile.education_level) {
    chips.push({ label: "学历", value: profile.education_level });
  }
  if (profile.school) {
    chips.push({ label: "学校", value: profile.school });
  }
  if (profile.major) {
    chips.push({ label: "专业", value: profile.major });
  }
  if (typeof profile.experience_years === "number") {
    chips.push({ label: "经验", value: `${profile.experience_years} 年` });
  }
  if (profile.current_or_target_role) {
    chips.push({ label: "方向", value: profile.current_or_target_role });
  }
  if (profile.fresh_graduate) {
    chips.push({ label: "阶段", value: "应届/在读" });
  }
  if (profile.graduation_year) {
    chips.push({ label: "毕业", value: `${profile.graduation_year} 届` });
  }
  if (profile.age) {
    chips.push({ label: "年龄", value: `${profile.age} 岁` });
  }
  return chips;
}

function ResumePreviewCard({
  candidateProfile,
  summary,
  skills,
  highlights,
  projects,
  focusAreas,
  concerns,
  showHint,
  readOnly,
  onChangeSummary,
  onChangeSkills,
  onChangeHighlights,
  onChangeProjects,
  onChangeFocusAreas,
}: {
  candidateProfile: ResumeCandidateProfile;
  summary: string;
  skills: string;
  highlights: string;
  projects: ResumeProject[];
  focusAreas: ResumeFocusArea[];
  concerns: string[];
  showHint: boolean;
  readOnly?: boolean;
  onChangeSummary: (v: string) => void;
  onChangeSkills: (v: string) => void;
  onChangeHighlights: (v: string) => void;
  onChangeProjects: (v: ResumeProject[]) => void;
  onChangeFocusAreas: (v: ResumeFocusArea[]) => void;
}) {
  const [tab, setTab] = useState<
    "summary" | "skills" | "highlights" | "projects" | "focus"
  >(
    "summary",
  );
  const skillCount = splitCsv(skills).length;
  const highlightCount = splitCsv(highlights).filter(Boolean).length;
  const isEmpty =
    !summary &&
    skillCount === 0 &&
    highlightCount === 0 &&
    projects.length === 0 &&
    focusAreas.length === 0;
  const profileChips = resumeCandidateProfileChips(candidateProfile);

  function updateProject(idx: number, patch: Partial<ResumeProject>) {
    onChangeProjects(
      projects.map((project, i) =>
        i === idx ? { ...project, ...patch } : project,
      ),
    );
  }

  function addProject() {
    onChangeProjects([
      ...projects,
      {
        id: `proj-${projects.length + 1}`,
        name: "",
        role: "",
        tech_stack: [],
        responsibilities: [],
        achievements: [],
        question_anchors: [],
      },
    ]);
  }

  function updateFocus(idx: number, patch: Partial<ResumeFocusArea>) {
    onChangeFocusAreas(
      focusAreas.map((focus, i) => (i === idx ? { ...focus, ...patch } : focus)),
    );
  }

  function addFocusArea() {
    onChangeFocusAreas([
      ...focusAreas,
      {
        id: `focus-${focusAreas.length + 1}`,
        label: "",
        project_id: null,
        dimensions: ["project_experience", "technical_depth"],
        skills: [],
        priority: focusAreas.length + 1,
      },
    ]);
  }

  return (
    <div className="rounded-lg border bg-secondary/30">
      <div className="flex flex-col gap-2 border-b px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-2">
          <Sparkles className="h-3.5 w-3.5 text-emerald-400" />
          <span className="text-sm font-medium">
            {isEmpty ? "手动填写或上传简历" : "简历内容确认"}
          </span>
        </div>
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          {!isEmpty && (
            <span>
              {projects.length} 个项目 · {focusAreas.length} 个重点
            </span>
          )}
          {showHint && <span className="text-emerald-400">已自动回填</span>}
        </div>
      </div>

      {profileChips.length > 0 && (
        <div className="flex flex-wrap gap-1.5 border-b px-4 py-3">
          {profileChips.map((chip) => (
            <Badge
              key={chip.label}
              variant="outline"
              className="border-border bg-background/50 text-[11px] font-normal text-muted-foreground"
            >
              <span className="mr-1 text-foreground/80">{chip.label}</span>
              {chip.value}
            </Badge>
          ))}
        </div>
      )}

      <div className="flex gap-1 border-b p-1 text-sm">
        {[
          { id: "summary" as const, label: "概要" },
          { id: "skills" as const, label: `技能 (${skillCount})` },
          { id: "highlights" as const, label: `亮点 (${highlightCount})` },
          { id: "projects" as const, label: `项目 (${projects.length})` },
          { id: "focus" as const, label: `重点 (${focusAreas.length})` },
        ].map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setTab(t.id)}
            className={`min-w-0 flex-1 rounded-md px-3 py-2 transition-colors ${
              tab === t.id
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="px-4 py-3">
        {tab === "summary" && (
          <Textarea
            rows={4}
            maxLength={CANDIDATE_SUMMARY_MAX_LENGTH}
            value={summary}
            onChange={(e) => onChangeSummary(e.target.value)}
            disabled={readOnly}
            placeholder="一句话概述你的经验、领域和优势。例如：5 年后端经验，专注支付与消息系统，主导过…"
            className="resize-none border-0 bg-transparent p-0 text-sm shadow-none focus-visible:ring-0"
          />
        )}
        {tab === "skills" && (
          <div className="space-y-2">
            <Input
              value={skills}
              onChange={(e) => onChangeSkills(e.target.value)}
              disabled={readOnly}
              maxLength={CANDIDATE_SKILLS_MAX_COUNT * (CANDIDATE_SKILL_MAX_LENGTH + 2)}
              placeholder="例如：React, TypeScript, Next.js"
              className="border-0 bg-transparent p-0 shadow-none focus-visible:ring-0"
            />
            <p className="text-xs text-muted-foreground">
              用逗号分隔多个技能，最多 40 项。AI 会用这些技能匹配题库和评分标准。
            </p>
            {skillCount > 0 && (
              <div className="flex flex-wrap gap-1.5 pt-1">
                {splitCsv(skills).map((s) => (
                  <Badge
                    key={s}
                    variant="outline"
                    className="border-emerald-500/30 bg-emerald-500/5 text-xs font-normal"
                  >
                    {s}
                  </Badge>
                ))}
              </div>
            )}
          </div>
        )}
        {tab === "highlights" && (
          <div className="space-y-2">
            <Textarea
              rows={4}
              maxLength={CANDIDATE_HIGHLIGHTS_MAX_COUNT * CANDIDATE_HIGHLIGHT_MAX_LENGTH}
              value={highlights}
              onChange={(e) => onChangeHighlights(e.target.value)}
              disabled={readOnly}
              placeholder="每行一条经历。建议带具体成果：例如「将首屏加载从 3.2s 优化到 0.9s」"
              className="resize-none border-0 bg-transparent p-0 text-sm shadow-none focus-visible:ring-0"
            />
            <p className="text-xs text-muted-foreground">
              亮点会作为 AI 出题的素材。可以是项目、成果、影响范围。
            </p>
          </div>
        )}
        {tab === "projects" && (
          <div className="space-y-3">
            <p className="text-xs text-muted-foreground">
              AI 会优先围绕这些项目追问，最多 12 个项目。你可以把项目名、技术栈和可追问点改得更准确。
            </p>
            {projects.map((project, idx) => (
              <div key={project.id || idx} className="space-y-2 rounded-md border bg-background/50 p-3">
                <div className="flex items-center justify-between gap-2">
                  <Input
                    value={project.name}
                    onChange={(e) => updateProject(idx, { name: e.target.value })}
                    disabled={readOnly}
                    maxLength={RESUME_PROJECT_NAME_MAX_LENGTH}
                    placeholder="项目名称，例如：支付系统迁移"
                    className="h-8"
                  />
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    disabled={readOnly}
                    onClick={() =>
                      onChangeProjects(projects.filter((_, i) => i !== idx))
                    }
                    aria-label="删除项目"
                  >
                    <X className="h-4 w-4" />
                  </Button>
                </div>
                <Input
                  value={project.role ?? ""}
                  onChange={(e) => updateProject(idx, { role: e.target.value })}
                  disabled={readOnly}
                  maxLength={RESUME_PROJECT_ROLE_MAX_LENGTH}
                  placeholder="你的角色，例如：负责人 / 核心开发"
                  className="h-8"
                />
                <Input
                  value={joinCsv(project.tech_stack ?? [])}
                  onChange={(e) =>
                    updateProject(idx, { tech_stack: splitCsv(e.target.value) })
                  }
                  disabled={readOnly}
                  maxLength={CANDIDATE_SKILLS_MAX_COUNT * (CANDIDATE_SKILL_MAX_LENGTH + 2)}
                  placeholder="技术栈，用逗号分隔，例如：Java, Kafka, Redis"
                  className="h-8"
                />
                <Textarea
                  rows={2}
                  value={(project.question_anchors ?? []).join("\n")}
                  onChange={(e) =>
                    updateProject(idx, {
                      question_anchors: splitCsv(e.target.value),
                    })
                  }
                  disabled={readOnly}
                  maxLength={RESUME_PROJECT_ANCHOR_MAX_COUNT * RESUME_PROJECT_ANCHOR_MAX_LENGTH}
                  placeholder="建议追问点，每行一条，例如：一致性、性能优化、故障恢复"
                  className="resize-none"
                />
              </div>
            ))}
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={addProject}
              disabled={readOnly || projects.length >= RESUME_PROJECTS_MAX_COUNT}
            >
              添加项目
            </Button>
          </div>
        )}
        {tab === "focus" && (
          <div className="space-y-3">
            <p className="text-xs text-muted-foreground">
              这些是 AI 从简历项目里整理出的考察重点，最多 20 个重点。留空也可以，系统会按方向和 JD 兜底。
            </p>
            {focusAreas.map((focus, idx) => (
              <div key={focus.id || idx} className="space-y-2 rounded-md border bg-background/50 p-3">
                <div className="flex items-center justify-between gap-2">
                  <Input
                    value={focus.label}
                    onChange={(e) => updateFocus(idx, { label: e.target.value })}
                    disabled={readOnly}
                    maxLength={RESUME_FOCUS_LABEL_MAX_LENGTH}
                    placeholder="考察重点，例如：支付迁移中的幂等和一致性"
                    className="h-8"
                  />
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    disabled={readOnly}
                    onClick={() =>
                      onChangeFocusAreas(focusAreas.filter((_, i) => i !== idx))
                    }
                    aria-label="删除重点"
                  >
                    <X className="h-4 w-4" />
                  </Button>
                </div>
                <Input
                  value={joinCsv(focus.skills ?? [])}
                  onChange={(e) =>
                    updateFocus(idx, { skills: splitCsv(e.target.value) })
                  }
                  disabled={readOnly}
                  maxLength={CANDIDATE_SKILLS_MAX_COUNT * (CANDIDATE_SKILL_MAX_LENGTH + 2)}
                  placeholder="关联技能，用逗号分隔"
                  className="h-8"
                />
              </div>
            ))}
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={addFocusArea}
              disabled={readOnly || focusAreas.length >= RESUME_FOCUS_AREAS_MAX_COUNT}
            >
              添加重点
            </Button>
            {concerns.length > 0 && (
              <div className="rounded-md border border-amber-500/20 bg-amber-500/5 p-3 text-xs text-muted-foreground">
                <div className="mb-1 font-medium text-amber-300">
                  可能会先确认
                </div>
                <ul className="space-y-1">
                  {concerns.map((item) => (
                    <li key={item}>· {item}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function ResumeFocusSummary({
  focusAreas,
  direction,
}: {
  focusAreas: ResumeFocusArea[];
  direction: ReturnType<typeof directionById>;
}) {
  const visible = normaliseFocusAreas(focusAreas).slice(0, 6);
  if (visible.length === 0) {
    return (
      <div className="rounded-md border bg-secondary/30 px-3 py-2 text-xs text-muted-foreground">
        还没有从简历中提取到明确项目重点。AI 会先按「{direction.label}」方向考察，
        并结合岗位描述和本地题库补充基础题。
        <div className="mt-2 flex flex-wrap gap-1.5">
          {direction.skills.slice(0, 6).map((skill) => (
            <Badge key={skill} variant="outline" className="text-[11px]">
              {skill}
            </Badge>
          ))}
        </div>
      </div>
    );
  }
  return (
    <div className="rounded-md border border-emerald-500/20 bg-emerald-500/5 px-3 py-2">
      <div className="mb-2 text-xs text-muted-foreground">
        已根据简历项目生成重点。面试会优先从这些经历切入，基础题和算法题会作为补充。
      </div>
      <div className="flex flex-wrap gap-1.5">
        {visible.map((focus) => (
          <Badge
            key={focus.id}
            variant="outline"
            className="border-emerald-500/30 bg-emerald-500/5 text-[11px]"
          >
            {focus.label}
          </Badge>
        ))}
      </div>
    </div>
  );
}

function JdHint({
  status,
  onRetry,
}: {
  status: JdStatus;
  onRetry: () => void;
}) {
  if (status.kind === "idle") {
    return (
      <span className="text-xs text-muted-foreground">
        粘贴 JD 后，AI 会自动识别考察重点
      </span>
    );
  }
  if (status.kind === "parsing") {
    return (
      <span className="flex items-center gap-1 text-xs text-emerald-400">
        <Loader2 className="h-3 w-3 animate-spin" />
        分析中…
      </span>
    );
  }
  if (status.kind === "success") {
    return (
      <span className="flex items-center gap-1 text-xs text-emerald-400">
        <Sparkles className="h-3 w-3" />
        已识别考察重点
      </span>
    );
  }
  return (
    <span className="flex flex-wrap items-center gap-2 text-xs text-destructive">
      <span>
        JD 分析失败，仍可继续使用默认考察维度：{status.message}
      </span>
      <button
        type="button"
        onClick={onRetry}
        className="rounded border border-destructive/30 px-1.5 py-0.5 text-[11px] transition-colors hover:bg-destructive/10"
      >
        重试
      </button>
    </span>
  );
}

function DimensionPicker({
  selected,
  catalog,
  onToggle,
  onRemove,
}: {
  selected: DimensionOption[];
  catalog: DimensionOption[];
  onToggle: (option: DimensionOption) => void;
  onRemove: (id: string) => void;
}) {
  const selectedIds = new Set(selected.map((d) => d.id));
  const inactive = catalog.filter((d) => !selectedIds.has(d.id));

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        {selected.length === 0 ? (
          <span className="text-sm text-muted-foreground">
            尚未选择考察维度，至少保留一项
          </span>
        ) : (
          selected.map((d) => (
            <button
              key={d.id}
              type="button"
              onClick={() => onRemove(d.id)}
              className="group flex items-center gap-1 rounded-full border border-emerald-500/40 bg-emerald-500/10 px-3 py-1 text-xs text-emerald-200 transition-all hover:border-destructive/40 hover:bg-destructive/10 hover:text-destructive"
            >
              <span>{d.label}</span>
              <X className="h-3 w-3 opacity-60 transition-opacity group-hover:opacity-100" />
            </button>
          ))
        )}
      </div>

      {inactive.length > 0 && (
        <div className="space-y-1.5">
          <p className="text-xs text-muted-foreground">点击添加：</p>
          <div className="flex flex-wrap gap-2">
            {inactive.map((d) => (
              <button
                key={d.id}
                type="button"
                onClick={() => onToggle(d)}
                disabled={selected.length >= 5}
                className="rounded-full border border-border px-3 py-1 text-xs text-muted-foreground transition-all hover:border-emerald-500/40 hover:bg-emerald-500/5 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40"
              >
                + {d.label}
              </button>
            ))}
          </div>
          {selected.length >= 5 && (
            <p className="text-xs text-muted-foreground">
              最多 5 项考察维度
            </p>
          )}
        </div>
      )}
    </div>
  );
}

function LengthPicker({
  value,
  onChange,
}: {
  value: "short" | "standard" | "deep";
  onChange: (v: "short" | "standard" | "deep") => void;
}) {
  return (
    <div
      className="grid grid-cols-3 gap-3"
      role="radiogroup"
      aria-label="面试深度选择"
    >
      {LENGTH_OPTIONS.map((opt) => {
        const active = value === opt.id;
        return (
          <button
            key={opt.id}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => onChange(opt.id)}
            onKeyDown={(e) => {
              if (e.key === "ArrowRight" || e.key === "ArrowDown") {
                e.preventDefault();
                const idx = LENGTH_OPTIONS.findIndex((o) => o.id === opt.id);
                const nextIdx = (idx + 1) % LENGTH_OPTIONS.length;
                onChange(LENGTH_OPTIONS[nextIdx].id);
                const nextEl = document.getElementById(`length-picker-${LENGTH_OPTIONS[nextIdx].id}`);
                nextEl?.focus();
              } else if (e.key === "ArrowLeft" || e.key === "ArrowUp") {
                e.preventDefault();
                const idx = LENGTH_OPTIONS.findIndex((o) => o.id === opt.id);
                const nextIdx = (idx - 1 + LENGTH_OPTIONS.length) % LENGTH_OPTIONS.length;
                onChange(LENGTH_OPTIONS[nextIdx].id);
                const nextEl = document.getElementById(`length-picker-${LENGTH_OPTIONS[nextIdx].id}`);
                nextEl?.focus();
              }
            }}
            id={`length-picker-${opt.id}`}
            tabIndex={active ? 0 : -1}
            className={`flex flex-col items-start rounded-lg border-2 px-4 py-3 text-left transition-all ${
              active
                ? "border-emerald-500/60 bg-emerald-500/10"
                : "border-border hover:border-emerald-500/30 hover:bg-emerald-500/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/50"
            }`}
          >
            <span
              className={`text-base font-medium ${active ? "text-emerald-300" : ""}`}
            >
              {opt.label}
            </span>
            <span className="text-xs text-muted-foreground">{opt.desc}</span>
          </button>
        );
      })}
    </div>
  );
}

type RegisterFn = ReturnType<typeof useForm<FormValues>>["register"];
type ErrorMap = ReturnType<typeof useForm<FormValues>>["formState"]["errors"];

function AdvancedPanel({
  open,
  onToggle,
  register,
  errors,
  enableVideoAnalysis,
  onToggleVideo,
}: {
  open: boolean;
  onToggle: () => void;
  register: RegisterFn;
  errors: ErrorMap;
  enableVideoAnalysis: boolean;
  onToggleVideo: () => void;
}) {
  return (
    <div className="rounded-lg border bg-secondary/20">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        aria-controls="advanced-panel-content"
        className="flex w-full items-center justify-between px-4 py-3 text-sm transition-colors hover:bg-secondary/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/50"
      >
        <span className="flex items-center gap-2 text-muted-foreground">
          高级选项
          <span className="text-xs">（开发者用，正常情况无需修改）</span>
        </span>
        <ChevronDown
          className={`h-4 w-4 text-muted-foreground transition-transform ${
            open ? "rotate-180" : ""
          }`}
        />
      </button>
      {open && (
        <div id="advanced-panel-content" className="grid gap-4 border-t px-4 py-4 md:grid-cols-3">
          <div className="space-y-1.5">
            <Label className="text-sm">最大轮数（覆盖深度预设）</Label>
            <Input
              type="number"
              min={1}
              max={20}
              placeholder="留空则按深度预设"
              aria-invalid={Boolean(errors.max_turns_override)}
              aria-describedby={
                errors.max_turns_override
                  ? fieldErrorId("max_turns_override")
                  : undefined
              }
              {...register("max_turns_override")}
            />
            {errors.max_turns_override && (
              <p id={fieldErrorId("max_turns_override")} className="text-xs text-destructive">
                {errors.max_turns_override.message}
              </p>
            )}
          </div>
          <div className="space-y-1.5">
            <Label className="text-sm">通过阈值 (0-10)</Label>
            <p className="text-xs text-muted-foreground">
              判定本场面试&quot;达标&quot;的目标分数；高于此分会显示&quot;达到目标水平&quot;。
            </p>
            <Input
              type="number"
              step="0.1"
              min={0}
              max={10}
              aria-invalid={Boolean(errors.quality_threshold)}
              aria-describedby={
                errors.quality_threshold
                  ? fieldErrorId("quality_threshold")
                  : undefined
              }
              {...register("quality_threshold")}
            />
            {errors.quality_threshold && (
              <p id={fieldErrorId("quality_threshold")} className="text-xs text-destructive">
                {errors.quality_threshold.message}
              </p>
            )}
          </div>
          <div className="space-y-1.5">
            <Label className="text-sm">总轮次预算（含追问）</Label>
            <Input
              type="number"
              min={1}
              max={30}
              placeholder="默认 = 最大轮数 + 2"
              aria-invalid={Boolean(errors.turn_budget_override)}
              aria-describedby={
                errors.turn_budget_override
                  ? fieldErrorId("turn_budget_override")
                  : undefined
              }
              {...register("turn_budget_override")}
            />
            {errors.turn_budget_override && (
              <p id={fieldErrorId("turn_budget_override")} className="text-xs text-destructive">
                {errors.turn_budget_override.message}
              </p>
            )}
          </div>
          <div className="col-span-full flex items-center gap-3 pt-1">
            <button
              type="button"
              role="switch"
              aria-checked={enableVideoAnalysis}
              aria-label="启用视频分析"
              onClick={onToggleVideo}
              className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors ${
                enableVideoAnalysis ? "bg-emerald-600" : "bg-secondary"
              }`}
            >
              <span
                className={`pointer-events-none block h-4 w-4 rounded-full bg-white shadow-sm transition-transform ${
                  enableVideoAnalysis ? "translate-x-4" : "translate-x-0"
                }`}
              />
            </button>
            <Label className="cursor-pointer text-sm" onClick={onToggleVideo}>
              启用视频分析
              <span className="ml-1.5 text-xs text-muted-foreground">
                （面试中开启摄像头采集面部特征用于评估）
              </span>
            </Label>
          </div>
        </div>
      )}
    </div>
  );
}
