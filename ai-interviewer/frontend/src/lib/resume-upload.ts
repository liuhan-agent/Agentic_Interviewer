import type {
  Candidate,
  LLMConfigPayload,
  ResumeParseJobResponse,
  ParseResumeResponse,
  ResumeCandidateProfile,
  ResumeFocusArea,
  ResumeProject,
} from "./api/types";

type ParseResumeFn = (
  file: File,
  llmConfig?: LLMConfigPayload,
) => Promise<ParseResumeResponse>;

type BuildLLMPayloadFn = () => LLMConfigPayload | undefined;

interface ParseResumeForSetupDeps {
  parseResume: ParseResumeFn;
  buildLLMPayload: BuildLLMPayloadFn;
}

type CreateResumeParseJobFn = (
  file: File,
  llmConfig?: LLMConfigPayload,
) => Promise<ResumeParseJobResponse>;

interface CreateResumeParseJobForSetupDeps {
  createResumeParseJob: CreateResumeParseJobFn;
  buildLLMPayload: BuildLLMPayloadFn;
}

export interface ResumeSourceRef {
  id: string;
  expiresAt?: string;
}

const QWEN_FLASH_MODEL = "qwen3.6-flash";
const QWEN_PLUS_MODEL = "qwen3.6-plus";
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

export function parseResumeForSetup(
  file: File,
  deps: ParseResumeForSetupDeps,
): Promise<ParseResumeResponse> {
  return deps.parseResume(file, preferQwenPlusForResumeParser(deps.buildLLMPayload()));
}

export function createResumeParseJobForSetup(
  file: File,
  deps: CreateResumeParseJobForSetupDeps,
): Promise<ResumeParseJobResponse> {
  return deps.createResumeParseJob(
    file,
    preferQwenPlusForResumeParser(deps.buildLLMPayload()),
  );
}

export function candidateNameAutofillValue(
  result: Pick<ParseResumeResponse, "candidate_name">,
  currentValue: string,
): string | null {
  const candidateName = result.candidate_name?.trim();
  if (!candidateName || currentValue.trim()) return null;
  return candidateName;
}

export function resumeParsedForSession(args: {
  summary?: string;
  skills?: string[];
  highlights?: string[];
  projects?: ParseResumeResponse["projects"];
  focus_areas?: ParseResumeResponse["focus_areas"];
  concerns?: string[];
  candidate_profile?: unknown;
}): Candidate["resume_parsed"] {
  const resumeParsed: Candidate["resume_parsed"] = {};
  if (args.summary?.trim()) {
    resumeParsed.summary = clipString(args.summary, CANDIDATE_SUMMARY_MAX_LENGTH);
  }
  if (args.skills && args.skills.length > 0) {
    resumeParsed.skills = sanitizeStringList(
      args.skills,
      CANDIDATE_SKILLS_MAX_COUNT,
      CANDIDATE_SKILL_MAX_LENGTH,
    );
  }
  if (args.highlights && args.highlights.length > 0) {
    resumeParsed.highlights = sanitizeStringList(
      args.highlights,
      CANDIDATE_HIGHLIGHTS_MAX_COUNT,
      CANDIDATE_HIGHLIGHT_MAX_LENGTH,
    );
  }
  if (args.projects && args.projects.length > 0) {
    resumeParsed.projects = sanitizeResumeProjects(args.projects);
  }
  if (args.focus_areas && args.focus_areas.length > 0) {
    resumeParsed.focus_areas = sanitizeResumeFocusAreas(args.focus_areas);
  }
  if (args.concerns && args.concerns.length > 0) {
    resumeParsed.concerns = sanitizeStringList(
      args.concerns,
      10,
      RESUME_PROJECT_ANCHOR_MAX_LENGTH,
    );
  }
  if (
    isPlainObject(args.candidate_profile) &&
    Object.keys(args.candidate_profile).length > 0
  ) {
    resumeParsed.candidate_profile =
      args.candidate_profile as ResumeCandidateProfile;
  }
  return resumeParsed;
}

function clipString(value: unknown, maxLength: number): string {
  return String(value ?? "").trim().slice(0, maxLength);
}

function optionalClipString(value: unknown, maxLength: number): string | undefined {
  const clipped = clipString(value, maxLength);
  return clipped || undefined;
}

function sanitizeStringList(
  items: unknown,
  maxCount: number,
  maxLength: number,
): string[] {
  if (!Array.isArray(items)) return [];
  return items
    .map((item) => clipString(item, maxLength))
    .filter(Boolean)
    .slice(0, maxCount);
}

