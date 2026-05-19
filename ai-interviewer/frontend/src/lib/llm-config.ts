import { ApiError, request } from "@/lib/api/client";
import type { LLMErrorKind as ApiLLMErrorKind } from "@/lib/api/types";

const STORAGE_KEY = "llm-config";
const TEST_STATUS_KEY = "llm-config-test-status";
export const LLM_CONFIG_EVENT = "llm-config-updated";

const OBF_KEY = "v1:bajie-llm-obf:";

function obfuscate(text: string): string {
  if (typeof window === "undefined") return text;
  return OBF_KEY + btoa(encodeURIComponent(text));
}

function deobfuscate(text: string): string {
  if (typeof window === "undefined") return text;
  if (text.startsWith(OBF_KEY)) {
    try {
      return decodeURIComponent(atob(text.slice(OBF_KEY.length)));
    } catch {
      return text;
    }
  }
  return text;
}

export interface LLMConfig {
  provider: string;
  apiKey: string;
  model: string;
  temperature: number;
  baseUrl: string;
  roleOverrides: Partial<Record<LLMRoleGroupId, LLMRoleOverrideConfig>>;
  voiceOverrides: Partial<Record<LLMVoiceRouteId, LLMVoiceOverrideConfig>>;
  embeddingOverride: LLMEmbeddingOverrideConfig;
  storageMode?: "local" | "session" | "memory";
}

export type LLMRoleKey =
  | "resume_parser"
  | "jd_parser"
  | "self_intro_parser"
  | "generator"
  | "llm_planner"
  | "rubric_negotiator"
  | "contract_negotiator"
  | "memory_selector"
  | "evaluator"
  | "verifier"
  | "coach"
  | "session_summarizer"
  | "guard";

export type LLMRoleGroupId =
  | "resume_parsing"
  | "questioning"
  | "evaluation"
  | "verification"
  | "coaching"
  | "safety";

export interface LLMRoleOverrideConfig {
  enabled: boolean;
  provider: string;
  apiKey: string;
  model: string;
  baseUrl: string;
}

export type LLMVoiceRouteId = "asr" | "tts";
export type LLMVoiceProviderId = "qwen" | "openai";
export type LLMEmbeddingRouteId = "session_anchor";
export type LLMEmbeddingProviderId = "qwen" | "openai" | "openai_compatible";

export interface LLMVoiceOverrideConfig {
  enabled?: boolean;
  provider: LLMVoiceProviderId;
  apiKey: string;
  model: string;
  baseUrl: string;
  voice?: string;
}

export interface LLMEmbeddingOverrideConfig {
  enabled?: boolean;
  provider: LLMEmbeddingProviderId;
  apiKey: string;
  model: string;
  baseUrl: string;
  dimensions: number;
}

export interface VoiceProviderInfo {
  id: LLMVoiceProviderId;
  label: string;
  asrModel: string;
  ttsModel: string;
  ttsVoice: string;
  ttsVoices: readonly string[];
  baseUrl: string;
  keyPlaceholder: string;
}

export interface EmbeddingProviderInfo {
  id: LLMEmbeddingProviderId;
  label: string;
  model: string;
  baseUrl: string;
  keyPlaceholder: string;
  baseUrlMode: "optional" | "required";
}

export type LLMErrorKind = ApiLLMErrorKind;

export interface ProviderInfo {
  id: string;
  label: string;
  defaultModel: string;
  defaultBaseUrl: string;
  keyPlaceholder: string;
  baseUrlMode: "hidden" | "optional" | "required";
}

export const PROVIDERS = [
  {
    id: "openai",
    label: "OpenAI",
    defaultModel: "gpt-4o-mini",
    defaultBaseUrl: "",
    keyPlaceholder: "sk-...",
    baseUrlMode: "optional",
  },
  {
    id: "anthropic",
    label: "Anthropic (Claude)",
    defaultModel: "claude-sonnet-4-20250514",
    defaultBaseUrl: "",
    keyPlaceholder: "sk-ant-...",
    baseUrlMode: "optional",
  },
  {
    id: "deepseek",
    label: "DeepSeek",
    defaultModel: "deepseek-chat",
    defaultBaseUrl: "https://api.deepseek.com/v1",
    keyPlaceholder: "sk-...",
    baseUrlMode: "optional",
  },
  {
    id: "kimi",
    label: "Kimi",
    defaultModel: "kimi-k2.6",
    defaultBaseUrl: "https://api.moonshot.cn/v1",
    keyPlaceholder: "sk-...",
    baseUrlMode: "optional",
  },
  {
    id: "qwen",
    label: "通义千问",
    defaultModel: "qwen3.6-flash",
    defaultBaseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    keyPlaceholder: "sk-...",
    baseUrlMode: "optional",
  },
  {
    id: "zhipu",
    label: "智谱 GLM",
    defaultModel: "glm-4.7-flash",
    defaultBaseUrl: "https://open.bigmodel.cn/api/paas/v4/",
    keyPlaceholder: "sk-...",
    baseUrlMode: "optional",
  },
  {
    id: "mistral",
    label: "Mistral",
    defaultModel: "mistral-small-latest",
    defaultBaseUrl: "https://api.mistral.ai/v1",
    keyPlaceholder: "...",
    baseUrlMode: "optional",
  },
  {
    id: "openai_compatible",
    label: "自定义 OpenAI-Compatible",
    defaultModel: "",
    defaultBaseUrl: "",
    keyPlaceholder: "sk-...",
    baseUrlMode: "required",
  },
] as const satisfies readonly ProviderInfo[];

