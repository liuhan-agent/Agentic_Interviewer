"use client";

import { useEffect, useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  ChevronDown,
  Eye,
  EyeOff,
  Info,
  Key,
  Loader2,
  Route,
  Save,
  Sparkles,
  X,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useToast } from "@/lib/hooks/useToast";
import { cn } from "@/lib/utils";
import type {
  LLMConfig,
  LLMConfigStatus,
  LLMEmbeddingOverrideConfig,
  LLMRoleGroupId,
  LLMRoleGroupInfo,
  LLMRoleOverrideConfig,
  LLMTestStatus,
  LLMTestTargetKind,
  LLMTestTargetStatus,
  LLMVoiceOverrideConfig,
  LLMVoiceRouteId,
} from "@/lib/llm-config";
import {
  defaultEmbeddingOverride,
  defaultVoiceOverride,
  effectiveEmbeddingConfig,
  effectiveRoleConfig,
  effectiveVoiceConfig,
  EMBEDDING_DIMENSIONS,
  embeddingProviderInfo,
  configFingerprint,
  getLLMConfigStatus,
  LLM_ROLE_GROUPS,
  llmErrorKindLabel,
  loadLLMConfig,
  loadLLMTestStatus,
  providerInfo,
  providerRequiresBaseUrl,
  providerShowsBaseUrl,
  PROVIDERS,
  recommendedRoleOverride,
  saveLLMConfig,
  testAllConnections,
  testTargets,
  voiceProviderInfo,
  VOICE_PROVIDERS,
} from "@/lib/llm-config";

const selectClass =
  "h-9 w-full rounded-md border border-input bg-background px-3 text-sm text-foreground shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring";

const ROUTE_SUMMARY_LABELS: Record<LLMRoleGroupId, string> = {
  resume_parsing: "简历解析",
  questioning: "出题追问",
  evaluation: "回答评分",
  verification: "复核检查",
  coaching: "反馈计划",
  safety: "安全检查",
};

const VOICE_ROUTE_LABELS: Record<LLMVoiceRouteId, string> = {
  asr: "语音识别",
  tts: "语音合成",
};

const CUSTOM_VOICE_VALUE = "__custom_voice__";

function routeProviderLabel(provider: string, kind?: LLMTestTargetKind): string {
  if (kind === "asr" || kind === "tts") {
    return voiceProviderInfo(provider).label;
  }
  if (kind === "embedding") {
    return embeddingProviderInfo(provider).label;
  }
  return providerInfo(provider).label;
}

function isTestable(config: LLMConfig): boolean {
  return (
    config.apiKey.trim().length > 0 &&
    config.model.trim().length > 0 &&
    (!providerRequiresBaseUrl(config.provider) || config.baseUrl.trim().length > 0)
  );
}

function isTestTargetReady(target: ReturnType<typeof testTargets>[number]): boolean {
  if (target.kind === "chat") {
    return Boolean(target.config && isTestable(target.config));
  }
  if (target.kind === "embedding") {
    const embedding = target.embedding;
    return Boolean(
      embedding?.apiKey.trim() &&
        embedding.model.trim() &&
        embedding.dimensions === EMBEDDING_DIMENSIONS &&
        (embeddingProviderInfo(embedding.provider).baseUrlMode !== "required" ||
          embedding.baseUrl.trim()),
    );
  }
  const voice = target.voice;
  return Boolean(voice?.apiKey.trim() && voice.model.trim());
}

type LLMValidation = {
  defaultErrors: {
    model?: string;
    baseUrl?: string;
  };
  canTestMessage: string | null;
  saveMessage: string | null;
};

function validateLLMConfig(config: LLMConfig): LLMValidation {
  const defaultErrors: LLMValidation["defaultErrors"] = {};
  const defaultHasKey = config.apiKey.trim().length > 0;
  if (defaultHasKey && !config.model.trim()) {
    defaultErrors.model = "填写 API Key 后需要填写模型名称。";
  }
  if (
    defaultHasKey &&
    providerRequiresBaseUrl(config.provider) &&
    !config.baseUrl.trim()
  ) {
    defaultErrors.baseUrl = "该服务商需要 Base URL。";
  }

  let roleIssue: string | null = null;
  for (const group of LLM_ROLE_GROUPS) {
    const override = config.roleOverrides[group.id];
    if (!override?.enabled) continue;
    const effective = effectiveRoleConfig(config, group.id);
    if (!effective.apiKey.trim()) continue;
    if (!effective.model.trim()) {
      roleIssue = `${group.label} 已填写 Key，但缺少模型名称。`;
      break;
    }
    if (providerRequiresBaseUrl(effective.provider) && !effective.baseUrl.trim()) {
      roleIssue = `${group.label} 使用的服务商需要 Base URL。`;
      break;
    }
  }

  let embeddingIssue: string | null = null;
  const embedding = effectiveEmbeddingConfig(config);
  if (embedding.apiKey.trim()) {
    if (!embedding.model.trim()) {
      embeddingIssue = "资料理解能力已填写 Key，但缺少模型名称。";
    } else if (embedding.dimensions !== EMBEDDING_DIMENSIONS) {
      embeddingIssue = `资料理解能力维度必须是 ${EMBEDDING_DIMENSIONS}。`;
    } else if (
      embeddingProviderInfo(embedding.provider).baseUrlMode === "required" &&
      !embedding.baseUrl.trim()
    ) {
      embeddingIssue = "资料理解能力使用的服务商需要 Base URL。";
    }
  }

  const saveMessage =
    defaultErrors.model ?? defaultErrors.baseUrl ?? roleIssue ?? embeddingIssue ?? null;
  const targets = testTargets(config);
  let canTestMessage: string | null = null;
  if (targets.length === 0) {
    canTestMessage = "填写 API Key 后才能测试连接；不填写时会使用系统默认练习模式。";
  } else if (saveMessage) {
    canTestMessage = saveMessage;
  } else if (!targets.every(isTestTargetReady)) {
    canTestMessage = "还有启用的模型配置缺少 Key、模型或 Base URL。";
  }

  return { defaultErrors, canTestMessage, saveMessage };
}