function sanitizeResumeProjects(projects: unknown): ResumeProject[] {
  if (!Array.isArray(projects)) return [];
  return projects
    .filter(isPlainObject)
    .map((project, idx): ResumeProject | null => {
      const name = clipString(project.name, RESUME_PROJECT_NAME_MAX_LENGTH);
      if (!name) return null;
      const role = optionalClipString(project.role, RESUME_PROJECT_ROLE_MAX_LENGTH);
      return {
        id:
          optionalClipString(project.id, 40) ??
          `proj-${idx + 1}`,
        name,
        ...(role ? { role } : {}),
        tech_stack: sanitizeStringList(
          project.tech_stack,
          CANDIDATE_SKILLS_MAX_COUNT,
          CANDIDATE_SKILL_MAX_LENGTH,
        ),
        responsibilities: sanitizeStringList(
          project.responsibilities,
          CANDIDATE_HIGHLIGHTS_MAX_COUNT,
          CANDIDATE_HIGHLIGHT_MAX_LENGTH,
        ),
        achievements: sanitizeStringList(
          project.achievements,
          CANDIDATE_HIGHLIGHTS_MAX_COUNT,
          CANDIDATE_HIGHLIGHT_MAX_LENGTH,
        ),
        question_anchors: sanitizeStringList(
          project.question_anchors,
          RESUME_PROJECT_ANCHOR_MAX_COUNT,
          RESUME_PROJECT_ANCHOR_MAX_LENGTH,
        ),
      };
    })
    .filter((project): project is ResumeProject => project !== null)
    .slice(0, RESUME_PROJECTS_MAX_COUNT);
}

function sanitizeResumeFocusAreas(focusAreas: unknown): ResumeFocusArea[] {
  if (!Array.isArray(focusAreas)) return [];
  return focusAreas
    .filter(isPlainObject)
    .map((focus, idx): ResumeFocusArea | null => {
      const label = clipString(focus.label, RESUME_FOCUS_LABEL_MAX_LENGTH);
      if (!label) return null;
      const rawPriority = Number(focus.priority);
      const priority = Number.isFinite(rawPriority)
        ? Math.trunc(rawPriority)
        : idx + 1;
      return {
        id:
          optionalClipString(focus.id, 40) ??
          `focus-${idx + 1}`,
        ...(optionalClipString(focus.anchor_key, 160)
          ? { anchor_key: optionalClipString(focus.anchor_key, 160) }
          : {}),
        label,
        project_id: optionalClipString(focus.project_id, 40) ?? null,
        dimensions: sanitizeStringList(focus.dimensions, 20, CANDIDATE_SKILL_MAX_LENGTH),
        skills: sanitizeStringList(
          focus.skills,
          CANDIDATE_SKILLS_MAX_COUNT,
          CANDIDATE_SKILL_MAX_LENGTH,
        ),
        priority,
      };
    })
    .filter((focus): focus is ResumeFocusArea => focus !== null)
    .slice(0, RESUME_FOCUS_AREAS_MAX_COUNT);
}

export function resumeJobAutofillValues(args: {
  profile?: ResumeCandidateProfile;
  currentTitle: string;
  titleDirty: boolean;
  levelDirty: boolean;
}): { jobTitle?: string; jobLevel?: NonNullable<ResumeCandidateProfile["suggested_job_level"]> } {
  const result: {
    jobTitle?: string;
    jobLevel?: NonNullable<ResumeCandidateProfile["suggested_job_level"]>;
  } = {};
  const suggestedTitle = args.profile?.suggested_job_title?.trim();
  if (suggestedTitle && !args.titleDirty) {
    result.jobTitle = suggestedTitle;
  }
  if (args.profile?.suggested_job_level && !args.levelDirty) {
    result.jobLevel = args.profile.suggested_job_level;
  }
  return result;
}

export function resumeReuploadInputValue(): string {
  return "";
}

export function resumeSourceRefFromParseResult(
  result: Pick<ParseResumeResponse, "resume_source_id" | "resume_source_expires_at">,
): ResumeSourceRef | null {
  const id = result.resume_source_id?.trim();
  if (!id) return null;
  return {
    id,
    ...(result.resume_source_expires_at
      ? { expiresAt: result.resume_source_expires_at }
      : {}),
  };
}

export function resumeSourceIdForSession(
  source: ResumeSourceRef | null | undefined,
  now = Date.now(),
): string | undefined {
  const id = source?.id?.trim();
  if (!id) return undefined;
  if (source?.expiresAt) {
    const expiresAt = Date.parse(source.expiresAt);
    if (Number.isFinite(expiresAt) && expiresAt <= now) {
      return undefined;
    }
  }
  return id;
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function preferQwenPlusForResumeParser(
  payload: LLMConfigPayload | undefined,
): LLMConfigPayload | undefined {
  if (!payload) return undefined;
  if (payload.role_overrides?.resume_parser) return payload;
  if (payload.provider !== "qwen" || payload.model !== QWEN_FLASH_MODEL) {
    return payload;
  }
  return {
    ...payload,
    role_overrides: {
      ...(payload.role_overrides ?? {}),
      resume_parser: {
        provider: "qwen",
        model: QWEN_PLUS_MODEL,
        ...(payload.base_url ? { base_url: payload.base_url } : {}),
      },
    },
  };
}