export const VOICE_PROVIDERS = [
  {
    id: "qwen",
    label: "通义千问 Qwen",
    asrModel: "qwen3-asr-flash-realtime",
    ttsModel: "qwen3-tts-flash-realtime",
    ttsVoice: "Cherry",
    ttsVoices: ["Cherry", "Serena", "Ethan", "Chelsie"],
    baseUrl: "wss://dashscope.aliyuncs.com/api-ws/v1/realtime",
    keyPlaceholder: "sk-...",
  },
  {
    id: "openai",
    label: "OpenAI",
    asrModel: "whisper-1",
    ttsModel: "gpt-4o-mini-tts",
    ttsVoice: "alloy",
    ttsVoices: ["alloy"],
    baseUrl: "",
    keyPlaceholder: "sk-...",
  },
] as const satisfies readonly VoiceProviderInfo[];

export const EMBEDDING_DIMENSIONS = 1536;

export const EMBEDDING_PROVIDERS = [
  {
    id: "qwen",
    label: "通义千问 Qwen",
    model: "text-embedding-v4",
    baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    keyPlaceholder: "sk-...",
    baseUrlMode: "optional",
  },
] as const satisfies readonly EmbeddingProviderInfo[];

export interface LLMRecommendation {
  provider: string;
  model: string;
}

export interface LLMRoleGroupInfo {
  id: LLMRoleGroupId;
  label: string;
  roles: LLMRoleKey[];
  description: string;
  keyHint: string;
  recommendations: [LLMRecommendation, LLMRecommendation];
}

export const LLM_ROLE_GROUPS: readonly LLMRoleGroupInfo[] = [
  {
    id: "resume_parsing",
    label: "简历 / JD / 开场解析",
    roles: ["resume_parser", "jd_parser", "self_intro_parser"],
    description: "整理简历项目和岗位要求，提取技能、项目重点、JD 能力维度和可追问点，建议使用理解力更强的模型。",
    keyHint: "不填则沿用默认 Key；只在上传简历或分析岗位要求时临时使用。",
    recommendations: [
      { provider: "qwen", model: "qwen3.6-plus" },
      { provider: "kimi", model: "kimi-k2.6" },
    ],
  },
  {
    id: "questioning",
    label: "出题与追问",
    roles: [
      "generator",
      "llm_planner",
      "rubric_negotiator",
      "contract_negotiator",
      "memory_selector",
    ],
    description: "生成面试题、追问方向和评分标准，适合使用轻量但稳定的模型。",
    keyHint: "不填则沿用默认 Key；换服务商时建议填写该服务商 Key。",
    recommendations: [
      { provider: "qwen", model: "qwen3.6-flash" },
      { provider: "zhipu", model: "glm-4.7-flash" },
    ],
  },
  {
    id: "evaluation",
    label: "回答评分",
    roles: ["evaluator"],
    description: "给你的回答打分，直接影响报告可信度，建议使用稳定、响应快、能输出结构化评分的模型。",
    keyHint: "不填则沿用默认 Key；如果评分换成另一个服务商，请填写对应 Key。",
    recommendations: [
      { provider: "qwen", model: "qwen3.6-flash" },
      { provider: "deepseek", model: "deepseek-v4-flash" },
    ],
  },
  {
    id: "verification",
    label: "复核检查",
    roles: ["verifier"],
    description: "复核评分是否偏差，使用不同厂商可降低同源判断偏差。",
    keyHint: "不填则沿用默认 Key；跨厂商复核时建议填写复核厂商 Key。",
    recommendations: [
      { provider: "kimi", model: "kimi-k2.6" },
      { provider: "qwen", model: "qwen3.6-plus" },
    ],
  },
  {
    id: "coaching",
    label: "反馈与提升计划",
    roles: ["coach", "session_summarizer"],
    description: "生成总结、训练计划和改进建议，轻量模型通常已经够用。",
    keyHint: "不填则沿用默认 Key。",
    recommendations: [
      { provider: "qwen", model: "qwen3.6-flash" },
      { provider: "zhipu", model: "glm-4.7-flash" },
    ],
  },
  {
    id: "safety",
    label: "安全与内容检查",
    roles: ["guard"],
    description: "检查异常输入和敏感内容，建议使用响应快、成本低的模型。",
    keyHint: "不填则沿用默认 Key。",
    recommendations: [
      { provider: "zhipu", model: "glm-4.7-flash" },
      { provider: "qwen", model: "qwen3.6-flash" },
    ],
  },
];

const DEFAULTS: LLMConfig = {
  provider: "qwen",
  apiKey: "",
  model: "qwen3.6-flash",
  temperature: 0.7,
  baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1",
  roleOverrides: {},
  voiceOverrides: {
    asr: {
      enabled: false,
      provider: "qwen",
      apiKey: "",
      model: "qwen3-asr-flash-realtime",
      baseUrl: "wss://dashscope.aliyuncs.com/api-ws/v1/realtime",
    },
    tts: {
      enabled: false,
      provider: "qwen",
      apiKey: "",
      model: "qwen3-tts-flash-realtime",
      voice: "Cherry",
      baseUrl: "wss://dashscope.aliyuncs.com/api-ws/v1/realtime",
    },
  },
  embeddingOverride: {
    enabled: false,
    provider: "qwen",
    apiKey: "",
    model: "text-embedding-v4",
    baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    dimensions: 1536,
  },
  storageMode: "session",
};