function modelRouteSummary(config: LLMConfig) {
  return LLM_ROLE_GROUPS.map((group) => {
    const override = config.roleOverrides[group.id];
    const effective = effectiveRoleConfig(config, group.id);
    const provider = providerInfo(effective.provider);
    return {
      id: group.id,
      label: ROUTE_SUMMARY_LABELS[group.id] ?? group.label,
      providerLabel: provider.label,
      model: effective.model || provider.defaultModel || "未填写模型",
      source: override?.enabled ? "单独配置" : "默认配置",
    };
  });
}

export function LLMSettingsDialog({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const [config, setConfig] = useState<LLMConfig>(loadLLMConfig);
  const [showKey, setShowKey] = useState(false);
  const [testStatus, setTestStatus] = useState<LLMTestStatus | null>(
    loadLLMTestStatus,
  );
  const [testing, setTesting] = useState(false);
  const [testError, setTestError] = useState<string | null>(null);
  const [visibleResultFingerprint, setVisibleResultFingerprint] = useState<string | null>(
    null,
  );
  const [resultDismissed, setResultDismissed] = useState(false);
  const { toast } = useToast();

  useEffect(() => {
    if (open) {
      setConfig(loadLLMConfig());
      setTestStatus(loadLLMTestStatus());
      setTestError(null);
      setVisibleResultFingerprint(null);
      setResultDismissed(false);
    }
  }, [open]);

  function handleSave() {
    const validation = validateLLMConfig(config);
    if (validation.saveMessage) {
      setTestError(validation.saveMessage);
      setResultDismissed(false);
      return;
    }
    saveLLMConfig(config);
    setOpen(false);
  }

  async function handleTest() {
    setTesting(true);
    setTestError(null);
    setVisibleResultFingerprint(null);
    setResultDismissed(false);
    try {
      const status = await testAllConnections(config);
      setTestStatus(status);
      setVisibleResultFingerprint(configFingerprint(config));
      const nextKind = getLLMConfigStatus(config, status);
      toast({
        title: status.ok ? "连接测试通过" : "连接测试未通过",
        description: status.ok
          ? "已填写的配置可以正常调用。"
          : connectionStatusMessage(nextKind),
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setTestError(message);
      toast({
        title: "连接测试未通过",
        description: message,
      });
    } finally {
      setTesting(false);
    }
  }

  function updateRoleOverride(
    groupId: LLMRoleGroupId,
    patch: Partial<LLMRoleOverrideConfig>,
  ) {
    setConfig((prev) => {
      const current = prev.roleOverrides[groupId] ?? {
        ...recommendedRoleOverride(groupId),
        enabled: false,
      };
      return {
        ...prev,
        roleOverrides: {
          ...prev.roleOverrides,
          [groupId]: { ...current, ...patch },
        },
      };
    });
    setTestError(null);
  }

  function updateVoiceOverride(
    routeId: LLMVoiceRouteId,
    patch: Partial<LLMVoiceOverrideConfig>,
  ) {
    setConfig((prev) => {
      const current = prev.voiceOverrides[routeId] ?? defaultVoiceOverride(routeId);
      return {
        ...prev,
        voiceOverrides: {
          ...prev.voiceOverrides,
          [routeId]: { ...current, ...patch },
        },
      };
    });
    setTestError(null);
  }

  function updateEmbeddingOverride(patch: Partial<LLMEmbeddingOverrideConfig>) {
    setConfig((prev) => ({
      ...prev,
      embeddingOverride: {
        ...(prev.embeddingOverride ?? defaultEmbeddingOverride()),
        ...patch,
        dimensions: EMBEDDING_DIMENSIONS,
      },
    }));
    setTestError(null);
  }

  const currentProvider = providerInfo(config.provider);
  const showBaseUrl = providerShowsBaseUrl(config.provider);
  const needsBaseUrl = providerRequiresBaseUrl(config.provider);
  const statusKind = getLLMConfigStatus(config, testStatus);
  const targets = testTargets(config);
  const validation = validateLLMConfig(config);
  const canTest =
    targets.length > 0 &&
    targets.every(isTestTargetReady) &&
    !validation.canTestMessage &&
    !testing;
  const showConnectionResult =
    !resultDismissed &&
    (targets.length === 0 || visibleResultFingerprint === configFingerprint(config));

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>{children}</DialogTrigger>
      <DialogContent className="max-h-[calc(100vh-2rem)] overflow-y-auto sm:max-w-[720px]">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Key className="h-4 w-4 text-emerald-400" />
            LLM 配置
          </DialogTitle>
          <DialogDescription>
            配置你的 API Key，以便 AI 面试官可以代你调用 LLM。
            默认会保留到本浏览器会话结束（关闭浏览器自动清空）；选择本机长期保存后，密钥会留在这台设备上。
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-4 py-2">
          <section className="grid gap-4 rounded-md border bg-secondary/20 p-4">
            <div>
              <h3 className="text-sm font-medium">默认配置（可选）</h3>
              <p className="mt-1 text-xs text-muted-foreground">
                填这里会作为本场面试的统一模型；不填时会使用系统默认练习模式。
              </p>
            </div>

            <div className="space-y-1.5">
              <Label>服务商</Label>
              <select
                value={config.provider}
                onChange={(e) => {
                  const p = PROVIDERS.find((x) => x.id === e.target.value);
                  setConfig({
                    ...config,
                    provider: e.target.value,
                    model: p?.defaultModel ?? "",
                    baseUrl: p?.defaultBaseUrl ?? "",
                  });
                  setTestError(null);
                }}
                className={selectClass}
              >
                {PROVIDERS.map((p) => (
                  <option
                    key={p.id}
                    value={p.id}
                    className="bg-background text-foreground"
                  >
                    {p.label}
                  </option>
                ))}
              </select>
            </div>

            <div className="space-y-1.5">
              <Label>API 密钥</Label>
              <div className="relative">
                <Input
                  type={showKey ? "text" : "password"}
                  placeholder={currentProvider.keyPlaceholder}
                  value={config.apiKey}
                  onChange={(e) =>
                    setConfig({ ...config, apiKey: e.target.value })
                  }
                  className="pr-10"
                />
                <button
                  type="button"
                  onClick={() => setShowKey(!showKey)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                >
                  {showKey ? (
                    <EyeOff className="h-4 w-4" />
                  ) : (
                    <Eye className="h-4 w-4" />
                  )}
                </button>
              </div>
              <p className="text-[11px] text-muted-foreground">
                开始面试和测试连接时，密钥会临时发送给后端使用，不会写入服务器数据库。
              </p>
              <details className="group rounded-md border border-border/50 bg-secondary/10 px-3 py-2 text-[11px]">
                <summary className="flex cursor-pointer list-none items-center justify-between gap-2 text-muted-foreground hover:text-foreground">
                  <span className="flex items-center gap-1.5">
                    <Info className="h-3.5 w-3.5" />
                    Key 在系统里怎么被保管？
                  </span>
                  <ChevronDown className="h-3.5 w-3.5 transition-transform group-open:rotate-180" />
                </summary>
                <ul className="mt-2 list-disc space-y-1.5 pl-4 text-muted-foreground">
                  <li>
                    <strong className="text-foreground">传输：</strong>
                    通过 HTTPS 发到后端；后端代你调用 LLM 服务商，前端不直连。
                  </li>
                  <li>
                    <strong className="text-foreground">服务器内存：</strong>
                    仅在本次请求处理期间放入会话级上下文，请求结束立刻释放。
                  </li>
                  <li>
                    <strong className="text-foreground">数据库：</strong>
                    不存 Key 真值，只保留服务商 / 模型 / Base URL 这些元信息。
                  </li>
                  <li>
                    <strong className="text-foreground">错误日志：</strong>
                    LLM 报错文本里如果出现 Key 原文，会自动替换为占位符再写入。
                  </li>
                  <li>
                    <strong className="text-foreground">本地浏览器：</strong>
                    默认仅保留到当前浏览器会话（刷新不丢，关闭浏览器自动清空）；公共设备请选择「不保存」。选择「本机长期保存」后，密钥会留在这台设备上。
                  </li>
                </ul>
                <p className="mt-2 text-muted-foreground">
                  建议为 AI 面试官单独申请一把额度受限的 Key，并在不再使用时去服务商后台撤销。
                </p>
              </details>
            </div>

            <div className="space-y-1.5">
              <Label>模型</Label>
              <Input
                placeholder={currentProvider.defaultModel || "model-id"}
                value={config.model}
                onChange={(e) =>
                  setConfig({ ...config, model: e.target.value })
                }
                aria-invalid={Boolean(validation.defaultErrors.model)}
                aria-describedby={
                  validation.defaultErrors.model ? "llm-default-model-error" : undefined
                }
              />
              {validation.defaultErrors.model && (
                <p id="llm-default-model-error" className="text-[11px] text-destructive">
                  {validation.defaultErrors.model}
                </p>
              )}
            </div>

            {showBaseUrl && (
              <div className="space-y-1.5">
                <Label>
                  Base URL（基础地址）
                  {needsBaseUrl && <span className="text-destructive"> *</span>}
                </Label>
                <Input
                  placeholder={
                    currentProvider.defaultBaseUrl || "https://example.com/v1"
                  }
                  value={config.baseUrl}
                  onChange={(e) =>
                    setConfig({ ...config, baseUrl: e.target.value })
                  }
                  aria-invalid={Boolean(validation.defaultErrors.baseUrl)}
                  aria-describedby={
                    validation.defaultErrors.baseUrl
                      ? "llm-default-base-url-error"
                      : undefined
                  }
                />
                {validation.defaultErrors.baseUrl && (
                  <p id="llm-default-base-url-error" className="text-[11px] text-destructive">
                    {validation.defaultErrors.baseUrl}
                  </p>
                )}
              </div>
            )}
          </section>

          <ModelRouteSummary config={config} />

          <ModelStrategyHint />

          <details className="group rounded-md border bg-background/40 p-4">
            <summary className="flex cursor-pointer list-none items-center justify-between gap-3 text-sm font-medium">
              <span>语音能力</span>
              <ChevronDown className="h-4 w-4 text-muted-foreground transition-transform group-open:rotate-180" />
            </summary>
            <p className="mt-2 text-xs text-muted-foreground">
              默认使用 Qwen 语音能力；也可以显式切换 OpenAI。语音 Key 只会继承同厂商的默认 Key。
            </p>
            <div className="mt-4 grid gap-3">
              <VoiceRouteCard
                routeId="asr"
                config={config}
                onChange={updateVoiceOverride}
              />
              <VoiceRouteCard
                routeId="tts"
                config={config}
                onChange={updateVoiceOverride}
              />
            </div>
          </details>

          <details className="group rounded-md border bg-background/40 p-4">
            <summary className="flex cursor-pointer list-none items-center justify-between gap-3 text-sm font-medium">
              <span>资料理解能力</span>
              <ChevronDown className="h-4 w-4 text-muted-foreground transition-transform group-open:rotate-180" />
            </summary>
            <p className="mt-2 text-xs text-muted-foreground">
              帮面试官理解简历和自我介绍里的经历线索，推荐使用 Qwen；未单独配置时会使用服务器端默认资料理解配置。
            </p>
            <div className="mt-4">
              <EmbeddingRouteCard
                config={config}
                onChange={updateEmbeddingOverride}
              />
            </div>
          </details>

          <details className="group rounded-md border bg-background/40 p-4">
            <summary className="flex cursor-pointer list-none items-center justify-between gap-3 text-sm font-medium">
              <span>高级：按简历与面试环节配置模型</span>
              <ChevronDown className="h-4 w-4 text-muted-foreground transition-transform group-open:rotate-180" />
            </summary>
            <p className="mt-2 text-xs text-muted-foreground">
              这些配置都可以不填。启用某个环节后，如果 API Key 留空，会优先沿用默认配置里的 Key；默认 Key 也为空时，该环节会回到系统默认配置。
            </p>
            <div className="mt-4 grid gap-3">
              {LLM_ROLE_GROUPS.map((group) => (
                <RoleGroupCard
                  key={group.id}
                  group={group}
                  config={config}
                  onChange={updateRoleOverride}
                />
              ))}
            </div>
          </details>

          <ConnectionResult
            config={config}
            statusKind={statusKind}
            status={showConnectionResult ? testStatus : null}
            error={testError}
            visible={showConnectionResult}
            onDismiss={() => setResultDismissed(true)}
          />
        </div>

        <DialogFooter className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div className="flex flex-col gap-1.5 text-xs text-muted-foreground">
            <div className="flex items-center gap-2">
              <Label className="text-foreground">凭证存储策略</Label>
              <select
                value={config.storageMode ?? "session"}
                onChange={(e) =>
                  setConfig({ ...config, storageMode: e.target.value as "local" | "session" | "memory" })
                }
                className="h-7 rounded-md border border-input bg-background px-2 text-xs text-foreground shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              >
                <option value="session">会话保留（默认：刷新不丢，关闭浏览器自动清空）</option>
                <option value="memory">不保存（刷新页面也会丢）</option>
                <option value="local">本机长期保存（公共设备勿选）</option>
              </select>
            </div>
            <span className="text-[10px] text-muted-foreground/70">
              混淆不是加密：公共设备请选择不保存，本机长期保存只适合自用设备。
            </span>
          </div>
          <div className="flex items-center justify-end gap-2 sm:gap-0">
            <Button variant="ghost" onClick={() => setOpen(false)}>
              取消
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={handleTest}
              disabled={!canTest}
              aria-label={
                !canTest && validation.canTestMessage
                  ? validation.canTestMessage
                  : "测试 API 配置"
              }
              className="gap-2"
            >
              {testing ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Key className="h-4 w-4" />
              )}
              测试
            </Button>
            {!canTest && validation.canTestMessage && (
              <span className="max-w-[220px] px-2 text-[11px] text-muted-foreground">
                {validation.canTestMessage}
              </span>
            )}
            <Button
              onClick={handleSave}
              className="gap-2 bg-emerald-600 text-white hover:bg-emerald-500"
            >
              <Save className="h-4 w-4" />
              保存
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ModelRouteSummary({ config }: { config: LLMConfig }) {
  const defaultProvider = providerInfo(config.provider);
  const defaultModel = config.model || defaultProvider.defaultModel || "未填写模型";
  const routes = [
    ...modelRouteSummary(config),
    ...(["asr", "tts"] as const).map((routeId) => {
      const configured = config.voiceOverrides[routeId];
      const effective = effectiveVoiceConfig(config, routeId);
      const provider = voiceProviderInfo(effective.provider);
      return {
        id: `voice-${routeId}`,
        label: VOICE_ROUTE_LABELS[routeId],
        providerLabel: provider.label,
        model:
          routeId === "tts"
            ? `${effective.model || provider.ttsModel} / ${effective.voice || provider.ttsVoice}`
            : effective.model || provider.asrModel,
        source: configured?.enabled ? "单独配置" : "默认配置",
      };
    }),
    (() => {
      const configured = config.embeddingOverride;
      const effective = effectiveEmbeddingConfig(config);
      const provider = embeddingProviderInfo(effective.provider);
      return {
        id: "embedding-session-anchor",
        label: "资料理解能力",
        providerLabel: provider.label,
        model: effective.model || provider.model,
        source: configured?.enabled ? "单独配置" : "默认配置",
      };
    })(),
  ];
  return (
    <section className="rounded-md border bg-background/40 p-4">
      <div className="flex items-start gap-2">
        <Route className="mt-0.5 h-4 w-4 text-emerald-300" />
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-medium">本场实际模型路由</h3>
          <p className="mt-1 text-xs text-muted-foreground">
            保存后，新面试会按这个路由发起请求；已创建的面试不会自动改配置。
          </p>
        </div>
      </div>
      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        {routes.map((route) => (
          <div
            key={route.id}
            className="flex min-w-0 items-center justify-between gap-3 rounded-md border border-border/70 px-3 py-2"
          >
            <div className="min-w-0">
              <div className="text-xs font-medium text-foreground">{route.label}</div>
              <div className="mt-0.5 truncate text-[11px] text-muted-foreground">
                {route.providerLabel} {route.model}
              </div>
            </div>
            <span
              className={cn(
                "shrink-0 rounded border px-1.5 py-0.5 text-[10px]",
                route.source === "单独配置"
                  ? "border-emerald-400/30 bg-emerald-400/10 text-emerald-200"
                  : "border-border text-muted-foreground",
              )}
            >
              {route.source}
            </span>
          </div>
        ))}
        <div className="flex min-w-0 items-center justify-between gap-3 rounded-md border border-dashed border-border/60 bg-secondary/10 px-3 py-2 text-muted-foreground sm:col-span-2">
          <div className="min-w-0">
            <div className="text-xs font-medium text-foreground/80">其它 LLM 调用</div>
            <div className="mt-0.5 truncate text-[11px]">
              {defaultProvider.label} {defaultModel}
            </div>
            <p className="mt-1 text-[10px] leading-relaxed text-muted-foreground/80">
              没有单独列出的常规调用和后续新增调用，会继承上面的默认配置。
            </p>
          </div>
          <span className="shrink-0 rounded border border-border/70 px-1.5 py-0.5 text-[10px] text-muted-foreground">
            使用默认配置
          </span>
        </div>
      </div>
      <details className="group mt-3 rounded-md border border-border/50 bg-background/30 px-3 py-2 text-xs text-muted-foreground">
        <summary className="flex cursor-pointer list-none items-center justify-between gap-3">
          <span>高级明细</span>
          <ChevronDown className="h-3.5 w-3.5 transition-transform group-open:rotate-180" />
        </summary>
        <div className="mt-2 grid gap-1.5 text-[11px]">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="font-mono text-foreground/80">strategy_dream</span>
            <span>策略整理；实验开关关闭时不会产生额外 LLM 调用。</span>
          </div>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="font-mono text-foreground/80">question_reranker</span>
            <span>题目影子重排；实验开关关闭时不会产生额外 LLM 调用。</span>
          </div>
        </div>
      </details>
    </section>
  );
}

function ModelStrategyHint() {
  return (
    <div className="rounded-md border border-emerald-400/20 bg-emerald-400/10 p-3 text-xs text-muted-foreground">
      <div className="mb-1.5 flex items-center gap-2 font-medium text-foreground">
        <Info className="h-3.5 w-3.5 text-emerald-300" />
        模型使用建议
      </div>
      <p>
        省心用法：简历解析和所有面试环节使用同一个模型，配置简单，适合大多数练习。
      </p>
      <p className="mt-1">
        想进一步控制成本时，可以把简历/JD 解析交给理解力更强的模型，评分、提问和建议优先选择响应稳定的轻量模型。
      </p>
    </div>
  );
}

function EmbeddingRouteCard({
  config,
  onChange,
}: {
  config: LLMConfig;
  onChange: (patch: Partial<LLMEmbeddingOverrideConfig>) => void;
}) {
  const [showEmbeddingKey, setShowEmbeddingKey] = useState(false);
  const override = config.embeddingOverride ?? defaultEmbeddingOverride();
  const effective = effectiveEmbeddingConfig(config);
  const provider = embeddingProviderInfo(override.provider);
  const effectiveProvider = embeddingProviderInfo(effective.provider);
  const overrideEnabled = Boolean(override.enabled);
  const inheritsDefaultKey =
    !override.apiKey.trim() && config.provider === override.provider && config.apiKey.trim();

  return (
    <div
      className={cn(
        "rounded-md border p-3",
        overrideEnabled ? "bg-secondary/20" : "bg-secondary/10",
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-sm font-medium">简历与自我介绍</div>
          <p className="mt-1 text-xs text-muted-foreground">
            把候选人的关键信息整理成可追问的资料线索；推荐使用 Qwen，未单独配置时走服务器端默认配置。
          </p>
          <p className="mt-1 text-[11px] text-muted-foreground">
            推荐：{effectiveProvider.label} {effective.model || effectiveProvider.model}
          </p>
        </div>
        <label className="flex shrink-0 items-center gap-2 text-xs text-muted-foreground">
          <input
            type="checkbox"
            checked={overrideEnabled}
            onChange={(e) => {
              if (e.target.checked) {
                onChange({ ...defaultEmbeddingOverride(), enabled: true });
              } else {
                onChange({ enabled: false });
              }
            }}
            className="h-4 w-4 accent-emerald-500"
          />
          单独配置
        </label>
      </div>

      {overrideEnabled && (
        <div className="mt-3 grid gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <Button
              type="button"
              size="sm"
              variant="secondary"
              className="gap-1"
              onClick={() => onChange(defaultEmbeddingOverride())}
            >
              <Sparkles className="h-3.5 w-3.5" />
              使用建议配置
            </Button>
            <span className="text-[11px] text-muted-foreground">
              当前有效模型：{effectiveProvider.label}{" "}
              {effective.model || effectiveProvider.model}（{EMBEDDING_DIMENSIONS} 维）
            </span>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label>服务商</Label>
              <select
                value={provider.id}
                onChange={(e) => {
                  const nextProvider = embeddingProviderInfo(e.target.value);
                  onChange(defaultEmbeddingOverride(nextProvider.id));
                }}
                className={selectClass}
              >
                <option
                  key={provider.id}
                  value={provider.id}
                  className="bg-background text-foreground"
                >
                  {provider.label}
                </option>
              </select>
            </div>
            <div className="space-y-1.5">
              <Label>模型</Label>
              <Input
                placeholder={provider.model}
                value={override.model}
                onChange={(e) => onChange({ model: e.target.value })}
              />
            </div>
          </div>

          <div className="space-y-1.5">
            <Label>API 密钥（可选）</Label>
            <div className="relative">
              <Input
                type={showEmbeddingKey ? "text" : "password"}
                placeholder={
                  inheritsDefaultKey
                    ? `沿用默认 ${provider.label} Key`
                    : provider.keyPlaceholder
                }
                value={override.apiKey}
                onChange={(e) => onChange({ apiKey: e.target.value })}
                className="pr-10"
              />
              <button
                type="button"
                onClick={() => setShowEmbeddingKey(!showEmbeddingKey)}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                aria-label={showEmbeddingKey ? "隐藏 API 密钥" : "显示 API 密钥"}
              >
                {showEmbeddingKey ? (
                  <EyeOff className="h-4 w-4" />
                ) : (
                  <Eye className="h-4 w-4" />
                )}
              </button>
            </div>
            <p className="text-[11px] text-muted-foreground">
              {inheritsDefaultKey
                ? `沿用默认 ${provider.label} Key；只在整理简历和自我介绍资料时使用。`
                : `不填则沿用同为 ${provider.label} 的默认 Key；只在整理简历和自我介绍资料时使用。`}
            </p>
          </div>

          <div className="space-y-1.5">
            <Label>Base URL（基础地址）</Label>
            <Input
              placeholder={provider.baseUrl || "https://api.openai.com/v1"}
              value={override.baseUrl}
              onChange={(e) => onChange({ baseUrl: e.target.value })}
            />
          </div>
        </div>
      )}
    </div>
  );
}

function VoiceRouteCard({
  routeId,
  config,
  onChange,
}: {
  routeId: LLMVoiceRouteId;
  config: LLMConfig;
  onChange: (
    routeId: LLMVoiceRouteId,
    patch: Partial<LLMVoiceOverrideConfig>,
  ) => void;
}) {
  const [showVoiceKey, setShowVoiceKey] = useState(false);
  const override = config.voiceOverrides[routeId] ?? defaultVoiceOverride(routeId);
  const effective = effectiveVoiceConfig(config, routeId);
  const provider = voiceProviderInfo(override.provider);
  const effectiveProvider = voiceProviderInfo(effective.provider);
  const overrideEnabled = Boolean(override.enabled);
  const inheritsDefaultKey =
    !override.apiKey.trim() && config.provider === override.provider && config.apiKey.trim();
  const label = VOICE_ROUTE_LABELS[routeId];
  const modelPlaceholder = routeId === "asr" ? provider.asrModel : provider.ttsModel;
  const voiceOptions = provider.ttsVoices;
  const currentVoice = override.voice ?? provider.ttsVoice;
  const customVoiceSelected =
    routeId === "tts" && !voiceOptions.includes(currentVoice);
  const selectedPresetVoice = customVoiceSelected
    ? CUSTOM_VOICE_VALUE
    : currentVoice || provider.ttsVoice;
  const effectiveModel =
    routeId === "tts"
      ? `${effective.model || effectiveProvider.ttsModel} / ${effective.voice || effectiveProvider.ttsVoice}`
      : effective.model || effectiveProvider.asrModel;

  return (
    <div
      className={cn(
        "rounded-md border p-3",
        overrideEnabled ? "bg-secondary/20" : "bg-secondary/10",
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-sm font-medium">{label}</div>
          <p className="mt-1 text-xs text-muted-foreground">
            {routeId === "asr"
              ? "把录音转成可编辑文字草稿，默认使用 Qwen 实时语音识别。"
              : "把面试官问题合成为可播放语音，默认使用 Qwen 实时语音合成。"}
          </p>
          <p className="mt-1 text-[11px] text-muted-foreground">
            推荐：{effectiveProvider.label} {effectiveModel}
          </p>
        </div>
        <label className="flex shrink-0 items-center gap-2 text-xs text-muted-foreground">
          <input
            type="checkbox"
            checked={overrideEnabled}
            onChange={(e) => {
              if (e.target.checked) {
                onChange(routeId, { ...defaultVoiceOverride(routeId), enabled: true });
              } else {
                onChange(routeId, { enabled: false });
              }
            }}
            className="h-4 w-4 accent-emerald-500"
          />
          单独配置
        </label>
      </div>

      {overrideEnabled && (
        <div className="mt-3 grid gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <Button
              type="button"
              size="sm"
              variant="secondary"
              className="gap-1"
              onClick={() => onChange(routeId, defaultVoiceOverride(routeId))}
            >
              <Sparkles className="h-3.5 w-3.5" />
              使用建议配置
            </Button>
            <span className="text-[11px] text-muted-foreground">
              当前有效模型：{effectiveProvider.label} {effectiveModel}
            </span>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label>服务商</Label>
              <select
                value={override.provider}
                onChange={(e) => {
                  const nextProvider = voiceProviderInfo(e.target.value);
                  onChange(routeId, defaultVoiceOverride(routeId, nextProvider.id));
                }}
                className={selectClass}
              >
                {VOICE_PROVIDERS.map((p) => (
                  <option
                    key={p.id}
                    value={p.id}
                    className="bg-background text-foreground"
                  >
                    {p.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-1.5">
              <Label>模型</Label>
              <Input
                placeholder={modelPlaceholder}
                value={override.model}
                onChange={(e) => onChange(routeId, { model: e.target.value })}
              />
            </div>
          </div>

          {routeId === "tts" && (
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label>Voice</Label>
                <select
                  value={selectedPresetVoice}
                  onChange={(e) => {
                    const nextVoice = e.target.value;
                    onChange(routeId, {
                      voice: nextVoice === CUSTOM_VOICE_VALUE ? "" : nextVoice,
                    });
                  }}
                  className={selectClass}
                >
                  {voiceOptions.map((voice) => (
                    <option
                      key={voice}
                      value={voice}
                      className="bg-background text-foreground"
                    >
                      {voice}
                    </option>
                  ))}
                  <option
                    value={CUSTOM_VOICE_VALUE}
                    className="bg-background text-foreground"
                  >
                    自定义音色
                  </option>
                </select>
              </div>
              {customVoiceSelected && (
                <div className="space-y-1.5">
                  <Label>自定义音色</Label>
                  <Input
                    placeholder={provider.ttsVoice}
                    value={currentVoice}
                    onChange={(e) => onChange(routeId, { voice: e.target.value })}
                  />
                </div>
              )}
            </div>
          )}

          <div className="space-y-1.5">
            <Label>{provider.label} API 密钥（可选）</Label>
            <div className="relative">
              <Input
                type={showVoiceKey ? "text" : "password"}
                placeholder={
                  inheritsDefaultKey ? `沿用默认 ${provider.label} Key` : provider.keyPlaceholder
                }
                value={override.apiKey}
                onChange={(e) => onChange(routeId, { apiKey: e.target.value })}
                className="pr-10"
              />
              <button
                type="button"
                onClick={() => setShowVoiceKey(!showVoiceKey)}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                aria-label={showVoiceKey ? "隐藏 API 密钥" : "显示 API 密钥"}
              >
                {showVoiceKey ? (
                  <EyeOff className="h-4 w-4" />
                ) : (
                  <Eye className="h-4 w-4" />
                )}
              </button>
            </div>
            <p className="text-[11px] text-muted-foreground">
              {inheritsDefaultKey
                ? `沿用默认 ${provider.label} Key。`
                : `不填时，仅在默认配置同为 ${provider.label} 时继承默认 Key。`}
            </p>
          </div>

          <div className="space-y-1.5">
            <Label>Base URL（可选）</Label>
            <Input
              placeholder={provider.baseUrl || "https://api.openai.com/v1"}
              value={override.baseUrl}
              onChange={(e) => onChange(routeId, { baseUrl: e.target.value })}
            />
          </div>
        </div>
      )}
    </div>
  );
}

function RoleGroupCard({
  group,
  config,
  onChange,
}: {
  group: LLMRoleGroupInfo;
  config: LLMConfig;
  onChange: (
    groupId: LLMRoleGroupId,
    patch: Partial<LLMRoleOverrideConfig>,
  ) => void;
}) {
  const [showRoleKey, setShowRoleKey] = useState(false);
  const override = config.roleOverrides[group.id] ?? {
    ...recommendedRoleOverride(group.id),
    enabled: false,
  };
  const effective = effectiveRoleConfig(config, group.id);
  const provider = providerInfo(override.provider || config.provider);
  const showBaseUrl = providerShowsBaseUrl(override.provider || config.provider);
  const needsBaseUrl = providerRequiresBaseUrl(override.provider || config.provider);
  const recommendations = group.recommendations
    .map((item) => `${providerInfo(item.provider).label} ${item.model}`)
    .join(" / ");

  return (
    <div
      className={cn(
        "rounded-md border p-3",
        override.enabled ? "bg-secondary/20" : "bg-secondary/10",
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-sm font-medium">{group.label}</div>
          <p className="mt-1 text-xs text-muted-foreground">{group.description}</p>
          <p className="mt-1 text-[11px] text-muted-foreground">
            推荐：{recommendations}
          </p>
        </div>
        <label className="flex shrink-0 items-center gap-2 text-xs text-muted-foreground">
          <input
            type="checkbox"
            checked={override.enabled}
            onChange={(e) => {
              if (e.target.checked) {
                onChange(group.id, { ...recommendedRoleOverride(group.id) });
              } else {
                onChange(group.id, { enabled: false });
              }
            }}
            className="h-4 w-4 accent-emerald-500"
          />
          单独配置
        </label>
      </div>

      {override.enabled && (
        <div className="mt-3 grid gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <Button
              type="button"
              size="sm"
              variant="secondary"
              className="gap-1"
              onClick={() => onChange(group.id, recommendedRoleOverride(group.id))}
            >
              <Sparkles className="h-3.5 w-3.5" />
              使用建议配置
            </Button>
            <span className="text-[11px] text-muted-foreground">
              当前有效模型：{providerInfo(effective.provider).label} {effective.model}
            </span>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label>服务商</Label>
              <select
                value={override.provider}
                onChange={(e) => {
                  const nextProvider = providerInfo(e.target.value);
                  onChange(group.id, {
                    provider: nextProvider.id,
                    model: nextProvider.defaultModel,
                    baseUrl: nextProvider.defaultBaseUrl,
                  });
                }}
                className={selectClass}
              >
                {PROVIDERS.map((p) => (
                  <option
                    key={p.id}
                    value={p.id}
                    className="bg-background text-foreground"
                  >
                    {p.label}
                  </option>
                ))}
              </select>
            </div>

            <div className="space-y-1.5">
              <Label>模型</Label>
              <Input
                placeholder={provider.defaultModel || "model-id"}
                value={override.model}
                onChange={(e) => onChange(group.id, { model: e.target.value })}
              />
            </div>
          </div>

          <div className="space-y-1.5">
            <Label>API 密钥（可选）</Label>
            <div className="relative">
              <Input
                type={showRoleKey ? "text" : "password"}
                placeholder={provider.keyPlaceholder}
                value={override.apiKey}
                onChange={(e) => onChange(group.id, { apiKey: e.target.value })}
                className="pr-10"
              />
              <button
                type="button"
                onClick={() => setShowRoleKey(!showRoleKey)}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                aria-label={showRoleKey ? "隐藏 API 密钥" : "显示 API 密钥"}
              >
                {showRoleKey ? (
                  <EyeOff className="h-4 w-4" />
                ) : (
                  <Eye className="h-4 w-4" />
                )}
              </button>
            </div>
            <p className="text-[11px] text-muted-foreground">{group.keyHint}</p>
          </div>

          {showBaseUrl && (
            <div className="space-y-1.5">
              <Label>
                Base URL（基础地址）
                {needsBaseUrl && <span className="text-destructive"> *</span>}
              </Label>
              <Input
                placeholder={provider.defaultBaseUrl || "https://example.com/v1"}
                value={override.baseUrl}
                onChange={(e) => onChange(group.id, { baseUrl: e.target.value })}
              />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function connectionStatusMessage(statusKind: LLMConfigStatus): string {
  switch (statusKind) {
    case "auth_failed":
      return "保存的密钥可能已过期、被撤销，或没有调用当前模型的权限。请更新对应密钥后再测试。";
    case "quota_exhausted":
      return "有一项配置的额度不足或余额耗尽。可以换一个 Key，或到对应厂商控制台检查余额。";
    case "rate_limited":
      return "有一项配置被限流了。可以稍后再试，或换成请求额度更充足的 Key。";
    case "transient":
      return "模型服务或网络暂时不稳定。配置本身不一定错，稍后重试通常就好。";
    case "misconfig":
      return "有一项配置不完整或不匹配，请检查模型名称、服务商和 Base URL。";
    case "error":
      return "部分配置测试未通过。请根据下方结果检查失败项的密钥、模型和 Base URL。";
    default:
      return "部分配置测试未通过。请根据下方结果检查失败项的密钥、模型和 Base URL。";
  }
}

function connectionImpactMessage(result: LLMTestTargetStatus): string | null {
  if (result.ok) return null;
  const isTransient =
    result.errorKind === "network" || result.errorKind === "timeout";
  if (!isTransient) return null;

  if (result.kind === "asr" || result.kind === "tts") {
    return "语音能力临时不可用；文字面试不受影响，可以稍后重试语音。";
  }
  if (result.kind === "embedding") {
    return "资料理解能力临时不可用；简历和自我介绍锚点可能退回保守召回路径。";
  }
  if (result.label === "默认配置") {
    return "默认配置临时不可用；未单独配置的回答评分等环节会一起受影响，面试中可能触发兜底评分。";
  }
  if (result.label === "回答评分") {
    return "回答评分临时不可用；面试可继续，但本轮可能使用兜底评分，报告可信度会降低。";
  }
  return `${result.label} 临时不可用；配置不一定错，稍后重试通常可以恢复。`;
}

function ConnectionResult({
  config,
  statusKind,
  status,
  error,
  visible,
  onDismiss,
}: {
  config: LLMConfig;
  statusKind: LLMConfigStatus;
  status: LLMTestStatus | null;
  error: string | null;
  visible: boolean;
  onDismiss: () => void;
}) {
  if (error) {
    return (
      <div className="flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive/10 p-3 text-xs text-destructive">
        <AlertCircle className="mt-0.5 h-4 w-4 flex-shrink-0" />
        <span className="min-w-0 flex-1">{error}</span>
        <button
          type="button"
          onClick={onDismiss}
          className="rounded p-0.5 text-destructive/70 transition-colors hover:bg-destructive/10 hover:text-destructive"
          aria-label="关闭提示"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
    );
  }
  if (!visible) {
    return null;
  }
  if (statusKind === "missing") {
    return (
      <DismissibleResult
        tone="neutral"
        onDismiss={onDismiss}
        message="还没有填写个人 API Key。你仍然可以开始面试，系统会使用默认练习模式；填写自己的 Key 后可以在这里测试连接。"
      />
    );
  }
  if (statusKind === "untested") {
    return (
      <DismissibleResult
        tone="warn"
        onDismiss={onDismiss}
        message="已填写的个人 API 配置尚未完整测试，保存后也可以直接开始，面试时会使用它。"
      />
    );
  }

  const targets = testTargets(config);
  const results = targets
    .map((target) => status?.results?.[target.id])
    .filter((result): result is LLMTestTargetStatus => Boolean(result));
  const success = statusKind === "success";

  return (
    <div
      className={cn(
        "rounded-md border p-3 text-xs",
        success
          ? "border-emerald-400/30 bg-emerald-400/10 text-emerald-200"
          : "border-destructive/30 bg-destructive/10 text-destructive",
      )}
    >
      <div className="flex items-start gap-2">
        {success ? (
          <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0" />
        ) : (
          <AlertCircle className="mt-0.5 h-4 w-4 flex-shrink-0" />
        )}
        <span className="min-w-0 flex-1">
          {success
            ? "所有已启用配置连接成功。"
            : connectionStatusMessage(statusKind)}
        </span>
        <button
          type="button"
          onClick={onDismiss}
          className="rounded p-0.5 opacity-70 transition-colors hover:bg-current/10 hover:opacity-100"
          aria-label="关闭提示"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
      {results.length > 0 && (
        <div className="mt-2 grid gap-1.5 text-[11px]">
          {results.map((result) => (
            <div
              key={result.fingerprint}
              className={cn(
                "flex items-start justify-between gap-3 rounded border px-2 py-1",
                result.ok
                  ? "border-emerald-400/30 bg-emerald-400/10 text-emerald-200"
                  : "border-destructive/30 bg-destructive/10 text-destructive",
              )}
            >
              <span className="min-w-0">
                <span className="block truncate">
                  {result.label}：{routeProviderLabel(result.provider, result.kind)} {result.model}
                </span>
                {!result.ok && result.error ? (
                  <span className="mt-0.5 block break-words opacity-90">
                    {result.error}
                  </span>
                ) : null}
                {connectionImpactMessage(result) ? (
                  <span className="mt-0.5 block break-words text-[10px] opacity-80">
                    {connectionImpactMessage(result)}
                  </span>
                ) : null}
              </span>
              <span className="shrink-0">
                {result.ok ? `${result.latencyMs} ms` : llmErrorKindLabel(result.errorKind)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function DismissibleResult({
  tone,
  message,
  onDismiss,
}: {
  tone: "neutral" | "warn";
  message: string;
  onDismiss: () => void;
}) {
  return (
    <div
      className={cn(
        "flex items-start gap-2 rounded-md border p-3 text-xs",
        tone === "warn"
          ? "border-amber-400/30 bg-amber-400/10 text-amber-200"
          : "bg-secondary/30 text-muted-foreground",
      )}
    >
      <span className="min-w-0 flex-1">{message}</span>
      <button
        type="button"
        onClick={onDismiss}
        className="rounded p-0.5 opacity-70 transition-colors hover:bg-current/10 hover:opacity-100"
        aria-label="关闭提示"
      >
        <X className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}
