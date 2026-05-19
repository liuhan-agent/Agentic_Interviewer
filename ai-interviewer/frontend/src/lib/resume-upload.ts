import type {
  Candidate,
  LLMConfigPayload,
  ResumeParseJobResponse,
  ParseResumeResponse,
  ResumeCandidateProfile,
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

const QWEN_FLASH_MODEL = "qwen3.6-flash";
const QWEN_PLUS_MODEL = "qwen3.6-plus";

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
    resumeParsed.summary = args.summary.trim();
  }
  if (args.skills && args.skills.length > 0) {
    resumeParsed.skills = args.skills;
  }
  if (args.highlights && args.highlights.length > 0) {
    resumeParsed.highlights = args.highlights;
  }
  if (args.projects && args.projects.length > 0) {
    resumeParsed.projects = args.projects;
  }
  if (args.focus_areas && args.focus_areas.length > 0) {
    resumeParsed.focus_areas = args.focus_areas;
  }
  if (args.concerns && args.concerns.length > 0) {
    resumeParsed.concerns = args.concerns;
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