let memoryConfig: LLMConfig | null = null;

function normalizeEmbeddingOverride(
  override?: Partial<LLMEmbeddingOverrideConfig>,
): LLMEmbeddingOverrideConfig {
  const provider = embeddingProviderInfo(override?.provider ?? "qwen");
  if (!override || !isSupportedEmbeddingProvider(override.provider ?? "")) {
    return {
      ...DEFAULTS.embeddingOverride,
      enabled: Boolean(override?.enabled),
      provider: provider.id,
      dimensions: EMBEDDING_DIMENSIONS,
    };
  }
  return {
    ...DEFAULTS.embeddingOverride,
    ...override,
    provider: provider.id,
    dimensions: EMBEDDING_DIMENSIONS,
  };
}

export function loadLLMConfig(): LLMConfig {
  if (memoryConfig) return memoryConfig;
  try {
    let raw = window.sessionStorage.getItem(STORAGE_KEY);
    let defaultStorageMode: "local" | "session" | "memory" = "session";
    if (!raw) {
      raw = window.localStorage.getItem(STORAGE_KEY);
      if (raw) defaultStorageMode = "local";
    }
    if (!raw) return { ...DEFAULTS };
    const parsed = JSON.parse(deobfuscate(raw)) as Partial<LLMConfig>;
    return {
      ...DEFAULTS,
      ...parsed,
      roleOverrides: parsed.roleOverrides ?? {},
      voiceOverrides: {
        ...DEFAULTS.voiceOverrides,
        ...(parsed.voiceOverrides ?? {}),
      },
      embeddingOverride: normalizeEmbeddingOverride(parsed.embeddingOverride),
      storageMode: parsed.storageMode ?? defaultStorageMode,
    };
  } catch {
    return { ...DEFAULTS };
  }
}

function emitConfigEvent(): void {
  try {
    window.dispatchEvent(new Event(LLM_CONFIG_EVENT));
  } catch {
    /* window may be unavailable */
  }
}

export function saveLLMConfig(config: LLMConfig): void {
  memoryConfig = config.storageMode === "memory" ? config : null;
  try {
    const payload = obfuscate(JSON.stringify(config));
    if (config.storageMode === "local") {
      window.localStorage.setItem(STORAGE_KEY, payload);
      window.sessionStorage.removeItem(STORAGE_KEY);
    } else if (config.storageMode === "session") {
      window.sessionStorage.setItem(STORAGE_KEY, payload);
      window.localStorage.removeItem(STORAGE_KEY);
    } else {
      window.localStorage.removeItem(STORAGE_KEY);
      window.sessionStorage.removeItem(STORAGE_KEY);
    }
  } catch {
    /* storage may be unavailable */
  }
  emitConfigEvent();
}

export function hasApiKey(): boolean {
  return hasCustomApiKey(loadLLMConfig());
}

export function hasCustomApiKey(config: LLMConfig = loadLLMConfig()): boolean {
  return (
    config.apiKey.trim().length > 0 ||
    enabledRoleGroups(config).some(
      (group) => config.roleOverrides[group.id]?.apiKey.trim(),
    ) ||
    (["asr", "tts"] as const).some(
      (routeId) =>
        config.voiceOverrides[routeId]?.enabled &&
        config.voiceOverrides[routeId]?.apiKey.trim(),
    ) ||
    Boolean(config.embeddingOverride?.enabled && config.embeddingOverride.apiKey.trim())
  );
}

export function providerInfo(provider: string): ProviderInfo {
  return PROVIDERS.find((p) => p.id === provider) ?? PROVIDERS[0];
}

export function voiceProviderInfo(provider: string): VoiceProviderInfo {
  return (
    VOICE_PROVIDERS.find((p) => p.id === provider) ?? VOICE_PROVIDERS[0]
  );
}

export function embeddingProviderInfo(provider: string): EmbeddingProviderInfo {
  return (
    EMBEDDING_PROVIDERS.find((p) => p.id === provider) ?? EMBEDDING_PROVIDERS[0]
  );
}

function isSupportedEmbeddingProvider(provider: string): provider is LLMEmbeddingProviderId {
  return EMBEDDING_PROVIDERS.some((p) => p.id === provider);
}

function normalizeVoiceProvider(provider: string): LLMVoiceProviderId | null {
  if (provider === "dashscope") return "qwen";
  if (provider === "qwen" || provider === "openai") return provider;
  return null;
}

function sameVoiceProvider(a: string, b: string): boolean {
  return normalizeVoiceProvider(a) === normalizeVoiceProvider(b);
}

function normalizeEmbeddingProvider(provider: string): LLMEmbeddingProviderId | null {
  if (provider === "dashscope") return "qwen";
  if (provider === "qwen" || provider === "openai" || provider === "openai_compatible") {
    return provider;
  }
  return null;
}

function sameEmbeddingProvider(a: string, b: string): boolean {
  return normalizeEmbeddingProvider(a) === normalizeEmbeddingProvider(b);
}

export function providerShowsBaseUrl(provider: string): boolean {
  return providerInfo(provider).baseUrlMode !== "hidden";
}

export function providerRequiresBaseUrl(provider: string): boolean {
  return providerInfo(provider).baseUrlMode === "required";
}

export function roleGroupInfo(groupId: LLMRoleGroupId): LLMRoleGroupInfo {
  return LLM_ROLE_GROUPS.find((group) => group.id === groupId) ?? LLM_ROLE_GROUPS[0];
}

