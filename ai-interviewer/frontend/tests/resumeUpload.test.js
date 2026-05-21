const assert = require("node:assert/strict");
const test = require("node:test");

const {
  candidateNameAutofillValue,
  resumeJobAutofillValues,
  parseResumeForSetup,
  resumeParsedForSession,
  resumeReuploadInputValue,
  resumeSourceIdForSession,
  resumeSourceRefFromParseResult,
} = require("../src/lib/resume-upload.ts");

test("passes the current LLM payload to resume parsing", async () => {
  const file = { name: "resume.txt", size: 128 };
  const llmConfig = {
    provider: "qwen",
    api_key: "default-key",
    model: "qwen3.6-flash",
    role_overrides: {
      resume_parser: {
        provider: "kimi",
        api_key: "resume-key",
        model: "kimi-k2.6",
      },
    },
  };
  const response = {
    summary: "parsed",
    skills: [],
    highlights: [],
    raw_text_preview: "parsed",
  };
  const calls = [];

  const result = await parseResumeForSetup(file, {
    buildLLMPayload: () => llmConfig,
    parseResume: async (receivedFile, receivedConfig) => {
      calls.push({ file: receivedFile, llmConfig: receivedConfig });
      return response;
    },
  });

  assert.equal(result, response);
  assert.deepEqual(calls, [{ file, llmConfig }]);
});

test("still parses resumes when no personal LLM payload exists", async () => {
  const file = { name: "resume.txt", size: 128 };
  const calls = [];

  await parseResumeForSetup(file, {
    buildLLMPayload: () => undefined,
    parseResume: async (receivedFile, receivedConfig) => {
      calls.push({ file: receivedFile, llmConfig: receivedConfig });
      return {
        summary: "basic",
        skills: [],
        highlights: [],
        raw_text_preview: "basic",
      };
    },
  });

  assert.deepEqual(calls, [{ file, llmConfig: undefined }]);
});

test("autofills parsed candidate name only when the field is empty", () => {
  assert.equal(
    candidateNameAutofillValue({ candidate_name: " 刘韩 " }, ""),
    "刘韩",
  );
  assert.equal(
    candidateNameAutofillValue({ candidate_name: "刘韩" }, "手动称呼"),
    null,
  );
  assert.equal(candidateNameAutofillValue({ summary: "parsed" }, ""), null);
});

test("session resume payload keeps candidate profile for setup snapshots", () => {
  const candidateProfile = {
    education_level: "本科",
    school: "九江学院",
    major: "软件工程",
    experience_years: 5,
    current_or_target_role: "Java 后端",
  };
  const parsed = resumeParsedForSession({
    candidate_name: "刘韩",
    candidate_profile: candidateProfile,
    summary: "parsed",
    skills: ["java"],
    highlights: ["project"],
    projects: [],
    focus_areas: [],
    concerns: [],
    raw_text_preview: "raw",
  });

  assert.deepEqual(parsed, {
    summary: "parsed",
    skills: ["java"],
    highlights: ["project"],
    candidate_profile: candidateProfile,
  });
});

test("session resume payload sanitizes parsed projects and focus areas", () => {
  const parsed = resumeParsedForSession({
    projects: [
      {
        id: "p".repeat(60),
        name: ` ${"n".repeat(140)} `,
        role: "r".repeat(100),
        tech_stack: ["java"],
        responsibilities: ["x".repeat(260)],
        achievements: ["a"],
        question_anchors: ["q".repeat(180)],
        unexpected: "drop-me",
      },
    ],
    focus_areas: [
      {
        id: "f".repeat(60),
        label: ` ${"l".repeat(180)} `,
        project_id: "p".repeat(60),
        dimensions: ["system_design"],
        skills: ["redis"],
        priority: 2,
        unexpected: "drop-me-too",
      },
    ],
  });

  assert.deepEqual(parsed.projects, [
    {
      id: "p".repeat(40),
      name: "n".repeat(120),
      role: "r".repeat(80),
      tech_stack: ["java"],
      responsibilities: ["x".repeat(240)],
      achievements: ["a"],
      question_anchors: ["q".repeat(160)],
    },
  ]);
  assert.deepEqual(parsed.focus_areas, [
    {
      id: "f".repeat(40),
      label: "l".repeat(160),
      project_id: "p".repeat(40),
      dimensions: ["system_design"],
      skills: ["redis"],
      priority: 2,
    },
  ]);
});

test("autofills job suggestion only before user edits job fields", () => {
  const profile = {
    suggested_job_title: "Java 后端开发工程师",
    suggested_job_level: "junior",
  };

  assert.deepEqual(
    resumeJobAutofillValues({
      profile,
      currentTitle: "Java 后端开发工程师",
      titleDirty: false,
      levelDirty: false,
    }),
    {
      jobTitle: "Java 后端开发工程师",
      jobLevel: "junior",
    },
  );
  assert.deepEqual(
    resumeJobAutofillValues({
      profile,
      currentTitle: "手动岗位",
      titleDirty: true,
      levelDirty: true,
    }),
    {},
  );
});

test("uses qwen plus for resume parsing when default config is qwen flash", async () => {
  const file = { name: "resume.txt", size: 128 };
  const llmConfig = {
    provider: "qwen",
    api_key: "default-key",
    model: "qwen3.6-flash",
    base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    embedding_override: {
      provider: "qwen",
      api_key: "default-key",
      model: "text-embedding-v4",
      base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1",
      dimensions: 1536,
    },
  };
  const calls = [];

  await parseResumeForSetup(file, {
    buildLLMPayload: () => llmConfig,
    parseResume: async (receivedFile, receivedConfig) => {
      calls.push({ file: receivedFile, llmConfig: receivedConfig });
      return {
        summary: "parsed",
        skills: [],
        highlights: [],
        raw_text_preview: "parsed",
      };
    },
  });

  assert.deepEqual(calls, [
    {
      file,
      llmConfig: {
        provider: "qwen",
        api_key: "default-key",
        model: "qwen3.6-flash",
        base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1",
        embedding_override: {
          provider: "qwen",
          api_key: "default-key",
          model: "text-embedding-v4",
          base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1",
          dimensions: 1536,
        },
        role_overrides: {
          resume_parser: {
            provider: "qwen",
            model: "qwen3.6-plus",
            base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1",
          },
        },
      },
    },
  ]);
  assert.equal(llmConfig.role_overrides, undefined);
});

test("clears the file input before reupload so selecting the same file fires change", () => {
  assert.equal(resumeReuploadInputValue(), "");
});

test("keeps resume parse artifact ids separate from parsed resume fields", () => {
  assert.deepEqual(
    resumeSourceRefFromParseResult({
      resume_source_id: "  artifact_123  ",
      resume_source_expires_at: "2099-01-01T00:00:00Z",
    }),
    {
      id: "artifact_123",
      expiresAt: "2099-01-01T00:00:00Z",
    },
  );
  assert.equal(resumeSourceRefFromParseResult({}), null);
});

test("only sends non-expired resume source ids to session creation", () => {
  assert.equal(
    resumeSourceIdForSession(
      { id: "artifact_123", expiresAt: "2099-01-01T00:00:00Z" },
      Date.parse("2026-05-18T00:00:00Z"),
    ),
    "artifact_123",
  );
  assert.equal(
    resumeSourceIdForSession(
      { id: "artifact_123", expiresAt: "2026-05-17T00:00:00Z" },
      Date.parse("2026-05-18T00:00:00Z"),
    ),
    undefined,
  );
});