export function recommendedRoleOverride(
  groupId: LLMRoleGroupId,
  index = 0,
): LLMRoleOverrideConfig {
  const group = roleGroupInfo(groupId);
  const recommendation = group.recommendations[index] ?? group.recommendations[0];
  const provider = providerInfo(recommendation.provider);
  return {
    enabled: true,
    provider: provider.id,
    apiKey: "",
    model: recommendation.model,
    baseUrl: provider.defaultBaseUrl,
  };
}

export function enabledRoleGroups(config: LLMConfig): LLMRoleGroupInfo[] {
  return LLM_ROLE_GROUPS.filter((group) => config.roleOverrides[group.id]?.enabled);
}

export function effectiveRoleConfig(
  config: LLMConfig,
  groupId: LLMRoleGroupId,
): LLMConfig {
  const override = config.roleOverrides[groupId];
  if (!override?.enabled) return config;
  const provider = override.provider || config.provider;
  const providerChanged = provider !== config.provider;
  return {
    ...config,
    provider,
    apiKey: override.apiKey.trim() || config.apiKey,
    model: override.model || config.model,
    baseUrl:
      override.baseUrl ||
      (providerChanged ? providerInfo(provider).defaultBaseUrl : config.baseUrl),
  };
}

export function defaultVoiceOverride(
  routeId: LLMVoiceRouteId,
  providerId: LLMVoiceProviderId = "qwen",
): LLMVoiceOverrideConfig {
  const provider = voiceProviderInfo(providerId);
  return {
    enabled: true,
    provider: provider.id,
    apiKey: "",
    model: routeId === "asr" ? provider.asrModel : provider.ttsModel,
    baseUrl: provider.baseUrl,
    ...(routeId === "tts" ? { voice: provider.ttsVoice } : {}),
  };
}

export function effectiveVoiceConfig(
  config: LLMConfig,
  routeId: LLMVoiceRouteId,
): LLMVoiceOverrideConfig {
  const override = config.voiceOverrides[routeId] ?? defaultVoiceOverride(routeId);
  const providerId = override.enabled ? override.provider : "qwen";
  const defaults = defaultVoiceOverride(routeId, providerId);
  const effective = override.enabled ? { ...defaults, ...override } : defaults;
  return {
    ...effective,
    apiKey:
      (override.enabled ? override.apiKey.trim() : "") ||
      (sameVoiceProvider(config.provider, effective.provider)
        ? config.apiKey.trim()
        : ""),
  };
}

export function defaultEmbeddingOverride(
  providerId: LLMEmbeddingProviderId = "qwen",
): LLMEmbeddingOverrideConfig {
  const provider = embeddingProviderInfo(providerId);
  return {
    enabled: true,
    provider: provider.id,
    apiKey: "",
    model: provider.model,
    baseUrl: provider.baseUrl,
    dimensions: EMBEDDING_DIMENSIONS,
  };
}

export function effectiveEmbeddingConfig(
  config: LLMConfig,
): LLMEmbeddingOverrideConfig {
  const override = normalizeEmbeddingOverride(
    config.embeddingOverride ?? defaultEmbeddingOverride(),
  );
  const provider = embeddingProviderInfo(override.enabled ? override.provider : "qwen");
  const defaults = defaultEmbeddingOverride(provider.id);
  const effective = override.enabled
    ? { ...defaults, ...override, provider: provider.id }
    : defaults;
  return {
    ...effective,
    dimensions: EMBEDDING_DIMENSIONS,
    apiKey:
      (override.enabled ? override.apiKey.trim() : "") ||
      (sameEmbeddingProvider(config.provider, effective.provider)
        ? config.apiKey.trim()
        : ""),
  };
}

/**
 * Build the `llm_config` payload to send with session creation requests.
 * Returns `undefined` if no API key is configured (backend will use its own).
 */
export function buildLLMPayload():
  | {
      provider?: string;
      api_key?: string;
      model?: string;
      temperature?: number;
      base_url?: string;
      role_overrides?: Partial<
        Record<
          LLMRoleKey,
          {
            provider?: string;
            api_key?: string;
            model?: string;
            base_url?: string;
          }
        >
      >;
      voice_overrides?: {
        asr?: {
          provider?: LLMVoiceProviderId;
          api_key?: string;
          model?: string;
          base_url?: string;
        };
        tts?: {
          provider?: LLMVoiceProviderId;
          api_key?: string;
          model?: string;
          voice?: string;
          base_url?: string;
        };
      };
      embedding_override?: {
        provider?: LLMEmbeddingProviderId;
        api_key?: string;
        model?: string;
        base_url?: string;
        dimensions?: number;
      };
    }
  | undefined {
  const c = loadLLMConfig();
  const payload: {
    provider?: string;
    api_key?: string;
    model?: string;
    temperature?: number;
    base_url?: string;
    role_overrides?: Partial<
      Record<
        LLMRoleKey,
        {
          provider?: string;
          api_key?: string;
          model?: string;
          base_url?: string;
        }
      >
    >;
    voice_overrides?: {
      asr?: {
        provider?: LLMVoiceProviderId;
        api_key?: string;
        model?: string;
        base_url?: string;
      };
      tts?: {
        provider?: LLMVoiceProviderId;
        api_key?: string;
        model?: string;
        voice?: string;
        base_url?: string;
      };
    };
    embedding_override?: {
      provider?: LLMEmbeddingProviderId;
      api_key?: string;
      model?: string;
      base_url?: string;
      dimensions?: number;
    };
  } = {};
  const defaultApiKey = c.apiKey.trim();
  if (defaultApiKey) {
    payload.provider = c.provider;
    payload.api_key = defaultApiKey;
    if (c.model) payload.model = c.model;
    if (c.temperature !== 0.7) payload.temperature = c.temperature;
    if (c.baseUrl) payload.base_url = c.baseUrl;
  }
  const roleOverrides: Partial<
    Record<
      LLMRoleKey,
      { provider?: string; api_key?: string; model?: string; base_url?: string }
    >
  > = {};
  for (const group of enabledRoleGroups(c)) {
    const override = c.roleOverrides[group.id];
    if (!override?.enabled) continue;
    const effective = effectiveRoleConfig(c, group.id);
    if (!effective.apiKey.trim()) continue;
    const rolePayload = {
      provider: effective.provider,
      ...(override.apiKey.trim() ? { api_key: override.apiKey.trim() } : {}),
      ...(effective.model ? { model: effective.model } : {}),
      ...(effective.baseUrl ? { base_url: effective.baseUrl } : {}),
    };
    for (const role of group.roles) {
      roleOverrides[role] = rolePayload;
    }
  }
  if (Object.keys(roleOverrides).length > 0) {
    payload.role_overrides = roleOverrides;
  }

  const asrVoice = effectiveVoiceConfig(c, "asr");
  const ttsVoice = effectiveVoiceConfig(c, "tts");
  const voiceOverrides: NonNullable<typeof payload.voice_overrides> = {};
  if (asrVoice.apiKey.trim()) {
    voiceOverrides.asr = {
      provider: asrVoice.provider,
      api_key: asrVoice.apiKey.trim(),
      model: asrVoice.model || voiceProviderInfo(asrVoice.provider).asrModel,
      ...(asrVoice.baseUrl.trim() ? { base_url: asrVoice.baseUrl.trim() } : {}),
    };
  }
  if (ttsVoice.apiKey.trim()) {
    voiceOverrides.tts = {
      provider: ttsVoice.provider,
      api_key: ttsVoice.apiKey.trim(),
      model: ttsVoice.model || voiceProviderInfo(ttsVoice.provider).ttsModel,
      voice: ttsVoice.voice || voiceProviderInfo(ttsVoice.provider).ttsVoice,
      ...(ttsVoice.baseUrl.trim() ? { base_url: ttsVoice.baseUrl.trim() } : {}),
    };
  }
  if (voiceOverrides.asr || voiceOverrides.tts) {
    payload.voice_overrides = voiceOverrides;
  }

  const embedding = effectiveEmbeddingConfig(c);
  if (embedding.apiKey.trim()) {
    payload.embedding_override = {
      provider: embedding.provider,
      api_key: embedding.apiKey.trim(),
      model: embedding.model || embeddingProviderInfo(embedding.provider).model,
      dimensions: embedding.dimensions,
      ...(embedding.baseUrl.trim() ? { base_url: embedding.baseUrl.trim() } : {}),
    };
  }

  if (
    !payload.api_key &&
    !payload.role_overrides &&
    !payload.voice_overrides &&
    !payload.embedding_override
  ) {
    return undefined;
  }
  return payload;
}

export interface LLMTestResponse {
  ok: boolean;
  provider: string;
  model: string;
  latency_ms: number;
  message?: string;
  error?: string;
  error_kind?: LLMErrorKind;
}

export interface LLMTestStatus {
  fingerprint: string;
  testedAt: string;
  ok: boolean;
  latencyMs: number;
  errorKind?: LLMErrorKind;
  message?: string;
  error?: string;
  results?: Partial<Record<LLMTestTargetId, LLMTestTargetStatus>>;
}

export type LLMConfigStatus =
  | "missing"
  | "untested"
  | "success"
  | "auth_failed"
  | "quota_exhausted"
  | "rate_limited"
  | "transient"
  | "misconfig"
  | "error";
export type LLMTestTargetId =
  | "default"
  | LLMRoleGroupId
  | `voice:${LLMVoiceRouteId}`
  | "embedding:session_anchor";
export type LLMTestTargetKind = "chat" | "asr" | "tts" | "embedding";

export interface LLMTestTargetStatus {
  fingerprint: string;
  testedAt: string;
  ok: boolean;
  latencyMs: number;
  provider: string;
  model: string;
  label: string;
  kind?: LLMTestTargetKind;
  errorKind?: LLMErrorKind;
  message?: string;
  error?: string;
}

function hashString(value: string): string {
  let h = 2166136261;
  for (let i = 0; i < value.length; i += 1) {
    h ^= value.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return (h >>> 0).toString(16).padStart(8, "0");
}

function inferLLMErrorKindFromText(text: string): LLMErrorKind {
  const blob = text.toLowerCase();
  if (
    [
      "invalid api key",
      "api key invalid",
      "incorrect api key",
      "authentication",
      "unauthorized",
      "forbidden",
      "permission denied",
      "not authorized",
      "401",
      "403",
    ].some((token) => blob.includes(token))
  ) {
    return "auth";
  }
  if (
    ["quota", "insufficient_quota", "billing", "balance", "credit", "credits"].some(
      (token) => blob.includes(token),
    )
  ) {
    return "quota";
  }
  if (
    ["rate limit", "ratelimit", "too many requests", "429"].some((token) =>
      blob.includes(token),
    )
  ) {
    return "rate_limit";
  }
  if (["timeout", "timed out"].some((token) => blob.includes(token))) {
    return "timeout";
  }
  if (
    [
      "network",
      "connection",
      "failed to fetch",
      "fetch",
      "dns",
      "socket",
      "reset by peer",
      "service unavailable",
      "gateway",
      "502",
      "503",
      "504",
    ].some((token) => blob.includes(token))
  ) {
    return "network";
  }
  if (
    [
      "base_url",
      "base url",
      "requires a base_url",
      "unsupported provider",
      "openai package is required",
      "anthropic package is required",
      "malformed",
      "bad request",
    ].some((token) => blob.includes(token))
  ) {
    return "misconfig";
  }
  return "unknown";
}

export function inferLLMErrorKind(error: unknown): LLMErrorKind {
  if (error instanceof ApiError) {
    const body = error.body as
      | {
          error_kind?: unknown;
          errorKind?: unknown;
          detail?: unknown;
        }
      | undefined;
    const bodyDetail =
      body && typeof body === "object" && "detail" in body
        ? (body.detail as
            | { error_kind?: unknown; errorKind?: unknown; error?: unknown }
            | string
            | undefined)
        : undefined;
    const fromBody =
      body && typeof body === "object"
        ? (body.error_kind ??
          body.errorKind ??
          (bodyDetail && typeof bodyDetail === "object"
            ? (bodyDetail.error_kind ?? bodyDetail.errorKind)
            : undefined))
        : undefined;
    if (typeof fromBody === "string") {
      const normalized = fromBody.trim();
      if (
        normalized === "auth" ||
        normalized === "quota" ||
        normalized === "rate_limit" ||
        normalized === "timeout" ||
        normalized === "network" ||
        normalized === "misconfig" ||
        normalized === "unknown"
      ) {
        return normalized;
      }
    }
    if (error.status === 401 || error.status === 403) return "auth";
    if (error.status === 429) return "rate_limit";
    if (error.status === 408 || error.status === 504) return "timeout";
    if (error.status === 422) return "misconfig";
    if (error.status >= 500) return "network";
    const detail =
      body && typeof body === "object" && typeof body.detail === "string"
        ? body.detail
        : bodyDetail &&
            typeof bodyDetail === "object" &&
            typeof bodyDetail.error === "string"
          ? bodyDetail.error
        : error.message;
    return inferLLMErrorKindFromText(detail);
  }
  if (error instanceof Error) {
    return inferLLMErrorKindFromText(`${error.name}: ${error.message}`);
  }
  return inferLLMErrorKindFromText(String(error));
}

export function llmConfigStatusFromErrorKind(
  kind: LLMErrorKind | null | undefined,
): LLMConfigStatus {
  switch (kind) {
    case "auth":
      return "auth_failed";
    case "quota":
      return "quota_exhausted";
    case "rate_limit":
      return "rate_limited";
    case "timeout":
    case "network":
      return "transient";
    case "misconfig":
      return "misconfig";
    case "unknown":
    case undefined:
    case null:
      return "error";
    default:
      return "error";
  }
}

export function llmErrorKindLabel(kind: LLMErrorKind | null | undefined): string {
  switch (kind) {
    case "auth":
      return "密钥失效或无权限";
    case "quota":
      return "额度不足或余额耗尽";
    case "rate_limit":
      return "请求太频繁";
    case "timeout":
      return "请求超时";
    case "network":
      return "网络或服务暂时不可用";
    case "misconfig":
      return "模型或 Base URL 配置有误";
    default:
      return "未知错误";
  }
}

export function configFingerprint(config: LLMConfig = loadLLMConfig()): string {
  return [
    config.provider,
    config.model.trim(),
    String(config.temperature),
    config.baseUrl.trim(),
    hashString(config.apiKey.trim()),
    ...LLM_ROLE_GROUPS.flatMap((group) => {
      const override = config.roleOverrides[group.id];
      if (!override?.enabled) return [`${group.id}:off`];
      return [
        `${group.id}:on`,
        override.provider,
        override.model.trim(),
        override.baseUrl.trim(),
        hashString(override.apiKey.trim()),
      ];
    }),
    ...(["asr", "tts"] as const).flatMap((routeId) => {
      const voice = config.voiceOverrides[routeId] ?? defaultVoiceOverride(routeId);
      return [
        `voice:${routeId}`,
        String(Boolean(voice.enabled)),
        voice.provider,
        voice.model.trim(),
        voice.baseUrl.trim(),
        voice.voice?.trim() ?? "",
        hashString(voice.apiKey.trim()),
      ];
    }),
    "embedding:session_anchor",
    String(Boolean(config.embeddingOverride?.enabled)),
    config.embeddingOverride?.provider ?? "qwen",
    config.embeddingOverride?.model?.trim() ?? "",
    config.embeddingOverride?.baseUrl?.trim() ?? "",
    String(EMBEDDING_DIMENSIONS),
    hashString(config.embeddingOverride?.apiKey?.trim() ?? ""),
  ].join("|");
}

export function targetFingerprint(
  config: LLMConfig,
  targetId: LLMTestTargetId,
): string {
  if (targetId === "voice:asr" || targetId === "voice:tts") {
    const routeId = targetId === "voice:asr" ? "asr" : "tts";
    const voice = effectiveVoiceConfig(config, routeId);
    return [
      targetId,
      voice.provider,
      voice.model.trim(),
      voice.baseUrl.trim(),
      voice.voice?.trim() ?? "",
      hashString(voice.apiKey.trim()),
    ].join("|");
  }
  if (targetId === "embedding:session_anchor") {
    const embedding = effectiveEmbeddingConfig(config);
    return [
      targetId,
      embedding.provider,
      embedding.model.trim(),
      embedding.baseUrl.trim(),
      String(embedding.dimensions),
      hashString(embedding.apiKey.trim()),
    ].join("|");
  }
  const targetConfig =
    targetId === "default" ? config : effectiveRoleConfig(config, targetId);
  return [
    targetId,
    targetConfig.provider,
    targetConfig.model.trim(),
    targetConfig.baseUrl.trim(),
    hashString(targetConfig.apiKey.trim()),
  ].join("|");
}

export function loadLLMTestStatus(): LLMTestStatus | null {
  try {
    const raw = window.localStorage.getItem(TEST_STATUS_KEY);
    return raw ? (JSON.parse(raw) as LLMTestStatus) : null;
  } catch {
    return null;
  }
}

export function saveLLMTestStatus(status: LLMTestStatus): void {
  try {
    window.localStorage.setItem(TEST_STATUS_KEY, JSON.stringify(status));
  } catch {
    /* localStorage may be unavailable */
  }
  emitConfigEvent();
}

function resultErrorKind(result?: LLMTestTargetStatus): LLMErrorKind | null {
  if (!result) return null;
  if (result.errorKind) return result.errorKind;
  if (result.ok) return null;
  if (result.error) return inferLLMErrorKindFromText(result.error);
  return "unknown";
}

function statusErrorKind(status: LLMTestStatus | null): LLMErrorKind | null {
  if (!status) return null;
  if (status.errorKind) return status.errorKind;
  const results = status.results ? Object.values(status.results) : [];
  for (const result of results) {
    const kind = resultErrorKind(result);
    if (kind) return kind;
  }
  if (status.error) return inferLLMErrorKindFromText(status.error);
  if (status.message) return inferLLMErrorKindFromText(status.message);
  return null;
}

export function getLLMConfigStatus(
  config: LLMConfig = loadLLMConfig(),
  status: LLMTestStatus | null = loadLLMTestStatus(),
): LLMConfigStatus {
  const targets = testTargets(config);
  if (targets.length === 0) return "missing";
  if (!status || status.fingerprint !== configFingerprint(config) || !status.results) {
    return "untested";
  }
  const results = targets.map((target) => status.results?.[target.id]);
  if (
    results.some(
      (result, index) =>
        !result || result.fingerprint !== targetFingerprint(config, targets[index].id),
    )
  ) {
    return "untested";
  }
  if (results.every((result) => result?.ok)) return "success";
  const kind = statusErrorKind(status) ?? "unknown";
  return llmConfigStatusFromErrorKind(kind);
}

export function testTargets(
  config: LLMConfig = loadLLMConfig(),
): Array<{
  id: LLMTestTargetId;
  label: string;
  kind: LLMTestTargetKind;
  config?: LLMConfig;
  voice?: LLMVoiceOverrideConfig;
  embedding?: LLMEmbeddingOverrideConfig;
}> {
  const targets: Array<{
    id: LLMTestTargetId;
    label: string;
    kind: LLMTestTargetKind;
    config?: LLMConfig;
    voice?: LLMVoiceOverrideConfig;
    embedding?: LLMEmbeddingOverrideConfig;
  }> = [];
  if (config.apiKey.trim()) {
    targets.push({ id: "default", label: "默认配置", kind: "chat", config });
  }
  targets.push(
    ...enabledRoleGroups(config)
      .map((group) => ({
        id: group.id,
        label: group.label,
        kind: "chat" as const,
        config: effectiveRoleConfig(config, group.id),
      }))
      .filter((target) => target.config.apiKey.trim().length > 0),
  );
  const asrVoice = effectiveVoiceConfig(config, "asr");
  if (asrVoice.apiKey.trim()) {
    targets.push({
      id: "voice:asr",
      label: "语音识别",
      kind: "asr",
      voice: asrVoice,
    });
  }
  const ttsVoice = effectiveVoiceConfig(config, "tts");
  if (ttsVoice.apiKey.trim()) {
    targets.push({
      id: "voice:tts",
      label: "语音合成",
      kind: "tts",
      voice: ttsVoice,
    });
  }
  const embedding = effectiveEmbeddingConfig(config);
  if (embedding.apiKey.trim()) {
    targets.push({
      id: "embedding:session_anchor",
      label: "资料理解能力",
      kind: "embedding",
      embedding,
    });
  }
  return targets;
}

function saveTargetTestStatus(
  config: LLMConfig,
  targetId: LLMTestTargetId,
  targetStatus: LLMTestTargetStatus,
): LLMTestStatus {
  const previous = loadLLMTestStatus();
  const results =
    previous?.fingerprint === configFingerprint(config) && previous.results
      ? { ...previous.results }
      : {};
  results[targetId] = targetStatus;
  const requiredTargets = testTargets(config);
  const requiredResults = requiredTargets.map((item) => results[item.id]);
  const allCurrent = requiredResults.every(
    (item, index) =>
      item && item.fingerprint === targetFingerprint(config, requiredTargets[index].id),
  );
  const aggregatedErrorKind =
    allCurrent && requiredResults.some((item) => !item?.ok)
      ? (requiredResults.map((item) => resultErrorKind(item)).find(Boolean) ?? "unknown")
      : null;
  const status: LLMTestStatus = {
    fingerprint: configFingerprint(config),
    testedAt: targetStatus.testedAt,
    ok: allCurrent && requiredResults.every((item) => item?.ok),
    latencyMs: targetStatus.latencyMs,
    errorKind: aggregatedErrorKind ?? undefined,
    message: targetStatus.message,
    error: targetStatus.error,
    results,
  };
  saveLLMTestStatus(status);
  return status;
}

export async function testConnection(
  config: LLMConfig = loadLLMConfig(),
  targetId: LLMTestTargetId = "default",
): Promise<LLMTestTargetStatus> {
  const target = testTargets(config).find((item) => item.id === targetId);
  if (!target) {
    throw new Error("测试目标不存在，请检查按环节配置。");
  }
  const trimmed: LLMConfig | null = target.config
    ? {
        ...target.config,
        apiKey: target.config.apiKey.trim(),
        model: target.config.model.trim(),
        baseUrl: target.config.baseUrl.trim(),
      }
    : null;
  const trimmedVoice = target.voice
    ? {
        ...target.voice,
        apiKey: target.voice.apiKey.trim(),
        model: target.voice.model.trim(),
        baseUrl: target.voice.baseUrl.trim(),
        voice: target.voice.voice?.trim(),
      }
    : null;
  const trimmedEmbedding = target.embedding
    ? {
        ...target.embedding,
        apiKey: target.embedding.apiKey.trim(),
        model: target.embedding.model.trim(),
        baseUrl: target.embedding.baseUrl.trim(),
        dimensions: EMBEDDING_DIMENSIONS,
      }
    : null;
  let targetStatus: LLMTestTargetStatus;
  try {
    const result = await request<LLMTestResponse>("/api/v1/llm/test", {
      method: "POST",
      body:
        target.kind === "chat" && trimmed
          ? {
              kind: target.kind,
              provider: trimmed.provider,
              api_key: trimmed.apiKey,
              model: trimmed.model,
              temperature: trimmed.temperature,
              ...(trimmed.baseUrl ? { base_url: trimmed.baseUrl } : {}),
            }
          : target.kind === "embedding" && trimmedEmbedding
            ? {
                kind: target.kind,
                provider: trimmedEmbedding.provider,
                api_key: trimmedEmbedding.apiKey,
                model: trimmedEmbedding.model,
                dimensions: trimmedEmbedding.dimensions,
                ...(trimmedEmbedding.baseUrl
                  ? { base_url: trimmedEmbedding.baseUrl }
                  : {}),
              }
          : {
              kind: target.kind,
              provider: trimmedVoice?.provider,
              api_key: trimmedVoice?.apiKey,
              model: trimmedVoice?.model,
              ...(target.kind === "tts" && trimmedVoice?.voice
                ? { voice: trimmedVoice.voice }
                : {}),
              ...(trimmedVoice?.baseUrl ? { base_url: trimmedVoice.baseUrl } : {}),
            },
      timeoutMs: 20_000,
    });
    targetStatus = {
      fingerprint: targetFingerprint(config, targetId),
      testedAt: new Date().toISOString(),
      ok: result.ok,
      latencyMs: result.latency_ms,
      provider: result.provider,
      model: result.model,
      label: target.label,
      kind: target.kind,
      errorKind:
        result.error_kind ??
        (!result.ok && result.error ? inferLLMErrorKindFromText(result.error) : undefined),
      message: result.message,
      error: result.error,
    };
  } catch (err) {
    targetStatus = {
      fingerprint: targetFingerprint(config, targetId),
      testedAt: new Date().toISOString(),
      ok: false,
      latencyMs: 0,
      provider:
        trimmed?.provider ?? trimmedVoice?.provider ?? trimmedEmbedding?.provider ?? "",
      model: trimmed?.model ?? trimmedVoice?.model ?? trimmedEmbedding?.model ?? "",
      label: target.label,
      kind: target.kind,
      errorKind: inferLLMErrorKind(err),
      error:
        err instanceof Error ? err.message : typeof err === "string" ? err : String(err),
    };
  }
  saveTargetTestStatus(config, targetId, targetStatus);
  return targetStatus;
}

export async function testAllConnections(
  config: LLMConfig = loadLLMConfig(),
): Promise<LLMTestStatus> {
  let latest: LLMTestStatus | null = null;
  const targets = testTargets(config);
  for (const target of targets) {
    try {
      await testConnection(config, target.id);
    } catch (err) {
      const now = new Date().toISOString();
      latest = saveTargetTestStatus(config, target.id, {
        fingerprint: targetFingerprint(config, target.id),
        testedAt: now,
        ok: false,
        latencyMs: 0,
        provider:
          target.config?.provider ??
          target.voice?.provider ??
          target.embedding?.provider ??
          "",
        model: target.config?.model ?? target.voice?.model ?? target.embedding?.model ?? "",
        label: target.label,
        kind: target.kind,
        errorKind: inferLLMErrorKind(err),
        error: err instanceof Error ? err.message : String(err),
      });
      continue;
    }
    latest = loadLLMTestStatus();
  }
  return (
    latest ?? {
      fingerprint: configFingerprint(config),
      testedAt: new Date().toISOString(),
      ok: false,
      latencyMs: 0,
      error: "没有可测试的个人 API 配置；不填写时会使用系统默认练习模式。",
      results: {},
    }
  );
}
