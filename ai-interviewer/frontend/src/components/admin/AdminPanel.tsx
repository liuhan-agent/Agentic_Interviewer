"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  AlertTriangle,
  BookMarked,
  ChevronLeft,
  ChevronRight,
  Clock,
  ClipboardList,
  Copy,
  Cpu,
  ExternalLink,
  History,
  Key,
  Loader2,
  Play,
  RefreshCw,
  Search,
  ShieldCheck,
  Trash2,
  Users,
  WalletCards,
  Waypoints,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { PendingNavigationLink } from "@/components/navigation/PendingNavigationLink";
import { SessionIdTooltip } from "@/components/interview/SessionIdTooltip";
import { formatCreditLedgerEntry } from "@/lib/credits";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { CandidateAnchorRagCard } from "@/components/admin/CandidateAnchorRagCard";
import { RagEvalPanel } from "@/components/admin/RagEvalPanel";
import {
  FALLBACK_KIND_DESCRIPTIONS,
  FALLBACK_KIND_LABELS,
  FALLBACK_KIND_ORDER,
  getAdminCreditRequests,
  getAdminSessions,
  getAdminUserDetail,
  getAdminUserCreditLedger,
  getAdminUserCredits,
  getAdminUsers,
  getBackendHealth,
  getBanditSnapshot,
  getEvidenceRollUp,
  getFallbackRates,
  getInterviewSessionsHistory,
  getQuestionQualityRollUp,
  getQuestionRewardReadiness,
  getQuestionRerankUsages,
  getQuestionReviews,
  getQuestionSeed,
  getQuestionSeeds,
  getQuestionUsageStats,
  getQuestionUsages,
  getRecentTracesByNode,
  getSkillPlaybook,
  getSkillPlaybooks,
  getSkillRewardReadiness,
  getSkillUsageStats,
  getStrategySignals,
  getStrategyRewardReadiness,
  getStrategyStats,
  getStrategyUsages,
  getStrategies,
  getTraceRollUp,
  getVerifierDrift,
  importSkillPlaybooks,
  importQuestionSeeds,
  importStrategySeeds,
  runQuestionSeedLint,
  loadAdminToken,
  archiveQuestionSeed,
  archiveQuestionVariant,
  archiveStrategy,
  adjustAdminUserCredits,
  decideAdminCreditRequest,
  disableQuestionSeed,
  disableQuestionVariant,
  disableStrategy,
  createQuestionReview,
  refreshStrategyStats,
  refreshQuestionUsageStats,
  refreshSkillUsageStats,
  runStrategyPromotion,
  saveAdminToken,
  setSkillRewardRollout,
  setQuestionRewardRollout,
  setStrategyRewardRollout,
  updateAdminUserStatus,
  type AdminCreditRequest,
  type AdminCreditRequestsResponse,
  type AdminSessions,
  type AdminUserDetail,
  type AdminUserItem,
  type AdminUserListResponse,
  type AdminUserCredit,
  type AdminUserCreditLedgerResponse,
  type AdminUserCreditsResponse,
  type BackendHealth,
  type BanditSnapshot,
  type EvidenceRollupResponse,
  type FallbackKind,
  type FallbackRatesResponse,
  type InterviewSessionHistory,
  type InterviewSessionHistoryFilters,
  type InterviewSessionHistoryItem,
  type QuestionSeedDetail,
  type QuestionSeeds,
  type QuestionRewardReadiness,
  type QuestionRewardReadinessGroup,
  type QuestionRewardRolloutMode,
  type QuestionRewardRolloutScope,
  type QuestionRerankUsages,
  type QuestionReviews,
  type QuestionUsageStatsResponse,
  type QuestionUsages,
  type QuestionQualityRollupResponse,
  type RecentTracesResponse,
  type SkillPlaybookDetail,
  type SkillPlaybooks,
  type SkillRewardReadiness,
  type SkillRewardRolloutMode,
  type SkillUsageStatsResponse,
  type Strategies,
  type StrategyPromotionSchedulerStatus,
  type StrategyRewardReadiness,
  type StrategyRewardRolloutMode,
  type StrategySignalGroup,
  type StrategySignals,
  type StrategyStats,
  type StrategyUsages,
  type TraceRollupResponse,
  type VerifierDriftSnapshot,
} from "@/lib/api/admin";
import { adminDeleteSession } from "@/lib/api/admin";
import { useToast } from "@/lib/hooks/useToast";
import { LLM_CONFIG_EVENT, hasApiKey } from "@/lib/llm-config";
import { removeEntry } from "@/lib/storage/interviewHistory";
import { cn } from "@/lib/utils";

// Auto-refresh cadence keeps the panel useful as a passive dashboard
// without hammering the backend; 15s strikes the same balance the
// /health dot in the header uses.
const REFRESH_INTERVAL_MS = 15_000;
const HISTORY_PAGE_SIZE = 20;
const ADMIN_ACCOUNT_PAGE_SIZE = 20;
const HISTORY_SEARCH_DEBOUNCE_MS = 300;
const QUESTION_USAGE_STATS_PAGE_SIZE = 25;
const SKILL_USAGE_STATS_PAGE_SIZE = 25;
const ADMIN_ACTIVE_TAB_STORAGE_KEY = "agentic-interviewer:admin-active-tab";
const BANDIT_RAW_DETAILS_PAGE_SIZE = 50;

type BanditRawDetailsFilterField =
  | "all"
  | "context_key"
  | "action_id"
  | "canonical_action";

const BANDIT_RAW_DETAILS_FILTER_OPTIONS: Array<{
  value: BanditRawDetailsFilterField;
  label: string;
}> = [
  { value: "all", label: "全部字段" },
  { value: "context_key", label: "context_key" },
  { value: "action_id", label: "action_id" },
  { value: "canonical_action", label: "canonical_action" },
];

type Loadable<T> =
  | { phase: "loading" }
  | { phase: "ready"; data: T }
  | { phase: "error"; message: string };

type AdminTabId = "health" | "scoring" | "strategy";

type AdminTabCssVars = React.CSSProperties & {
  "--admin-tab-bg": string;
  "--admin-tab-border": string;
  "--admin-tab-rail": string;
  "--admin-tab-ring": string;
};

type AdminTabTheme = {
  id: AdminTabId;
  label: string;
  icon: typeof Activity;
  tabActive: string;
  tabInactive: string;
  iconActive: string;
  panelStyle: AdminTabCssVars;
};

const ADMIN_TAB_PANEL_CARD_THEME =
  "[&_.rounded-xl.border.bg-card]:shadow-[0_0_0_1px_var(--admin-tab-ring)]";

const ADMIN_TAB_THEMES: Record<AdminTabId, AdminTabTheme> = {
  health: {
    id: "health",
    label: "运行健康",
    icon: Activity,
    tabActive:
      "border-emerald-500/35 bg-emerald-500/10 text-emerald-700 shadow-sm dark:text-emerald-100",
    tabInactive:
      "border-transparent text-muted-foreground hover:bg-emerald-500/5 hover:text-emerald-700 dark:hover:text-emerald-100",
    iconActive: "text-emerald-500 dark:text-emerald-300",
    panelStyle: {
      "--admin-tab-bg": "rgb(16 185 129 / 0.055)",
      "--admin-tab-border": "rgb(16 185 129 / 0.28)",
      "--admin-tab-rail": "rgb(16 185 129 / 0.78)",
      "--admin-tab-ring": "rgb(16 185 129 / 0.14)",
    },
  },
  scoring: {
    id: "scoring",
    label: "评分质量",
    icon: ClipboardList,
    tabActive:
      "border-sky-500/35 bg-sky-500/10 text-sky-700 shadow-sm dark:text-sky-100",
    tabInactive:
      "border-transparent text-muted-foreground hover:bg-sky-500/5 hover:text-sky-700 dark:hover:text-sky-100",
    iconActive: "text-sky-500 dark:text-sky-300",
    panelStyle: {
      "--admin-tab-bg": "rgb(14 165 233 / 0.055)",
      "--admin-tab-border": "rgb(14 165 233 / 0.28)",
      "--admin-tab-rail": "rgb(14 165 233 / 0.78)",
      "--admin-tab-ring": "rgb(14 165 233 / 0.14)",
    },
  },
  strategy: {
    id: "strategy",
    label: "策略学习",
    icon: BookMarked,
    tabActive:
      "border-amber-500/35 bg-amber-500/10 text-amber-700 shadow-sm dark:text-amber-100",
    tabInactive:
      "border-transparent text-muted-foreground hover:bg-amber-500/5 hover:text-amber-700 dark:hover:text-amber-100",
    iconActive: "text-amber-500 dark:text-amber-300",
    panelStyle: {
      "--admin-tab-bg": "rgb(245 158 11 / 0.055)",
      "--admin-tab-border": "rgb(245 158 11 / 0.28)",
      "--admin-tab-rail": "rgb(245 158 11 / 0.78)",
      "--admin-tab-ring": "rgb(245 158 11 / 0.14)",
    },
  },
};

const ADMIN_TABS = [
  ADMIN_TAB_THEMES.health,
  ADMIN_TAB_THEMES.scoring,
  ADMIN_TAB_THEMES.strategy,
];

function isAdminTabId(value: string | null): value is AdminTabId {
  return value === "health" || value === "scoring" || value === "strategy";
}

function loadStoredAdminTab(): AdminTabId | null {
  if (typeof window === "undefined") return null;
  try {
    const stored = window.localStorage.getItem(ADMIN_ACTIVE_TAB_STORAGE_KEY);
    return isAdminTabId(stored) ? stored : null;
  } catch {
    return null;
  }
}

function useAutoFetch<T>(
  fetcher: (signal?: AbortSignal) => Promise<T>,
  refreshKey: number,
): Loadable<T> {
  const [state, setState] = useState<Loadable<T>>({ phase: "loading" });

  useEffect(() => {
    const ctrl = new AbortController();
    setState((prev) =>
      prev.phase === "ready" ? prev : { phase: "loading" },
    );
    fetcher(ctrl.signal)
      .then((data) => {
        if (ctrl.signal.aborted) return;
        setState({ phase: "ready", data });
      })
      .catch((err) => {
        if (ctrl.signal.aborted) return;
        setState({
          phase: "error",
          message: err instanceof Error ? err.message : String(err),
        });
      });
    return () => ctrl.abort();
  }, [fetcher, refreshKey]);

  return state;
}

function AdminHealthSection({
  traceRollup,
  fallbackRollup,
  evidenceRollup,
  questionQualityRollup,
  fallbackRates,
  recentTraces,
  recentNode,
  onRecentNodeChange,
  sessions,
  history,
  historyPage,
  historyFilters,
  historySearchText,
  adminUsers,
  adminUserDetail,
  selectedAdminUserId,
  accountSearchText,
  accountStatusFilter,
  accountRoleFilter,
  accountPage,
  creditRequests,
  creditRequestSearchText,
  creditRequestStatusFilter,
  userCredits,
  userCreditLedger,
  selectedCreditUserId,
  creditSearchText,
  onSelectedAdminUserIdChange,
  onAccountSearchTextChange,
  onAccountStatusFilterChange,
  onAccountRoleFilterChange,
  onAccountPageChange,
  onCreditRequestSearchTextChange,
  onCreditRequestStatusFilterChange,
  onSelectedCreditUserIdChange,
  onCreditSearchTextChange,
  onHistoryPageChange,
  onHistoryFiltersChange,
  onHistorySearchTextChange,
  onRefresh,
}: {
  traceRollup: Loadable<TraceRollupResponse>;
  fallbackRollup: Loadable<TraceRollupResponse>;
  evidenceRollup: Loadable<EvidenceRollupResponse>;
  questionQualityRollup: Loadable<QuestionQualityRollupResponse>;
  fallbackRates: Loadable<FallbackRatesResponse>;
  recentTraces: Loadable<RecentTracesResponse>;
  recentNode: string;
  onRecentNodeChange: (next: string) => void;
  sessions: Loadable<AdminSessions>;
  history: Loadable<InterviewSessionHistory>;
  historyPage: number;
  historyFilters: InterviewSessionHistoryFilters;
  historySearchText: string;
  adminUsers: Loadable<AdminUserListResponse>;
  adminUserDetail: Loadable<AdminUserDetail | null>;
  selectedAdminUserId: number | null;
  accountSearchText: string;
  accountStatusFilter: string;
  accountRoleFilter: string;
  accountPage: number;
  creditRequests: Loadable<AdminCreditRequestsResponse>;
  creditRequestSearchText: string;
  creditRequestStatusFilter: string;
  userCredits: Loadable<AdminUserCreditsResponse>;
  userCreditLedger: Loadable<AdminUserCreditLedgerResponse>;
  selectedCreditUserId: number | null;
  creditSearchText: string;
  onSelectedAdminUserIdChange: (userId: number) => void;
  onAccountSearchTextChange: (text: string) => void;
  onAccountStatusFilterChange: (status: string) => void;
  onAccountRoleFilterChange: (role: string) => void;
  onAccountPageChange: (page: number) => void;
  onCreditRequestSearchTextChange: (text: string) => void;
  onCreditRequestStatusFilterChange: (status: string) => void;
  onSelectedCreditUserIdChange: (userId: number) => void;
  onCreditSearchTextChange: (text: string) => void;
  onHistoryPageChange: (page: number) => void;
  onHistoryFiltersChange: (filters: InterviewSessionHistoryFilters) => void;
  onHistorySearchTextChange: (text: string) => void;
  onRefresh: () => void;
}) {
  return (
    <>
      <InterviewQualityOverview
        trace={traceRollup}
        fallback={fallbackRollup}
        evidence={evidenceRollup}
        question={questionQualityRollup}
      />
      <AccountManagementPanel
        users={adminUsers}
        detail={adminUserDetail}
        selectedUserId={selectedAdminUserId}
        searchText={accountSearchText}
        statusFilter={accountStatusFilter}
        roleFilter={accountRoleFilter}
        page={accountPage}
        pageSize={ADMIN_ACCOUNT_PAGE_SIZE}
        onSelectedUserIdChange={onSelectedAdminUserIdChange}
        onSearchTextChange={onAccountSearchTextChange}
        onStatusFilterChange={onAccountStatusFilterChange}
        onRoleFilterChange={onAccountRoleFilterChange}
        onPageChange={onAccountPageChange}
        onRefresh={onRefresh}
      />
      <CreditRequestsPanel
        requests={creditRequests}
        searchText={creditRequestSearchText}
        statusFilter={creditRequestStatusFilter}
        onSearchTextChange={onCreditRequestSearchTextChange}
        onStatusFilterChange={onCreditRequestStatusFilterChange}
        onRefresh={onRefresh}
      />
      <UserCreditsPanel
        users={userCredits}
        ledger={userCreditLedger}
        selectedUserId={selectedCreditUserId}
        searchText={creditSearchText}
        onSelectedUserIdChange={onSelectedCreditUserIdChange}
        onSearchTextChange={onCreditSearchTextChange}
        onRefresh={onRefresh}
      />
      <section aria-label="24 小时主链路诊断" className="space-y-6">
        <TraceHealthRollUp state={traceRollup} />
        <FallbackRollUp state={fallbackRollup} />
      </section>
      <section className="space-y-3">
        <div>
          <h3 className="text-sm font-semibold text-foreground">二级诊断</h3>
          <p className="mt-1 text-xs text-muted-foreground">
            需要定位原因时再看这里：实时 fallback 看进程内增量，最近 trace
            看单节点样本。
          </p>
        </div>
        <div className="grid gap-6 lg:grid-cols-2">
          <FallbackKindCounts state={fallbackRates} />
          <RecentTracesByNode
            state={recentTraces}
            node={recentNode}
            onNodeChange={onRecentNodeChange}
          />
        </div>
      </section>
      <SessionsCard state={sessions} />
      <HistoricalSessionsCard
        state={history}
        historyPage={historyPage}
        pageSize={HISTORY_PAGE_SIZE}
        filters={historyFilters}
        searchText={historySearchText}
        onHistoryPageChange={onHistoryPageChange}
        onHistoryFiltersChange={onHistoryFiltersChange}
        onHistorySearchTextChange={onHistorySearchTextChange}
        onRefresh={onRefresh}
      />
    </>
  );
}

function AdminScoringSection({
  evidenceRollup,
  questionQualityRollup,
  drift,
}: {
  evidenceRollup: Loadable<EvidenceRollupResponse>;
  questionQualityRollup: Loadable<QuestionQualityRollupResponse>;
  drift: Loadable<VerifierDriftSnapshot>;
}) {
  return (
    <>
      <section aria-label="评分主诊断" className="space-y-6">
        <EvidenceRollUp state={evidenceRollup} />
        <QuestionQualityRollUp state={questionQualityRollup} />
      </section>
      <section className="space-y-3">
        <div>
          <h3 className="text-sm font-semibold text-foreground">评分二级诊断</h3>
          <p className="mt-1 text-xs text-muted-foreground">
            需要定位原因时再看这里：复核分歧看评分裁定漂移，RAG 观察看检索信号和评分分布的相关性。
          </p>
        </div>
        <div className="space-y-6">
          <DriftCard state={drift} />
          <RagEvalSection />
        </div>
      </section>
    </>
  );
}

function AdminStrategySection({
  bandit,
  questionSeeds,
  questionUsages,
  questionUsageStats,
  questionUsageStatsPage,
  onQuestionUsageStatsPageChange,
  questionRewardReadiness,
  questionRerankUsages,
  questionReviews,
  skillPlaybooks,
  skillUsageStats,
  skillUsageStatsPage,
  onSkillUsageStatsPageChange,
  skillRewardReadiness,
  strategies,
  strategySignals,
  strategyUsages,
  strategyStats,
  strategyRewardReadiness,
  onRefresh,
}: {
  bandit: Loadable<BanditSnapshot>;
  questionSeeds: Loadable<QuestionSeeds>;
  questionUsages: Loadable<QuestionUsages>;
  questionUsageStats: Loadable<QuestionUsageStatsResponse>;
  questionUsageStatsPage: number;
  onQuestionUsageStatsPageChange: (page: number) => void;
  questionRewardReadiness: Loadable<QuestionRewardReadiness>;
  questionRerankUsages: Loadable<QuestionRerankUsages>;
  questionReviews: Loadable<QuestionReviews>;
  skillPlaybooks: Loadable<SkillPlaybooks>;
  skillUsageStats: Loadable<SkillUsageStatsResponse>;
  skillUsageStatsPage: number;
  onSkillUsageStatsPageChange: (page: number) => void;
  skillRewardReadiness: Loadable<SkillRewardReadiness>;
  strategies: Loadable<Strategies>;
  strategySignals: Loadable<StrategySignals>;
  strategyUsages: Loadable<StrategyUsages>;
  strategyStats: Loadable<StrategyStats>;
  strategyRewardReadiness: Loadable<StrategyRewardReadiness>;
  onRefresh: () => void;
}) {
  return (
    <>
      <StrategyLearningOverview
        bandit={bandit}
        questionSeeds={questionSeeds}
        questionUsages={questionUsages}
        skillPlaybooks={skillPlaybooks}
        strategies={strategies}
        strategyUsages={strategyUsages}
      />
      <section aria-label="策略学习治理台" className="space-y-6">
        <BanditCard state={bandit} />
        <QuestionBankCard
          state={questionSeeds}
          usages={questionUsages}
          usageStats={questionUsageStats}
          usageStatsPage={questionUsageStatsPage}
          onUsageStatsPageChange={onQuestionUsageStatsPageChange}
          rewardReadiness={questionRewardReadiness}
          rerankUsages={questionRerankUsages}
          reviews={questionReviews}
          onRefresh={onRefresh}
        />
        <SkillsPlaybookCard
          state={skillPlaybooks}
          usageStats={skillUsageStats}
          usageStatsPage={skillUsageStatsPage}
          onUsageStatsPageChange={onSkillUsageStatsPageChange}
          rewardReadiness={skillRewardReadiness}
          onRefresh={onRefresh}
        />
        <StrategiesCard
          state={strategies}
          signals={strategySignals}
          usages={strategyUsages}
          stats={strategyStats}
          rewardReadiness={strategyRewardReadiness}
          onRefresh={onRefresh}
        />
      </section>
    </>
  );
}

function AdminTabPanel({
  theme,
  children,
}: {
  theme: AdminTabTheme;
  children: React.ReactNode;
}) {
  return (
    <section
      style={theme.panelStyle}
      className={cn(
        "space-y-6 rounded-xl border p-3 transition-colors sm:p-4",
        "border-[color:var(--admin-tab-border)] bg-[color:var(--admin-tab-bg)]",
        "shadow-[inset_0_1px_0_var(--admin-tab-ring)]",
        ADMIN_TAB_PANEL_CARD_THEME,
      )}
    >
      <div className="h-1 w-24 rounded-full bg-[color:var(--admin-tab-rail)]" />
      {children}
    </section>
  );
}

export function AdminPanel() {
  const [tokenInput, setTokenInput] = useState("");
  const [tokenSaved, setTokenSaved] = useState("");
  const [tick, setTick] = useState(0);
  const [recentNode, setRecentNode] = useState<string>("evaluator");
  const [activeTab, setActiveTab] = useState<AdminTabId>("health");
  const [historyPage, setHistoryPage] = useState(0);
  const [questionUsageStatsPage, setQuestionUsageStatsPage] = useState(0);
  const [skillUsageStatsPage, setSkillUsageStatsPage] = useState(0);
  const [historyFilters, setHistoryFilters] =
    useState<InterviewSessionHistoryFilters>({});
  const [historySearchText, setHistorySearchText] = useState("");
  const [debouncedHistoryQuery, setDebouncedHistoryQuery] = useState("");
  const [browserHasLlmKey, setBrowserHasLlmKey] = useState(false);
  const [accountSearchText, setAccountSearchText] = useState("");
  const [accountStatusFilter, setAccountStatusFilter] = useState("");
  const [accountRoleFilter, setAccountRoleFilter] = useState("");
  const [accountPage, setAccountPage] = useState(0);
  const [selectedAdminUserId, setSelectedAdminUserId] = useState<number | null>(
    null,
  );
  const [creditRequestSearchText, setCreditRequestSearchText] = useState("");
  const [creditRequestStatusFilter, setCreditRequestStatusFilter] =
    useState("pending");
  const [creditSearchText, setCreditSearchText] = useState("");
  const [selectedCreditUserId, setSelectedCreditUserId] = useState<number | null>(null);

  useEffect(() => {
    const t = loadAdminToken();
    setTokenInput(t);
    setTokenSaved(t);
  }, []);

  useEffect(() => {
    const storedTab = loadStoredAdminTab();
    if (storedTab) {
      setActiveTab(storedTab);
    }
  }, []);

  useEffect(() => {
    const id = window.setInterval(
      () => setTick((t) => t + 1),
      REFRESH_INTERVAL_MS,
    );
    return () => window.clearInterval(id);
  }, []);

  useEffect(() => {
    const refresh = () => setBrowserHasLlmKey(hasApiKey());
    refresh();
    window.addEventListener(LLM_CONFIG_EVENT, refresh);
    return () => window.removeEventListener(LLM_CONFIG_EVENT, refresh);
  }, []);

  useEffect(() => {
    const id = window.setTimeout(
      () => setDebouncedHistoryQuery(historySearchText.trim()),
      HISTORY_SEARCH_DEBOUNCE_MS,
    );
    return () => window.clearTimeout(id);
  }, [historySearchText]);

  useEffect(() => {
    setHistoryPage(0);
  }, [historyFilters, debouncedHistoryQuery]);

  useEffect(() => {
    setAccountPage(0);
  }, [accountSearchText, accountStatusFilter, accountRoleFilter]);

  const activeHistoryFilters = React.useMemo<InterviewSessionHistoryFilters>(() => {
    const next: InterviewSessionHistoryFilters = { ...historyFilters };
    if (debouncedHistoryQuery) {
      next.query = debouncedHistoryQuery;
    }
    return next;
  }, [historyFilters, debouncedHistoryQuery]);

  // ``tokenSaved`` is the value we actually fetch against; editing
  // the input does not refetch until the operator clicks Save. That
  // keeps mid-typing requests from flooding the backend with 403s.
  const healthFetcher = useCallback(
    (signal?: AbortSignal) => getBackendHealth(signal),
    [],
  );
  const banditFetcher = useCallback(
    (signal?: AbortSignal) => getBanditSnapshot(signal),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [tokenSaved],
  );
  const driftFetcher = useCallback(
    (signal?: AbortSignal) => getVerifierDrift(signal),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [tokenSaved],
  );
  const sessionsFetcher = useCallback(
    (signal?: AbortSignal) => getAdminSessions(signal),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [tokenSaved],
  );
  const historyFetcher = useCallback(
    (signal?: AbortSignal) =>
      getInterviewSessionsHistory(signal, {
        offset: historyPage * HISTORY_PAGE_SIZE,
        limit: HISTORY_PAGE_SIZE,
        filters: activeHistoryFilters,
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [tokenSaved, historyPage, activeHistoryFilters],
  );
  const userCreditsFetcher = useCallback(
    (signal?: AbortSignal) =>
      getAdminUserCredits(signal, {
        email: creditSearchText.trim() || undefined,
        limit: 20,
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [tokenSaved, creditSearchText],
  );
  const adminUsersFetcher = useCallback(
    (signal?: AbortSignal) =>
      getAdminUsers(signal, {
        email: accountSearchText.trim() || undefined,
        status: accountStatusFilter || undefined,
        role: accountRoleFilter || undefined,
        offset: accountPage * ADMIN_ACCOUNT_PAGE_SIZE,
        limit: ADMIN_ACCOUNT_PAGE_SIZE,
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [
      tokenSaved,
      accountSearchText,
      accountStatusFilter,
      accountRoleFilter,
      accountPage,
    ],
  );
  const adminUserDetailFetcher = useCallback(
    (signal?: AbortSignal) =>
      selectedAdminUserId
        ? getAdminUserDetail(selectedAdminUserId, signal)
        : Promise.resolve(null),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [tokenSaved, selectedAdminUserId],
  );
  const creditRequestsFetcher = useCallback(
    (signal?: AbortSignal) =>
      getAdminCreditRequests(signal, {
        email: creditRequestSearchText.trim() || undefined,
        status: creditRequestStatusFilter || undefined,
        limit: 20,
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [tokenSaved, creditRequestSearchText, creditRequestStatusFilter],
  );
  const userCreditLedgerFetcher = useCallback(
    (signal?: AbortSignal) =>
      selectedCreditUserId
        ? getAdminUserCreditLedger(selectedCreditUserId, signal)
        : Promise.resolve({
            user_id: 0,
            balance: 0,
            count: 0,
            total_count: 0,
            limit: 100,
            offset: 0,
            entries: [],
          } satisfies AdminUserCreditLedgerResponse),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [tokenSaved, selectedCreditUserId],
  );
  const strategiesFetcher = useCallback(
    (signal?: AbortSignal) => getStrategies(signal),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [tokenSaved],
  );
  const skillPlaybooksFetcher = useCallback(
    (signal?: AbortSignal) => getSkillPlaybooks(signal),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [tokenSaved],
  );
  const skillUsageStatsFetcher = useCallback(
    (signal?: AbortSignal) =>
      getSkillUsageStats(true, {
        limit: SKILL_USAGE_STATS_PAGE_SIZE,
        offset: skillUsageStatsPage * SKILL_USAGE_STATS_PAGE_SIZE,
        signal,
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [tokenSaved, skillUsageStatsPage],
  );
  const skillRewardReadinessFetcher = useCallback(
    (signal?: AbortSignal) => getSkillRewardReadiness(true, signal),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [tokenSaved],
  );
  const questionSeedsFetcher = useCallback(
    (signal?: AbortSignal) => getQuestionSeeds(signal),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [tokenSaved],
  );
  const questionUsagesFetcher = useCallback(
    (signal?: AbortSignal) => getQuestionUsages(signal),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [tokenSaved],
  );
  const questionUsageStatsFetcher = useCallback(
    (signal?: AbortSignal) =>
      getQuestionUsageStats(true, {
        limit: QUESTION_USAGE_STATS_PAGE_SIZE,
        offset: questionUsageStatsPage * QUESTION_USAGE_STATS_PAGE_SIZE,
        signal,
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [tokenSaved, questionUsageStatsPage],
  );
  const questionRewardReadinessFetcher = useCallback(
    (signal?: AbortSignal) => getQuestionRewardReadiness(true, signal),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [tokenSaved],
  );
  const questionRerankUsagesFetcher = useCallback(
    (signal?: AbortSignal) => getQuestionRerankUsages(signal),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [tokenSaved],
  );
  const questionReviewsFetcher = useCallback(
    (signal?: AbortSignal) => getQuestionReviews(signal),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [tokenSaved],
  );
  const strategySignalsFetcher = useCallback(
    (signal?: AbortSignal) => getStrategySignals(signal),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [tokenSaved],
  );
  const strategyUsagesFetcher = useCallback(
    (signal?: AbortSignal) => getStrategyUsages(signal),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [tokenSaved],
  );
  const strategyStatsFetcher = useCallback(
    (signal?: AbortSignal) => getStrategyStats(true, signal),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [tokenSaved],
  );
  const strategyRewardReadinessFetcher = useCallback(
    (signal?: AbortSignal) => getStrategyRewardReadiness(true, signal),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [tokenSaved],
  );
  const traceRollupFetcher = useCallback(
    (signal?: AbortSignal) => getTraceRollUp({ since: "24h", groupby: "health" }, signal),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [tokenSaved],
  );
  const fallbackRollupFetcher = useCallback(
    (signal?: AbortSignal) => getTraceRollUp({ since: "24h", groupby: "fallback" }, signal),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [tokenSaved],
  );
  const evidenceRollupFetcher = useCallback(
    (signal?: AbortSignal) => getEvidenceRollUp({ since: "24h" }, signal),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [tokenSaved],
  );
  const questionQualityRollupFetcher = useCallback(
    (signal?: AbortSignal) => getQuestionQualityRollUp({ since: "24h" }, signal),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [tokenSaved],
  );
  const recentTracesFetcher = useCallback(
    (signal?: AbortSignal) =>
      getRecentTracesByNode({ node: recentNode, limit: 30 }, signal),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [tokenSaved, recentNode],
  );
  const fallbackRatesFetcher = useCallback(
    (signal?: AbortSignal) => getFallbackRates(signal),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [tokenSaved],
  );

  const health = useAutoFetch(healthFetcher, tick);
  const bandit = useAutoFetch(banditFetcher, tick);
  const drift = useAutoFetch(driftFetcher, tick);
  const sessions = useAutoFetch(sessionsFetcher, tick);
  const history = useAutoFetch(historyFetcher, tick);
  const adminUsers = useAutoFetch(adminUsersFetcher, tick);
  const adminUserDetail = useAutoFetch(adminUserDetailFetcher, tick);
  const creditRequests = useAutoFetch(creditRequestsFetcher, tick);
  const userCredits = useAutoFetch(userCreditsFetcher, tick);
  const userCreditLedger = useAutoFetch(userCreditLedgerFetcher, tick);
  const strategies = useAutoFetch(strategiesFetcher, tick);
  const skillPlaybooks = useAutoFetch(skillPlaybooksFetcher, tick);
  const skillUsageStats = useAutoFetch(skillUsageStatsFetcher, tick);
  const skillRewardReadiness = useAutoFetch(skillRewardReadinessFetcher, tick);
  const questionSeeds = useAutoFetch(questionSeedsFetcher, tick);
  const questionUsages = useAutoFetch(questionUsagesFetcher, tick);
  const questionUsageStats = useAutoFetch(questionUsageStatsFetcher, tick);
  const questionRewardReadiness = useAutoFetch(questionRewardReadinessFetcher, tick);
  const questionRerankUsages = useAutoFetch(questionRerankUsagesFetcher, tick);
  const questionReviews = useAutoFetch(questionReviewsFetcher, tick);
  const strategySignals = useAutoFetch(strategySignalsFetcher, tick);
  const strategyUsages = useAutoFetch(strategyUsagesFetcher, tick);
  const strategyStats = useAutoFetch(strategyStatsFetcher, tick);
  const strategyRewardReadiness = useAutoFetch(strategyRewardReadinessFetcher, tick);
  const traceRollup = useAutoFetch(traceRollupFetcher, tick);
  const fallbackRollup = useAutoFetch(fallbackRollupFetcher, tick);
  const evidenceRollup = useAutoFetch(evidenceRollupFetcher, tick);
  const questionQualityRollup = useAutoFetch(questionQualityRollupFetcher, tick);
  const recentTraces = useAutoFetch(recentTracesFetcher, tick);
  const fallbackRates = useAutoFetch(fallbackRatesFetcher, tick);

  function handleSaveToken() {
    saveAdminToken(tokenInput);
    setTokenSaved(tokenInput);
    setTick((t) => t + 1);
  }

  function handleTabChange(tab: AdminTabId) {
    setActiveTab(tab);
    try {
      window.localStorage.setItem(ADMIN_ACTIVE_TAB_STORAGE_KEY, tab);
    } catch {
      // Tab switching should still work when storage is unavailable.
    }
  }

  useEffect(() => {
    if (userCredits.phase !== "ready") return;
    const users = userCredits.data.users;
    if (users.length === 0) {
      setSelectedCreditUserId(null);
      return;
    }
    if (!selectedCreditUserId || !users.some((user) => user.user_id === selectedCreditUserId)) {
      setSelectedCreditUserId(users[0].user_id);
    }
  }, [selectedCreditUserId, userCredits]);

  useEffect(() => {
    if (adminUsers.phase !== "ready") return;
    const users = adminUsers.data.users;
    if (users.length === 0) {
      setSelectedAdminUserId(null);
      return;
    }
    if (!selectedAdminUserId || !users.some((user) => user.id === selectedAdminUserId)) {
      setSelectedAdminUserId(users[0].id);
    }
  }, [adminUsers, selectedAdminUserId]);

  return (
    <div className="space-y-6">
      <TokenBar
        tokenInput={tokenInput}
        setTokenInput={setTokenInput}
        onSave={handleSaveToken}
        tokenSaved={tokenSaved}
        onRefresh={() => setTick((t) => t + 1)}
      />

      <SystemOverview
        health={health}
        bandit={bandit}
        drift={drift}
        sessions={sessions}
        strategies={strategies}
        browserHasLlmKey={browserHasLlmKey}
      />

      <div className="grid grid-cols-3 gap-1 rounded-xl border bg-muted/40 p-1">
        {ADMIN_TABS.map((theme) => (
          <button
            key={theme.id}
            onClick={() => handleTabChange(theme.id)}
            aria-pressed={activeTab === theme.id}
            className={cn(
              "flex items-center justify-center gap-1.5 rounded-lg border px-3 py-2 text-sm font-medium transition-colors active:scale-[0.98]",
              activeTab === theme.id ? theme.tabActive : theme.tabInactive,
            )}
          >
            <theme.icon
              className={cn(
                "h-3.5 w-3.5 transition-colors",
                activeTab === theme.id
                  ? theme.iconActive
                  : "text-muted-foreground/80",
              )}
            />
            {theme.label}
          </button>
        ))}
      </div>

      {activeTab === "health" && (
        <AdminTabPanel theme={ADMIN_TAB_THEMES.health}>
          <AdminHealthSection
            traceRollup={traceRollup}
            fallbackRollup={fallbackRollup}
            evidenceRollup={evidenceRollup}
            questionQualityRollup={questionQualityRollup}
            fallbackRates={fallbackRates}
            recentTraces={recentTraces}
            recentNode={recentNode}
            onRecentNodeChange={setRecentNode}
            sessions={sessions}
            history={history}
            historyPage={historyPage}
            historyFilters={historyFilters}
            historySearchText={historySearchText}
            adminUsers={adminUsers}
            adminUserDetail={adminUserDetail}
            selectedAdminUserId={selectedAdminUserId}
            accountSearchText={accountSearchText}
            accountStatusFilter={accountStatusFilter}
            accountRoleFilter={accountRoleFilter}
            accountPage={accountPage}
            creditRequests={creditRequests}
            creditRequestSearchText={creditRequestSearchText}
            creditRequestStatusFilter={creditRequestStatusFilter}
            userCredits={userCredits}
            userCreditLedger={userCreditLedger}
            selectedCreditUserId={selectedCreditUserId}
            creditSearchText={creditSearchText}
            onSelectedAdminUserIdChange={setSelectedAdminUserId}
            onAccountSearchTextChange={setAccountSearchText}
            onAccountStatusFilterChange={setAccountStatusFilter}
            onAccountRoleFilterChange={setAccountRoleFilter}
            onAccountPageChange={setAccountPage}
            onCreditRequestSearchTextChange={setCreditRequestSearchText}
            onCreditRequestStatusFilterChange={setCreditRequestStatusFilter}
            onSelectedCreditUserIdChange={setSelectedCreditUserId}
            onCreditSearchTextChange={setCreditSearchText}
            onHistoryPageChange={setHistoryPage}
            onHistoryFiltersChange={setHistoryFilters}
            onHistorySearchTextChange={setHistorySearchText}
            onRefresh={() => setTick((t) => t + 1)}
          />
        </AdminTabPanel>
      )}

      {activeTab === "scoring" && (
        <AdminTabPanel theme={ADMIN_TAB_THEMES.scoring}>
          <AdminScoringSection
            evidenceRollup={evidenceRollup}
            questionQualityRollup={questionQualityRollup}
            drift={drift}
          />
        </AdminTabPanel>
      )}

      {activeTab === "strategy" && (
        <AdminTabPanel theme={ADMIN_TAB_THEMES.strategy}>
          <AdminStrategySection
            bandit={bandit}
            questionSeeds={questionSeeds}
            questionUsages={questionUsages}
            questionUsageStats={questionUsageStats}
            questionUsageStatsPage={questionUsageStatsPage}
            onQuestionUsageStatsPageChange={setQuestionUsageStatsPage}
            questionRewardReadiness={questionRewardReadiness}
            questionRerankUsages={questionRerankUsages}
            questionReviews={questionReviews}
            skillPlaybooks={skillPlaybooks}
            skillUsageStats={skillUsageStats}
            skillUsageStatsPage={skillUsageStatsPage}
            onSkillUsageStatsPageChange={setSkillUsageStatsPage}
            skillRewardReadiness={skillRewardReadiness}
            strategies={strategies}
            strategySignals={strategySignals}
            strategyUsages={strategyUsages}
            strategyStats={strategyStats}
            strategyRewardReadiness={strategyRewardReadiness}
            onRefresh={() => setTick((t) => t + 1)}
          />
        </AdminTabPanel>
      )}
    </div>
  );
}

function formatAdminUserStatus(status: string): string {
  if (status === "active") return "可用";
  if (status === "disabled") return "已禁用";
  return status || "未知";
}

function formatAdminUserRole(role: string): string {
  if (role === "admin") return "管理员";
  if (role === "user") return "普通用户";
  return role || "未知";
}

function formatOptionalAdminTime(value?: string | null): string {
  return value ? formatDateTime(value) : "—";
}

function formatAdminCreditRequestStatus(status: AdminCreditRequest["status"]): string {
  if (status === "pending") return "待处理";
  if (status === "approved") return "已批准";
  if (status === "rejected") return "已拒绝";
  return status;
}

function CreditRequestsPanel({
  requests,
  searchText,
  statusFilter,
  onSearchTextChange,
  onStatusFilterChange,
  onRefresh,
}: {
  requests: Loadable<AdminCreditRequestsResponse>;
  searchText: string;
  statusFilter: string;
  onSearchTextChange: (text: string) => void;
  onStatusFilterChange: (status: string) => void;
  onRefresh: () => void;
}) {
  const { toast } = useToast();
  const [pendingId, setPendingId] = useState<number | null>(null);

  async function handleDecision(
    request: AdminCreditRequest,
    status: "approved" | "rejected",
  ) {
    const reason =
      status === "approved"
        ? `批准 ${request.user_email || `user_id ${request.user_id}`} 的额度申请`
        : `拒绝 ${request.user_email || `user_id ${request.user_id}`} 的额度申请`;
    setPendingId(request.id);
    try {
      await decideAdminCreditRequest(request.id, { status, reason });
      toast({
        title: status === "approved" ? "申请已批准" : "申请已拒绝",
        description:
          status === "approved"
            ? `已补充 ${request.requested_amount} 次平台面试次数。`
            : "该申请不会改动用户额度。",
      });
      onRefresh();
    } catch (err) {
      toast({
        title: "处理额度申请失败",
        description: err instanceof Error ? err.message : "请稍后再试",
        variant: "destructive",
      });
    } finally {
      setPendingId(null);
    }
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <WalletCards className="h-4 w-4 text-emerald-400" />
              额度申请
            </CardTitle>
            <CardDescription className="mt-1">
              处理用户提交的补充次数申请；批准后会写入现有额度账本。
            </CardDescription>
          </div>
          <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_9rem] lg:w-[30rem]">
            <div className="relative">
              <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input
                value={searchText}
                onChange={(event) => onSearchTextChange(event.target.value)}
                placeholder="按邮箱搜索申请"
                className="pl-8"
              />
            </div>
            <label className="space-y-1 text-xs text-muted-foreground">
              <span>状态筛选</span>
              <select
                value={statusFilter}
                onChange={(event) => onStatusFilterChange(event.target.value)}
                className="h-10 w-full rounded-md border bg-background px-3 text-sm text-foreground"
              >
                <option value="">全部</option>
                <option value="pending">待处理</option>
                <option value="approved">已批准</option>
                <option value="rejected">已拒绝</option>
              </select>
            </label>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {requests.phase === "loading" && <LoadingList rows={3} />}
        {requests.phase === "error" && <ErrorBox message={requests.message} />}
        {requests.phase === "ready" && requests.data.requests.length === 0 && (
          <p className="rounded-lg border border-dashed px-3 py-4 text-sm text-muted-foreground">
            暂无匹配的额度申请。
          </p>
        )}
        {requests.phase === "ready" &&
          requests.data.requests.map((request) => (
            <div
              key={request.id}
              className="rounded-lg border bg-background px-3 py-3 text-sm"
            >
              <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="truncate font-medium">
                      {request.user_email || `user_id ${request.user_id}`}
                    </p>
                    <Badge
                      variant={
                        request.status === "pending"
                          ? "secondary"
                          : request.status === "approved"
                            ? "outline"
                            : "destructive"
                      }
                    >
                      {formatAdminCreditRequestStatus(request.status)}
                    </Badge>
                    <Badge variant="outline">申请 {request.requested_amount} 次</Badge>
                  </div>
                  <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">
                    {request.reason}
                  </p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    提交于 {formatOptionalAdminTime(request.created_at)}
                    {request.decision_reason
                      ? ` · 处理意见：${request.decision_reason}`
                      : ""}
                  </p>
                </div>
                {request.status === "pending" ? (
                  <div className="flex shrink-0 gap-2">
                    <Button
                      type="button"
                      size="sm"
                      className="gap-2"
                      disabled={pendingId === request.id}
                      onClick={() => void handleDecision(request, "approved")}
                    >
                      {pendingId === request.id && (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      )}
                      批准申请
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      disabled={pendingId === request.id}
                      onClick={() => void handleDecision(request, "rejected")}
                    >
                      拒绝申请
                    </Button>
                  </div>
                ) : (
                  <div className="shrink-0 rounded-md border bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
                    {request.status === "approved"
                      ? `已补充 ${request.requested_amount} 次`
                      : "未改动额度"}
                  </div>
                )}
              </div>
            </div>
          ))}
      </CardContent>
    </Card>
  );
}

function AccountManagementPanel({
  users,
  detail,
  selectedUserId,
  searchText,
  statusFilter,
  roleFilter,
  page,
  pageSize,
  onSelectedUserIdChange,
  onSearchTextChange,
  onStatusFilterChange,
  onRoleFilterChange,
  onPageChange,
  onRefresh,
}: {
  users: Loadable<AdminUserListResponse>;
  detail: Loadable<AdminUserDetail | null>;
  selectedUserId: number | null;
  searchText: string;
  statusFilter: string;
  roleFilter: string;
  page: number;
  pageSize: number;
  onSelectedUserIdChange: (userId: number) => void;
  onSearchTextChange: (text: string) => void;
  onStatusFilterChange: (status: string) => void;
  onRoleFilterChange: (role: string) => void;
  onPageChange: (page: number) => void;
  onRefresh: () => void;
}) {
  const { toast } = useToast();
  const [confirmEmail, setConfirmEmail] = useState("");
  const [pending, setPending] = useState(false);
  const usersData = users.phase === "ready" ? users.data : null;
  const selectedFromList =
    usersData?.users.find((user) => user.id === selectedUserId) ?? null;
  const selectedUser =
    detail.phase === "ready" && detail.data ? detail.data.user : selectedFromList;
  const isAdminTarget = selectedUser?.role === "admin";
  const nextStatus =
    selectedUser?.status === "disabled" ? "active" : "disabled";
  const actionLabel = nextStatus === "disabled" ? "禁用账号" : "启用账号";
  const confirmationMatches =
    !!selectedUser &&
    confirmEmail.trim().toLowerCase() === selectedUser.email.toLowerCase();
  const canGoNext =
    !!usersData && usersData.offset + usersData.count < usersData.total_count;

  async function handleStatusChange() {
    if (!selectedUser || isAdminTarget) return;
    if (!confirmationMatches) {
      toast({
        title: "输入邮箱确认后再操作",
        description: `请完整输入 ${selectedUser.email}`,
        variant: "destructive",
      });
      return;
    }
    setPending(true);
    try {
      await updateAdminUserStatus(selectedUser.id, {
        status: nextStatus,
        reason:
          nextStatus === "disabled"
            ? `admin disabled account ${selectedUser.email}`
            : `admin re-enabled account ${selectedUser.email}`,
      });
      toast({
        title: nextStatus === "disabled" ? "账号已禁用" : "账号已启用",
        description:
          nextStatus === "disabled"
            ? "该用户将无法继续使用登录态访问账号能力；已有面试记录不会删除。"
            : "该用户可以重新使用账号能力。",
      });
      setConfirmEmail("");
      onRefresh();
    } catch (err) {
      toast({
        title: "账号状态更新失败",
        description: err instanceof Error ? err.message : "请稍后再试",
        variant: "destructive",
      });
    } finally {
      setPending(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <Users className="h-4 w-4 text-emerald-400" />
              账号管理
            </CardTitle>
            <CardDescription className="mt-1">
              查询平台用户、查看额度和账号记录概况，并启用或禁用普通用户。
            </CardDescription>
          </div>
          <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_9rem_9rem] lg:w-[42rem]">
            <div className="relative">
              <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input
                value={searchText}
                onChange={(event) => onSearchTextChange(event.target.value)}
                placeholder="按邮箱搜索账号"
                className="pl-8"
              />
            </div>
            <label className="space-y-1 text-xs text-muted-foreground">
              <span>状态筛选</span>
              <select
                value={statusFilter}
                onChange={(event) => onStatusFilterChange(event.target.value)}
                className="h-10 w-full rounded-md border bg-background px-3 text-sm text-foreground"
              >
                <option value="">全部状态</option>
                <option value="active">可用</option>
                <option value="disabled">已禁用</option>
              </select>
            </label>
            <label className="space-y-1 text-xs text-muted-foreground">
              <span>角色筛选</span>
              <select
                value={roleFilter}
                onChange={(event) => onRoleFilterChange(event.target.value)}
                className="h-10 w-full rounded-md border bg-background px-3 text-sm text-foreground"
              >
                <option value="">全部角色</option>
                <option value="user">普通用户</option>
                <option value="admin">管理员</option>
              </select>
            </label>
          </div>
        </div>
      </CardHeader>
      <CardContent className="grid gap-4 xl:grid-cols-[minmax(0,1.15fr)_minmax(22rem,0.85fr)]">
        <div className="space-y-3">
          {users.phase === "loading" && <LoadingList rows={4} />}
          {users.phase === "error" && <ErrorBox message={users.message} />}
          {usersData && usersData.users.length === 0 && (
            <p className="rounded-lg border border-dashed px-3 py-4 text-sm text-muted-foreground">
              暂无匹配账号。
            </p>
          )}
          {usersData?.users.map((user) => (
            <AdminUserRow
              key={user.id}
              user={user}
              active={user.id === selectedUserId}
              onClick={() => onSelectedUserIdChange(user.id)}
            />
          ))}
          {usersData && usersData.total_count > pageSize && (
            <div className="flex items-center justify-between gap-3 text-xs text-muted-foreground">
              <span>
                第 {page + 1} 页 · 共 {usersData.total_count} 个账号
              </span>
              <div className="flex gap-2">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={page <= 0}
                  onClick={() => onPageChange(Math.max(0, page - 1))}
                >
                  上一页
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={!canGoNext}
                  onClick={() => onPageChange(page + 1)}
                >
                  下一页
                </Button>
              </div>
            </div>
          )}
        </div>

        <div className="space-y-3 rounded-lg border bg-muted/20 p-3">
          {!selectedUser && (
            <p className="text-sm text-muted-foreground">
              选择一个账号后查看详情、最近流水和最近账号记录。
            </p>
          )}
          {selectedUser && (
            <>
              <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold">{selectedUser.email}</p>
                  <p className="text-xs text-muted-foreground">
                    user_id {selectedUser.id} · {formatAdminUserRole(selectedUser.role)} ·{" "}
                    {formatAdminUserStatus(selectedUser.status)}
                  </p>
                </div>
                <Badge variant={selectedUser.status === "disabled" ? "destructive" : "outline"}>
                  {formatAdminUserStatus(selectedUser.status)}
                </Badge>
              </div>
              <div className="grid gap-2 text-xs sm:grid-cols-2">
                <div className="rounded-md border bg-background px-3 py-2">
                  <p className="text-muted-foreground">剩余额度</p>
                  <p className="mt-1 text-lg font-semibold">
                    {selectedUser.credit_balance} 次
                  </p>
                </div>
                <div className="rounded-md border bg-background px-3 py-2">
                  <p className="text-muted-foreground">账号记录</p>
                  <p className="mt-1 text-lg font-semibold">
                    {selectedUser.interview_session_count} 场
                  </p>
                </div>
                <div className="rounded-md border bg-background px-3 py-2">
                  <p className="text-muted-foreground">最近活跃</p>
                  <p className="mt-1 font-medium">
                    {formatOptionalAdminTime(selectedUser.last_seen_at)}
                  </p>
                </div>
                <div className="rounded-md border bg-background px-3 py-2">
                  <p className="text-muted-foreground">注册时间</p>
                  <p className="mt-1 font-medium">
                    {formatOptionalAdminTime(selectedUser.created_at)}
                  </p>
                </div>
              </div>
              {detail.phase === "loading" && <LoadingList rows={3} />}
              {detail.phase === "error" && <ErrorBox message={detail.message} />}
              {detail.phase === "ready" && detail.data && (
                <div className="space-y-3">
                  <div>
                    <p className="text-xs font-medium text-muted-foreground">
                      最近额度流水
                    </p>
                    <div className="mt-2 space-y-2">
                      {detail.data.recent_credit_entries.length === 0 && (
                        <p className="text-sm text-muted-foreground">
                          暂无额度流水。
                        </p>
                      )}
                      {detail.data.recent_credit_entries.slice(0, 4).map((entry) => {
                        const formatted = formatCreditLedgerEntry(entry);
                        return (
                          <div
                            key={entry.id}
                            className="flex items-start justify-between gap-3 rounded-md border bg-background px-3 py-2 text-xs"
                          >
                            <div className="min-w-0">
                              <p className="font-medium">
                                {formatted.title} · {formatted.deltaLabel}
                              </p>
                              <p className="truncate text-muted-foreground">
                                {formatted.description}
                              </p>
                            </div>
                            <div className="shrink-0 text-right text-muted-foreground">
                              <p>{formatted.balanceLabel}</p>
                              {entry.created_at && <p>{formatDateTime(entry.created_at)}</p>}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                  <div>
                    <p className="text-xs font-medium text-muted-foreground">
                      最近账号记录
                    </p>
                    <div className="mt-2 space-y-2">
                      {detail.data.recent_interview_sessions.length === 0 && (
                        <p className="text-sm text-muted-foreground">
                          暂无账号归属面试记录。
                        </p>
                      )}
                      {detail.data.recent_interview_sessions.slice(0, 4).map((session) => (
                        <div
                          key={session.session_id}
                          className="rounded-md border bg-background px-3 py-2 text-xs"
                        >
                          <div className="flex items-start justify-between gap-3">
                            <div className="min-w-0">
                              <p className="truncate font-medium">
                                {session.job_title || "未命名面试"}
                              </p>
                              <p className="truncate text-muted-foreground">
                                {session.candidate_name || "候选人未填"} ·{" "}
                                {session.status}
                              </p>
                            </div>
                            <div className="shrink-0 text-right text-muted-foreground">
                              <p>
                                {typeof session.overall_score === "number"
                                  ? `${session.overall_score}/10`
                                  : "无报告"}
                              </p>
                              <p>{formatOptionalAdminTime(session.updated_at)}</p>
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              )}
              <Separator />
              {isAdminTarget ? (
                <div className="rounded-md border border-amber-500/25 bg-amber-500/10 px-3 py-2 text-sm text-amber-700 dark:text-amber-200">
                  <div className="flex items-center gap-2 font-medium">
                    <ShieldCheck className="h-4 w-4" />
                    admin 账号只读保护
                  </div>
                  <p className="mt-1 text-xs">
                    管理员账号不支持在此启用或禁用；管理员提升继续走后端脚本。
                  </p>
                </div>
              ) : (
                <div className="space-y-2">
                  <label className="space-y-1 text-xs text-muted-foreground">
                    <span>输入邮箱确认</span>
                    <Input
                      value={confirmEmail}
                      onChange={(event) => setConfirmEmail(event.target.value)}
                      placeholder={selectedUser.email}
                    />
                  </label>
                  <Button
                    type="button"
                    variant={nextStatus === "disabled" ? "destructive" : "outline"}
                    className="w-full gap-2"
                    disabled={pending || !confirmationMatches}
                    onClick={() => void handleStatusChange()}
                  >
                    {pending && <Loader2 className="h-4 w-4 animate-spin" />}
                    {actionLabel}
                  </Button>
                  <p className="text-xs text-muted-foreground">
                    禁用后该用户将无法继续使用登录态访问账号能力；已有面试记录不删除。
                  </p>
                </div>
              )}
            </>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function AdminUserRow({
  user,
  active,
  onClick,
}: {
  user: AdminUserItem;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "w-full rounded-lg border px-3 py-3 text-left text-sm transition-colors",
        active
          ? "border-emerald-500/40 bg-emerald-500/10"
          : "bg-background hover:bg-accent",
      )}
    >
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <p className="truncate font-medium">{user.email}</p>
            <Badge variant="outline">{formatAdminUserRole(user.role)}</Badge>
            <Badge variant={user.status === "disabled" ? "destructive" : "secondary"}>
              {formatAdminUserStatus(user.status)}
            </Badge>
          </div>
          <p className="mt-1 text-xs text-muted-foreground">
            最近活跃 {formatOptionalAdminTime(user.last_seen_at)} · 注册{" "}
            {formatOptionalAdminTime(user.created_at)}
          </p>
        </div>
        <div className="grid shrink-0 grid-cols-2 gap-2 text-xs text-muted-foreground sm:min-w-56">
          <div className="rounded-md border bg-muted/30 px-2 py-1.5">
            <p>额度</p>
            <p className="text-sm font-semibold text-foreground">
              {user.credit_balance} 次
            </p>
          </div>
          <div className="rounded-md border bg-muted/30 px-2 py-1.5">
            <p>账号记录</p>
            <p className="text-sm font-semibold text-foreground">
              {user.interview_session_count} 场
            </p>
          </div>
        </div>
      </div>
    </button>
  );
}

function UserCreditsPanel({
  users,
  ledger,
  selectedUserId,
  searchText,
  onSelectedUserIdChange,
  onSearchTextChange,
  onRefresh,
}: {
  users: Loadable<AdminUserCreditsResponse>;
  ledger: Loadable<AdminUserCreditLedgerResponse>;
  selectedUserId: number | null;
  searchText: string;
  onSelectedUserIdChange: (userId: number) => void;
  onSearchTextChange: (text: string) => void;
  onRefresh: () => void;
}) {
  const { toast } = useToast();
  const [amount, setAmount] = useState("1");
  const [reason, setReason] = useState("手动赠送");
  const [pending, setPending] = useState(false);
  const selectedUser =
    users.phase === "ready"
      ? users.data.users.find((user) => user.user_id === selectedUserId) ?? null
      : null;
  const amountDelta = Number.parseInt(amount, 10);
  const hasValidAmount = Number.isFinite(amountDelta) && amountDelta !== 0;
  const adjustmentPreviewBalance =
    selectedUser && hasValidAmount ? selectedUser.balance + amountDelta : null;

  async function handleAdjustCredits() {
    if (!selectedUser) return;
    if (!hasValidAmount) {
      toast({ title: "请输入非 0 整数", variant: "destructive" });
      return;
    }
    const nextBalance = selectedUser.balance + amountDelta;
    if (nextBalance < 0) {
      toast({ title: "调整后余额不能为负数", variant: "destructive" });
      return;
    }
    if (!reason.trim()) {
      toast({ title: "请填写调整原因", variant: "destructive" });
      return;
    }
    setPending(true);
    try {
      const result = await adjustAdminUserCredits(selectedUser.user_id, {
        amount_delta: amountDelta,
        reason: reason.trim(),
      });
      toast({
        title: amountDelta > 0 ? "已手动赠送次数" : "已调整用户次数",
        description: `${selectedUser.email} 当前余额 ${result.balance} 次。`,
      });
      onRefresh();
    } catch (err) {
      toast({
        title: "调整失败",
        description: err instanceof Error ? err.message : "请稍后再试",
        variant: "destructive",
      });
    } finally {
      setPending(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <Key className="h-4 w-4 text-emerald-400" />
              用户额度
            </CardTitle>
            <CardDescription className="mt-1">
              查看账号免费次数、最近账本，并在内测或补偿时手动赠送。
            </CardDescription>
          </div>
          <div className="relative w-full sm:w-72">
            <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
            <Input
              value={searchText}
              onChange={(event) => onSearchTextChange(event.target.value)}
              placeholder="按邮箱搜索"
              className="pl-8"
            />
          </div>
        </div>
      </CardHeader>
      <CardContent className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
        <div className="space-y-2">
          {users.phase === "loading" && <LoadingList rows={3} />}
          {users.phase === "error" && <ErrorBox message={users.message} />}
          {users.phase === "ready" && users.data.users.length === 0 && (
            <p className="rounded-lg border border-dashed px-3 py-4 text-sm text-muted-foreground">
              暂无匹配用户。
            </p>
          )}
          {users.phase === "ready" &&
            users.data.users.map((user) => (
              <UserCreditRow
                key={user.user_id}
                user={user}
                active={user.user_id === selectedUserId}
                onClick={() => onSelectedUserIdChange(user.user_id)}
              />
            ))}
        </div>

        <div className="space-y-3 rounded-lg border bg-muted/20 p-3">
          {selectedUser ? (
            <>
              <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <p className="text-sm font-medium">{selectedUser.email}</p>
                  <p className="text-xs text-muted-foreground">
                    当前余额 {selectedUser.balance} 次 · {selectedUser.status}
                    {selectedUser.updated_at
                      ? ` · 最后更新 ${formatDateTime(selectedUser.updated_at)}`
                      : ""}
                  </p>
                </div>
                <Badge variant="outline">user_id {selectedUser.user_id}</Badge>
              </div>
              <div className="grid gap-2 sm:grid-cols-[7rem_minmax(0,1fr)_auto]">
                <Input
                  value={amount}
                  onChange={(event) => setAmount(event.target.value)}
                  inputMode="numeric"
                  placeholder="+3 / -1"
                />
                <Input
                  value={reason}
                  onChange={(event) => setReason(event.target.value)}
                  placeholder="调整原因"
                />
                <Button
                  type="button"
                  onClick={() => void handleAdjustCredits()}
                  disabled={pending}
                  className="gap-2"
                >
                  {pending && <Loader2 className="h-4 w-4 animate-spin" />}
                  手动赠送
                </Button>
              </div>
              <p
                className={
                  adjustmentPreviewBalance !== null && adjustmentPreviewBalance < 0
                    ? "text-xs text-destructive"
                    : "text-xs text-muted-foreground"
                }
              >
                调整后余额：
                {adjustmentPreviewBalance !== null
                  ? `${adjustmentPreviewBalance} 次`
                  : "请输入调整次数"}
              </p>
              <div className="space-y-2">
                <p className="text-xs font-medium text-muted-foreground">最近账本</p>
                {ledger.phase === "loading" && <LoadingList rows={3} />}
                {ledger.phase === "error" && <ErrorBox message={ledger.message} />}
                {ledger.phase === "ready" && ledger.data.entries.length === 0 && (
                  <p className="text-sm text-muted-foreground">暂无账本记录。</p>
                )}
                {ledger.phase === "ready" &&
                  ledger.data.entries.slice(0, 6).map((entry) => {
                    const formatted = formatCreditLedgerEntry(entry);
                    return (
                      <div
                        key={entry.id}
                        className="flex items-start justify-between gap-3 rounded-md border bg-background px-3 py-2 text-xs"
                      >
                        <div className="min-w-0">
                          <p className="font-medium">
                            {formatted.title} · {formatted.deltaLabel}
                          </p>
                          <p className="truncate text-muted-foreground">
                            {formatted.description}
                          </p>
                        </div>
                        <div className="shrink-0 text-right text-muted-foreground">
                          <p>{formatted.balanceLabel}</p>
                          {entry.created_at && <p>{formatDateTime(entry.created_at)}</p>}
                        </div>
                      </div>
                    );
                  })}
              </div>
            </>
          ) : (
            <p className="text-sm text-muted-foreground">
              选择一个用户后查看账本和调整额度。
            </p>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function UserCreditRow({
  user,
  active,
  onClick,
}: {
  user: AdminUserCredit;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "w-full rounded-lg border px-3 py-2 text-left text-sm transition-colors",
        active
          ? "border-emerald-500/40 bg-emerald-500/10"
          : "bg-background hover:bg-accent",
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate font-medium">{user.email}</p>
          <p className="text-xs text-muted-foreground">
            {user.role} · {user.status}
            {user.updated_at ? ` · 最后更新 ${formatDateTime(user.updated_at)}` : ""}
          </p>
        </div>
        <Badge variant={user.balance > 0 ? "success" : "warn"}>
          {user.balance} 次
        </Badge>
      </div>
    </button>
  );
}

// TraceHealthRollUp pins the answer to "今日有多少场面试 trace 健康 / 部分 / 缺失"
// at the top of the dashboard. The 15s auto-refresh keeps it useful as
// a passive ops indicator; degraded states bubble up via the badge
// colour so the operator does not have to scroll the long sessions
// table to notice.
const HEALTH_LABEL: Record<string, string> = {
  complete: "完整",
  partial: "部分",
  missing: "缺失",
};
const HEALTH_TONE: Record<string, "success" | "warn" | "destructive" | "outline"> = {
  complete: "success",
  partial: "warn",
  missing: "destructive",
};

function InterviewQualityOverview({
  trace,
  fallback,
  evidence,
  question,
}: {
  trace: Loadable<TraceRollupResponse>;
  fallback: Loadable<TraceRollupResponse>;
  evidence: Loadable<EvidenceRollupResponse>;
  question: Loadable<QuestionQualityRollupResponse>;
}) {
  if (
    trace.phase === "loading" ||
    fallback.phase === "loading" ||
    evidence.phase === "loading" ||
    question.phase === "loading"
  ) {
    return <Skeleton className="h-28 w-full" />;
  }
  const errors = [trace, fallback, evidence, question].filter(
    (s): s is { phase: "error"; message: string } => s.phase === "error",
  );
  if (errors.length > 0) {
    return (
      <Card className="border-destructive/40 bg-destructive/5">
        <CardContent className="space-y-1 pt-6 text-sm">
          <p className="font-medium text-destructive">面试主链路质量总览加载失败</p>
          <p className="text-xs text-muted-foreground">{errors[0].message}</p>
        </CardContent>
      </Card>
    );
  }
  if (
    trace.phase !== "ready" ||
    fallback.phase !== "ready" ||
    evidence.phase !== "ready" ||
    question.phase !== "ready"
  ) {
    return null;
  }

  const traceData = trace.data;
  const fallbackData = fallback.data;
  const evidenceData = evidence.data;
  const questionData = question.data;
  const missingTraceShare = bucketShare(traceData, "missing");
  const partialTraceShare = bucketShare(traceData, "partial");
  const supportedEvidenceRate =
    evidenceData.yes_checks === 0
      ? null
      : Math.max(0, 1 - evidenceData.unsupported_yes_rate);
  const evidenceRateValue =
    evidenceData.total_evaluator_traces === 0
      ? "无 Trace"
      : supportedEvidenceRate === null
        ? "无通过项"
        : formatPercent(supportedEvidenceRate);
  const contractRateValue =
    questionData.total_ask_question_traces === 0
      ? "无 Trace"
      : formatPercent(questionData.contract_rate);
  const qualityLevel =
    missingTraceShare > 0 ||
    (fallbackData.fallback_rate ?? 0) >= 0.3 ||
    supportedEvidenceRate === null ||
    supportedEvidenceRate < 0.8 ||
    questionData.contract_rate < 0.8
      ? "red"
      : partialTraceShare > 0 ||
          (fallbackData.fallback_rate ?? 0) > 0 ||
          supportedEvidenceRate < 0.95 ||
          questionData.contract_rate < 0.95
        ? "yellow"
        : "green";
  const tone =
    qualityLevel === "green" ? "success" : qualityLevel === "yellow" ? "warn" : "destructive";
  const label =
    qualityLevel === "green" ? "健康" : qualityLevel === "yellow" ? "关注" : "风险";

  return (
    <Card className={qualityLevel === "red" ? "border-destructive/40 bg-destructive/5" : ""}>
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <Activity className="h-4 w-4 text-emerald-400" />
              面试主链路质量总览
            </CardTitle>
            <CardDescription className="mt-1">
              汇总 Trace 健康、fallback、评分证据和问题质量支撑，先做运营预警，不替代人工抽查。
            </CardDescription>
            <p className="mt-1 text-xs text-muted-foreground">
              口径：最近 24h 创建的面试 session；评分兜底来自 final_report，评分证据与出题契约来自 generation_traces。
            </p>
          </div>
          <Badge variant={tone} className="font-mono">
            {label}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="grid gap-3 md:grid-cols-4">
        <StatBox label="评分兜底率" value={formatPercent(fallbackData.fallback_rate ?? 0)} />
        <StatBox
          label="评分证据率"
          value={evidenceRateValue}
        />
        <StatBox label="出题契约率" value={contractRateValue} />
        <StatBox label="Trace 缺失率" value={formatPercent(missingTraceShare)} />
      </CardContent>
    </Card>
  );
}

function TraceHealthRollUp({ state }: { state: Loadable<TraceRollupResponse> }) {
  if (state.phase === "loading") {
    return <Skeleton className="h-24 w-full" />;
  }
  if (state.phase === "error") {
    return (
      <Card className="border-destructive/40 bg-destructive/5">
        <CardContent className="space-y-1 pt-6 text-sm">
          <p className="font-medium text-destructive">Trace 健康度加载失败</p>
          <p className="text-xs text-muted-foreground">{state.message}</p>
        </CardContent>
      </Card>
    );
  }
  const data = state.data;
  const totalForShare = data.buckets.reduce((sum, b) => sum + b.count, 0) || 1;
  return (
    <Card>
      <CardHeader>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <CardTitle className="flex items-center gap-2 text-base">
              <Activity className="h-4 w-4 text-emerald-400" />
              Trace 健康度（24 小时）
            </CardTitle>
            <CardDescription className="mt-1 max-w-3xl">
              聚合最近 24 小时的 generation_traces 与 interview_sessions，颜色与 Trace Explorer 一致。
            </CardDescription>
          </div>
          <Badge variant="outline" className="shrink-0 whitespace-nowrap font-mono text-[10px]">
            共 {data.total_sessions} 场
          </Badge>
        </div>
      </CardHeader>
      <CardContent>
        {data.total_sessions === 0 ? (
          <p className="text-sm text-muted-foreground">
            过去 24 小时还没有面试记录。等一场面试跑完后这里会出现统计。
          </p>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {data.buckets.map((bucket) => (
              <div key={bucket.key} className="rounded-lg border bg-card/50 p-3">
                <div className="mb-2 flex items-center justify-between gap-2">
                  <p className="text-xs text-muted-foreground">
                    {HEALTH_LABEL[bucket.key] ?? bucket.key}
                  </p>
                  <Badge variant={HEALTH_TONE[bucket.key] ?? "outline"}>
                    {Math.round((bucket.count / totalForShare) * 100)}%
                  </Badge>
                </div>
                <p className="text-2xl font-semibold">{bucket.count}</p>
                <p className="mt-1 text-[11px] text-muted-foreground">
                  {bucket.key === "complete"
                    ? "走完整闭环（评分 + 学习节点 + completed）"
                    : bucket.key === "partial"
                      ? "节点缺失或会话未到 completed"
                      : bucket.key === "missing"
                        ? "无任何 generation_traces 记录"
                        : "其它"}
                </p>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function bucketShare(data: TraceRollupResponse, key: string): number {
  return data.buckets.find((bucket) => bucket.key === key)?.share ?? 0;
}

function FallbackRollUp({ state }: { state: Loadable<TraceRollupResponse> }) {
  if (state.phase === "loading") {
    return <Skeleton className="h-24 w-full" />;
  }
  if (state.phase === "error") {
    return (
      <Card className="border-destructive/40 bg-destructive/5">
        <CardContent className="space-y-1 pt-6 text-sm">
          <p className="font-medium text-destructive">评分 fallback 加载失败</p>
          <p className="text-xs text-muted-foreground">{state.message}</p>
        </CardContent>
      </Card>
    );
  }
  const data = state.data;
  const fallbackRate = data.fallback_rate ?? 0;
  const affectedSessions = data.affected_sessions ?? 0;
  const fallbackTurns = data.fallback_turns ?? 0;
  const totalTurns = data.total_turns ?? 0;
  const fallbackBadgeLabel =
    fallbackRate > 0 ? `兜底率 ${formatPercent(fallbackRate)}` : "无兜底";
  return (
    <Card className={fallbackRate >= 0.3 ? "border-amber-500/40 bg-amber-500/[0.04]" : ""}>
      <CardHeader>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <CardTitle className="flex items-center gap-2 text-base">
              <AlertTriangle className="h-4 w-4 text-amber-300" />
              评分 fallback（24 小时）
            </CardTitle>
            <CardDescription className="mt-1 max-w-3xl">
              聚合 final_report 的 evaluator_fallback_count，观察评估模型是否持续退化。
            </CardDescription>
          </div>
          <Badge
            variant={fallbackRate >= 0.3 ? "warn" : "outline"}
            className="shrink-0 whitespace-nowrap font-mono"
          >
            {fallbackBadgeLabel}
          </Badge>
        </div>
      </CardHeader>
      <CardContent>
        {data.total_sessions === 0 ? (
          <p className="text-sm text-muted-foreground">
            过去 24 小时还没有可统计的面试报告。
          </p>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            <StatBox label="兜底轮次" value={`${fallbackTurns}/${totalTurns}`} />
            <StatBox label="影响会话" value={`${affectedSessions}/${data.total_sessions}`} />
            <StatBox label="兜底率" value={formatPercent(fallbackRate)} />
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// FallbackKindCounts shows the in-process per-kind fallback Counter
// (since process boot). It complements the trace-database
// ``FallbackRollUp`` above, which only counts evaluator turns from
// the last 24h. By breaking the count down per *kind* we let the
// operator answer "which fallback is firing right now?" without
// scraping Prometheus.
//
// Tone is set per-kind so a spike in any single kind stays visible
// at a glance: safety→destructive, language→info-blue,
// duplicate→accent-purple, contract_unsigned→amber,
// evaluator_fallback→warning-yellow.
const FALLBACK_KIND_TONE: Record<FallbackKind, string> = {
  safety: "border-red-500/40 bg-red-500/[0.06]",
  language: "border-sky-500/40 bg-sky-500/[0.06]",
  duplicate: "border-purple-500/40 bg-purple-500/[0.06]",
  contract_unsigned: "border-amber-500/40 bg-amber-500/[0.06]",
  evaluator_fallback: "border-yellow-500/40 bg-yellow-500/[0.06]",
};
const FALLBACK_KIND_TEXT: Record<FallbackKind, string> = {
  safety: "text-red-400",
  language: "text-sky-400",
  duplicate: "text-purple-400",
  contract_unsigned: "text-amber-400",
  evaluator_fallback: "text-yellow-400",
};

function FallbackKindCounts({ state }: { state: Loadable<FallbackRatesResponse> }) {
  if (state.phase === "loading") {
    return <Skeleton className="h-32 w-full" />;
  }
  if (state.phase === "error") {
    return (
      <Card className="border-destructive/40 bg-destructive/5">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <AlertTriangle className="h-4 w-4 text-destructive" />
            Fallback 详细计数加载失败
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-xs text-muted-foreground">{state.message}</p>
        </CardContent>
      </Card>
    );
  }
  const counts = state.data.fallback_counts ?? {};
  const knownTotal = FALLBACK_KIND_ORDER.reduce(
    (sum, kind) => sum + (counts[kind] ?? 0),
    0,
  );
  const extraEntries = Object.entries(counts).filter(
    ([kind]) => !(FALLBACK_KIND_ORDER as readonly string[]).includes(kind),
  );
  const extraTotal = extraEntries.reduce((sum, [, n]) => sum + n, 0);
  const grandTotal = knownTotal + extraTotal;
  const activeKinds = FALLBACK_KIND_ORDER.filter((kind) => (counts[kind] ?? 0) > 0);
  const quietKindCount = FALLBACK_KIND_ORDER.length - activeKinds.length;

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <AlertTriangle className="h-4 w-4 text-amber-300" />
              实时 fallback 明细
            </CardTitle>
            <CardDescription className="mt-1">
              按 kind 看当前进程内的兜底增量；重启清零，长期趋势看
              Prometheus。
            </CardDescription>
          </div>
          <Badge
            variant={grandTotal > 0 ? "warn" : "outline"}
            className="font-mono text-[10px]"
          >
            合计 {grandTotal}
          </Badge>
        </div>
      </CardHeader>
      <CardContent>
        {grandTotal === 0 ? (
          <div className="rounded-lg border border-dashed bg-muted/10 px-3 py-2">
            <p className="text-sm text-muted-foreground">当前进程暂无 fallback</p>
            <p className="mt-0.5 text-[11px] text-muted-foreground/70">
              有新增兜底事件时，这里会按 kind 展开明细。
            </p>
          </div>
        ) : (
          <div className="space-y-2">
            {activeKinds.map((kind) => {
              const count = counts[kind] ?? 0;
              const share = grandTotal > 0 ? count / grandTotal : 0;
              return (
                <FallbackKindRow
                  key={kind}
                  kind={kind}
                  count={count}
                  share={share}
                />
              );
            })}
            {quietKindCount > 0 && (
              <p className="text-[11px] text-muted-foreground">
                其余 {quietKindCount} 类 fallback 当前为 0。
              </p>
            )}
          </div>
        )}
        {extraEntries.length > 0 && (
          <div className="mt-3 rounded-lg border border-dashed border-amber-500/40 bg-amber-500/[0.04] p-3">
            <p className="mb-1.5 text-[11px] font-medium text-amber-300">
              发现未知 kind（疑似拼写漂移或新增类别，请确认）
            </p>
            <ul className="flex flex-wrap gap-1.5">
              {extraEntries.map(([kind, count]) => (
                <li key={kind}>
                  <Badge variant="outline" className="font-mono text-[10px]">
                    {kind} · {count}
                  </Badge>
                </li>
              ))}
            </ul>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function FallbackKindRow({
  kind,
  count,
  share,
}: {
  kind: FallbackKind;
  count: number;
  share: number;
}) {
  const sharePct = Math.round(share * 100);
  const tone = count > 0 ? FALLBACK_KIND_TONE[kind] : "";
  const textTone = count > 0 ? FALLBACK_KIND_TEXT[kind] : "text-foreground/70";
  return (
    <div
      className={cn(
        "rounded-lg border bg-card/50 p-3 transition-colors",
        tone,
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs font-medium">{FALLBACK_KIND_LABELS[kind]}</span>
            <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/60">
              {kind}
            </span>
          </div>
          <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
            {FALLBACK_KIND_DESCRIPTIONS[kind]}
          </p>
        </div>
        <div className="shrink-0 text-right">
          <div className={cn("font-mono text-xl font-semibold tabular-nums", textTone)}>
            {count}
          </div>
          <Badge variant="outline" className="font-mono text-[10px] tabular-nums">
            {sharePct}%
          </Badge>
        </div>
      </div>
      <div className="mt-2 h-1 w-full overflow-hidden rounded-full bg-muted/40">
        <div
          className={cn(
            "h-full rounded-full transition-all",
            count > 0 ? "bg-current opacity-70" : "bg-muted-foreground/30",
            textTone,
          )}
          style={{ width: `${Math.min(100, Math.max(count > 0 ? 6 : 0, sharePct))}%` }}
        />
      </div>
    </div>
  );
}

function EvidenceRollUp({ state }: { state: Loadable<EvidenceRollupResponse> }) {
  if (state.phase === "loading") {
    return <Skeleton className="h-24 w-full" />;
  }
  if (state.phase === "error") {
    return (
      <Card className="border-destructive/40 bg-destructive/5">
        <CardContent className="space-y-1 pt-6 text-sm">
          <p className="font-medium text-destructive">评分证据加载失败</p>
          <p className="text-xs text-muted-foreground">{state.message}</p>
        </CardContent>
      </Card>
    );
  }
  const data = state.data;
  const supportedEvidenceRate =
    data.yes_checks === 0 ? null : Math.max(0, 1 - data.unsupported_yes_rate);
  const evidenceBadgeLabel =
    data.total_evaluator_traces === 0
      ? "无 Trace"
      : supportedEvidenceRate === null
        ? "无通过项"
        : formatPercent(supportedEvidenceRate);
  const evidenceNeedsAttention =
    data.total_evaluator_traces > 0 &&
    (supportedEvidenceRate === null || supportedEvidenceRate < 0.8);
  return (
    <Card className={evidenceNeedsAttention ? "border-amber-500/40 bg-amber-500/[0.04]" : ""}>
      <CardHeader>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <CardTitle className="flex items-center gap-2 text-base">
              <ClipboardList className="h-4 w-4 text-blue-300" />
              评分证据质量（24 小时）
            </CardTitle>
            <CardDescription className="mt-1 max-w-3xl">
              聚合 evaluator / verification trace；主指标看“通过项是否有证据”，定位片段和引用数作为诊断线索。
            </CardDescription>
          </div>
          <Badge
            variant={evidenceNeedsAttention ? "warn" : "outline"}
            className="shrink-0 whitespace-nowrap font-mono"
          >
            {evidenceBadgeLabel}
          </Badge>
        </div>
      </CardHeader>
      <CardContent>
        {data.total_evaluator_traces === 0 ? (
          <p className="text-sm text-muted-foreground">
            过去 24 小时还没有 evaluator trace 可统计。
          </p>
        ) : (
          <div className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-3">
              <StatBox
                label="评分证据率"
                value={
                  supportedEvidenceRate === null
                    ? "无通过项"
                    : formatPercent(supportedEvidenceRate)
                }
              />
              <StatBox
                label="无证据通过"
                value={`${data.unsupported_yes_checks}/${data.yes_checks} (${formatPercent(data.unsupported_yes_rate)})`}
              />
              <StatBox
                label="复核改写率"
                value={formatPercent(data.verification_change_rate)}
              />
            </div>
            <div className="space-y-2 border-t border-border/50 pt-3">
              <p className="text-xs font-medium text-muted-foreground">
                评分证据诊断
              </p>
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                <StatBox
                  label="验收检查率"
                  value={formatPercent(data.acceptance_check_rate)}
                />
                <StatBox
                  label="证据定位率"
                  value={formatPercent(data.evidence_span_rate)}
                />
                <StatBox
                  label="证据引用数"
                  value={String(data.evidence_quote_total)}
                />
                <StatBox
                  label="平均引用"
                  value={data.avg_evidence_quotes_per_check.toFixed(2)}
                />
                <StatBox
                  label="验收检查数"
                  value={String(data.total_acceptance_checks)}
                />
                <StatBox label="通过项" value={String(data.yes_checks)} />
                <StatBox
                  label="无证据片段"
                  value={`${data.evidence_span_none_count}/${data.evidence_span_total} (${formatPercent(data.evidence_span_none_rate)})`}
                />
              </div>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function QuestionQualityRollUp({
  state,
}: {
  state: Loadable<QuestionQualityRollupResponse>;
}) {
  if (state.phase === "loading") {
    return <Skeleton className="h-24 w-full" />;
  }
  if (state.phase === "error") {
    return (
      <Card className="border-destructive/40 bg-destructive/5">
        <CardContent className="space-y-1 pt-6 text-sm">
          <p className="font-medium text-destructive">问题质量加载失败</p>
          <p className="text-xs text-muted-foreground">{state.message}</p>
        </CardContent>
      </Card>
    );
  }
  const data = state.data;
  return (
    <Card className={data.contract_rate < 0.8 ? "border-amber-500/40 bg-amber-500/[0.04]" : ""}>
      <CardHeader>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <CardTitle className="flex items-center gap-2 text-base">
              <BookMarked className="h-4 w-4 text-purple-300" />
              出题契约质量（24 小时）
            </CardTitle>
            <CardDescription className="mt-1 max-w-3xl">
              聚合 ask_question trace；主指标看题目是否带完整 contract，RAG 与技能聚焦作为出题支撑线索。
            </CardDescription>
          </div>
          <Badge
            variant={data.contract_rate < 0.8 ? "warn" : "outline"}
            className="shrink-0 whitespace-nowrap font-mono"
          >
            {formatPercent(data.contract_rate)}
          </Badge>
        </div>
      </CardHeader>
      <CardContent>
        {data.total_ask_question_traces === 0 ? (
          <p className="text-sm text-muted-foreground">
            过去 24 小时还没有 ask_question trace 可统计。
          </p>
        ) : (
          <div className="grid gap-3 md:grid-cols-3">
            <StatBox label="出题契约率" value={formatPercent(data.contract_rate)} />
            <StatBox
              label="检索支撑率"
              value={formatPercent(data.retrieval_grounding_rate)}
            />
            <StatBox
              label="平均检查数"
              value={data.avg_acceptance_checks.toFixed(1)}
            />
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// RecentTracesByNode: reverse-lookup card. Lets the operator pivot
// from "node X is misbehaving" to "show me the last N runs of node X
// and let me click into any one's Trace Explorer", instead of having
// to enumerate sessions first.
const RECENT_TRACE_NODES = [
  "evaluator",
  "director_sample",
  "verification",
  "reward_update",
  "route_decision",
  "final_report",
  "ask_question",
  "turn_finalize",
  "refine_followup",
  "training_plan",
  "experience_extractor",
  "resume_parse",
] as const;

const RECENT_TRACE_NODE_LABELS: Record<string, string> = {
  evaluator: "评分",
  director_sample: "策略采样",
  verification: "复核",
  reward_update: "奖励更新",
  route_decision: "路由决策",
  final_report: "最终报告",
  ask_question: "出题",
  turn_finalize: "轮次收尾",
  refine_followup: "追问优化",
  training_plan: "训练计划",
  experience_extractor: "经验提取",
  resume_parse: "简历解析",
};

function RecentTracesByNode({
  state,
  node,
  onNodeChange,
}: {
  state: Loadable<RecentTracesResponse>;
  node: string;
  onNodeChange: (next: string) => void;
}) {
  return (
    <Card>
      <CardHeader>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <Activity className="h-4 w-4 text-emerald-400" />
              最近 trace 抽样
            </CardTitle>
            <CardDescription className="mt-1">
              按节点抽 5 条最新记录，用来快速跳到 Trace Explorer。
            </CardDescription>
          </div>
          <label className="grid gap-1 text-[11px] text-muted-foreground">
            节点
            <select
              aria-label="选择 trace 节点"
              name="recentTraceNode"
              value={node}
              onChange={(event) => onNodeChange(event.target.value)}
              className="h-8 rounded-md border bg-background px-2 text-xs text-foreground"
            >
              {RECENT_TRACE_NODES.map((nodeId) => (
                <option key={nodeId} value={nodeId}>
                  {RECENT_TRACE_NODE_LABELS[nodeId] ?? nodeId}
                </option>
              ))}
            </select>
          </label>
        </div>
      </CardHeader>
      <CardContent>
        {state.phase === "loading" ? (
          <Skeleton className="h-24 w-full" />
        ) : state.phase === "error" ? (
          <p className="text-sm text-destructive">
            加载失败：{state.message}
          </p>
        ) : state.data.items.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            还没有 {RECENT_TRACE_NODE_LABELS[node] ?? node} 节点的 trace 记录。
          </p>
        ) : (
          <ul className="divide-y text-sm">
            {state.data.items.slice(0, 5).map((item) => (
              <li
                key={item.id}
                className="flex flex-wrap items-center justify-between gap-2 py-2"
              >
                <div className="min-w-0 space-y-0.5">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant="outline" className="font-mono text-[10px]">
                      {item.node}
                    </Badge>
                    {item.dimension && (
                      <span className="text-xs text-muted-foreground">
                        {item.dimension}
                      </span>
                    )}
                    {typeof item.score === "number" && (
                      <Badge variant={item.passed ? "success" : "warn"}>
                        {item.score.toFixed(1)}
                      </Badge>
                    )}
                  </div>
                  <p className="truncate font-mono text-[11px] text-muted-foreground">
                    {item.session_id}
                    {typeof item.turn_idx === "number" && ` · turn ${item.turn_idx}`}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-[11px] text-muted-foreground">
                    {item.created_at
                      ? new Date(item.created_at).toLocaleTimeString()
                      : "—"}
                  </span>
                  <Button asChild size="sm" variant="ghost" className="h-7 px-2 text-xs">
                    <PendingNavigationLink
                      href={`/admin/trace?sessionId=${encodeURIComponent(
                        item.session_id,
                      )}&node=${encodeURIComponent(item.node)}${
                        item.dimension
                          ? `&dimension=${encodeURIComponent(item.dimension)}`
                          : ""
                      }`}
                    >
                      Trace
                    </PendingNavigationLink>
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function isEnabledFlag(value?: string): boolean {
  return (value ?? "").toLowerCase() === "true";
}

function isStubMode(value?: string): boolean {
  return isEnabledFlag(value);
}

function formatCheckpointMode(backend?: string): string {
  if (backend === "postgres") return "持久化";
  if (backend === "memory") return "内存";
  return backend ? `检查点：${backend}` : "检查点未知";
}

function formatLlmProvider(provider?: string): string {
  const labels: Record<string, string> = {
    anthropic: "Anthropic",
    dashscope: "通义千问",
    deepseek: "DeepSeek",
    kimi: "Kimi",
    mistral: "Mistral",
    moonshot: "Moonshot",
    openai: "OpenAI",
    openai_compatible: "OpenAI 兼容",
    qwen: "通义千问",
    stub: "本地模拟",
    xiaomimimo: "Xiaomi MiMo",
    zhipu: "智谱",
  };
  return labels[provider ?? ""] ?? provider ?? "未知";
}

function formatBackendLlmStatus(provider?: string, stubMode?: string): string {
  if (provider === "stub") return "后端默认：本地模拟";
  const providerLabel = formatLlmProvider(provider);
  return isStubMode(stubMode)
    ? `后端默认：${providerLabel}（服务端 Key 未配置）`
    : `后端默认：${providerLabel}（服务端 Key 已配置）`;
}

function formatBrowserLlmKeyStatus(browserHasLlmKey: boolean): string {
  return browserHasLlmKey ? "浏览器 Key 已配置" : "浏览器未配置 Key";
}

function SystemOverview({
  health,
  bandit,
  drift,
  sessions,
  strategies,
  browserHasLlmKey,
}: {
  health: Loadable<BackendHealth>;
  bandit: Loadable<BanditSnapshot>;
  drift: Loadable<VerifierDriftSnapshot>;
  sessions: Loadable<AdminSessions>;
  strategies: Loadable<Strategies>;
  browserHasLlmKey: boolean;
}) {
  const runtimeModeLabel =
    health.phase === "ready"
      ? formatCheckpointMode(health.data.checkpoint_backend)
      : phaseLabel(health);
  const runtimeModeHint =
    health.phase === "ready"
      ? `${formatBackendLlmStatus(
          health.data.llm_provider,
          health.data.stub_mode,
        )}；${formatBrowserLlmKeyStatus(
          browserHasLlmKey,
        )}`
      : "等待健康检查";
  const traceLabel =
    health.phase === "ready"
      ? isEnabledFlag(health.data.langsmith_tracing)
        ? "开启"
        : "关闭"
      : phaseLabel(health);
  const memoryPriorCount =
    bandit.phase === "ready"
      ? (bandit.data.memory_prior_count ??
        Object.keys(bandit.data.priors || {}).length)
      : null;
  const persistedPriorCount =
    bandit.phase === "ready"
      ? (bandit.data.persisted_prior_count ?? memoryPriorCount)
      : null;
  const driftLabel =
    drift.phase === "ready"
      ? drift.data.enabled
        ? `${drift.data.samples ?? 0} 个样本`
        : "已关闭"
      : phaseLabel(drift);
  const sessionCount = sessions.phase === "ready" ? sessions.data.count : null;
  const strategyCount = strategies.phase === "ready" ? strategies.data.count : null;
  const runtimeModeTone =
    health.phase === "error"
      ? "error"
      : health.phase === "loading"
        ? "loading"
        : health.data.status !== "ok"
          ? "warn"
          : health.data.checkpoint_backend === "postgres" &&
              (!isStubMode(health.data.stub_mode) || browserHasLlmKey)
            ? "ok"
            : "warn";
  const traceTone =
    health.phase === "error"
      ? "error"
      : health.phase === "loading"
        ? "loading"
        : isEnabledFlag(health.data.langsmith_tracing)
          ? "ok"
          : "idle";
  const banditTone =
    bandit.phase === "error"
      ? "error"
      : bandit.phase === "loading"
        ? "loading"
        : persistedPriorCount && persistedPriorCount > 0
          ? "ok"
          : "idle";
  const driftTone =
    drift.phase === "error"
      ? "error"
      : drift.phase === "loading"
        ? "loading"
        : drift.data.enabled
          ? "ok"
          : "idle";
  const sessionsTone =
    sessions.phase === "error"
      ? "error"
      : sessions.phase === "loading"
        ? "loading"
        : sessionCount && sessionCount > 0
          ? "ok"
          : "idle";
  const strategiesTone =
    strategies.phase === "error"
      ? "error"
      : strategies.phase === "loading"
        ? "loading"
        : strategyCount && strategyCount > 0
          ? "ok"
          : "idle";

  return (
    <Card className="overflow-hidden">
      <CardContent className="space-y-3 p-4">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="min-w-0">
            <CardTitle className="flex items-center gap-2 text-base">
              <Activity className="h-4 w-4 text-emerald-400" />
              运行概览
            </CardTitle>
            <CardDescription className="mt-1 text-xs">
              关键后台状态灯，详细诊断在下方页签查看。
            </CardDescription>
          </div>
          <Button
            asChild
            variant="outline"
            size="sm"
            className="h-8 shrink-0 gap-1.5 text-xs active:scale-[0.98]"
          >
            <PendingNavigationLink href="/interview/history">
              面试质量入口
            </PendingNavigationLink>
          </Button>
        </div>
        <div className="grid gap-2 sm:grid-cols-2 md:grid-cols-3">
          <OverviewStatusLight
            label="运行模式"
            value={runtimeModeLabel}
            hint={runtimeModeHint}
            tone={runtimeModeTone}
          />
          <OverviewStatusLight
            label="Trace 采集"
            value={traceLabel}
            hint={`LangSmith：${traceLabel}`}
            tone={traceTone}
          />
          <OverviewStatusLight
            label="策略学习"
            value={
              persistedPriorCount === null
                ? phaseLabel(bandit)
                : `${persistedPriorCount} 个策略状态`
            }
            hint="来自 bandit_posteriors；Director 运行时仍读内存后验"
            tone={banditTone}
          />
          <OverviewStatusLight
            label="Verifier 监控"
            value={driftLabel}
            hint="drift 观测开关，不代表 Verifier 未运行"
            tone={driftTone}
          />
          <OverviewStatusLight
            label="内存会话"
            value={sessionCount === null ? phaseLabel(sessions) : `${sessionCount} 个`}
            hint="当前进程保留的会话句柄；超过 60 分钟无用户会话操作后清理，历史记录不受影响"
            tone={sessionsTone}
          />
          <OverviewStatusLight
            label="已入库策略"
            value={strategyCount === null ? phaseLabel(strategies) : `${strategyCount} 条`}
            hint="Generator 可复用经验"
            tone={strategiesTone}
          />
        </div>
      </CardContent>
    </Card>
  );
}

type OverviewTone = "ok" | "idle" | "warn" | "error" | "loading";

function OverviewStatusLight({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: string;
  hint: string;
  tone: OverviewTone;
}) {
  const toneClass = {
    ok: "bg-emerald-400 shadow-[0_0_0_3px_rgba(52,211,153,0.16)]",
    idle: "bg-muted-foreground/40",
    warn: "bg-amber-400 shadow-[0_0_0_3px_rgba(251,191,36,0.16)]",
    error: "bg-destructive shadow-[0_0_0_3px_hsl(var(--destructive)/0.16)]",
    loading: "animate-pulse bg-sky-400 shadow-[0_0_0_3px_rgba(56,189,248,0.16)]",
  }[tone];

  return (
    <div className="flex min-w-0 w-full items-start gap-3 rounded-lg border bg-muted/20 px-3 py-2 text-left">
      <span
        className={cn("mt-1.5 h-2 w-2 shrink-0 rounded-full", toneClass)}
        aria-hidden="true"
      />
      <span className="grid min-w-0 gap-0.5">
        <span className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-0.5">
          <span className="shrink-0 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
            {label}
          </span>
          <span className="min-w-0 break-words font-mono text-sm font-semibold leading-5 text-foreground">
            {value}
          </span>
        </span>
        <span className="block break-words text-[11px] leading-4 text-muted-foreground">
          {hint}
        </span>
      </span>
    </div>
  );
}

function phaseLabel(state: Loadable<unknown>): string {
  if (state.phase === "loading") return "加载中";
  if (state.phase === "error") return "连接异常";
  return "已连接";
}

// ---------------------------------------------------------------------------
// Token bar — the page-level gate keeps casual users out of the panel.
// This in-panel control lets operators update the bearer token used by
// protected admin API requests after the panel is unlocked.
// ---------------------------------------------------------------------------

function TokenBar({
  tokenInput,
  setTokenInput,
  onSave,
  tokenSaved,
  onRefresh,
}: {
  tokenInput: string;
  setTokenInput: (v: string) => void;
  onSave: () => void;
  tokenSaved: string;
  onRefresh: () => void;
}) {
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const refreshTimerRef = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (refreshTimerRef.current !== null) {
        window.clearTimeout(refreshTimerRef.current);
      }
    };
  }, []);

  function handleRefreshClick() {
    setRefreshing(true);
    onRefresh();

    if (refreshTimerRef.current !== null) {
      window.clearTimeout(refreshTimerRef.current);
    }
    refreshTimerRef.current = window.setTimeout(() => {
      setRefreshing(false);
      refreshTimerRef.current = null;
    }, 900);
  }

  return (
    <Card className="overflow-hidden">
      <CardContent className="space-y-4 pt-5">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-start gap-3">
            <div className="mt-0.5 rounded-md border bg-muted/50 p-2 text-muted-foreground">
              <Key className="h-4 w-4" />
            </div>
            <div className="space-y-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-medium">后台设置 / 权限</span>
                <Badge variant="outline" className="text-[10px]">
                  {tokenSaved ? "令牌已保存" : "等待令牌"}
                </Badge>
              </div>
              <p className="text-xs leading-5 text-muted-foreground">
                用于访问受保护的后台观测接口，本地开发可使用 dev 标记。
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2 sm:justify-end">
            <Button
              size="sm"
              variant="outline"
              onClick={() => setSettingsOpen((open) => !open)}
            >
              {settingsOpen ? "收起" : "设置"}
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={handleRefreshClick}
              className={cn(
                "min-w-[5.75rem] justify-center gap-1.5 transition-colors active:scale-[0.98]",
                refreshing &&
                  "border border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-200",
              )}
              aria-busy={refreshing}
              aria-label={`每 ${REFRESH_INTERVAL_MS / 1000} 秒自动刷新`}
            >
              <RefreshCw
                className={cn("h-3.5 w-3.5", refreshing && "animate-spin")}
              />
              {refreshing ? "刷新中" : "刷新"}
            </Button>
          </div>
        </div>
        {settingsOpen && (
          <div className="grid gap-3 border-t pt-4 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
            <label className="grid gap-2">
              <span className="text-xs font-medium text-muted-foreground">
                管理员认证令牌
              </span>
              <Input
                type="password"
                placeholder="API_TOKEN 或本地 dev 标记"
                value={tokenInput}
                onChange={(e) => setTokenInput(e.target.value)}
                className="sm:max-w-md"
              />
            </label>
            <Button
              size="sm"
              variant={tokenInput !== tokenSaved ? "default" : "outline"}
              onClick={onSave}
              className={
                tokenInput !== tokenSaved
                  ? "bg-emerald-600 hover:bg-emerald-500 text-white"
                  : ""
              }
            >
              保存
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Bandit posteriors
// ---------------------------------------------------------------------------

function StrategyLearningOverview({
  bandit,
  questionSeeds,
  questionUsages,
  skillPlaybooks,
  strategies,
  strategyUsages,
}: {
  bandit: Loadable<BanditSnapshot>;
  questionSeeds: Loadable<QuestionSeeds>;
  questionUsages: Loadable<QuestionUsages>;
  skillPlaybooks: Loadable<SkillPlaybooks>;
  strategies: Loadable<Strategies>;
  strategyUsages: Loadable<StrategyUsages>;
}) {
  const banditCount =
    bandit.phase === "ready"
      ? String(
          bandit.data.persisted_prior_count ??
            Object.keys(bandit.data.priors || {}).length,
        )
      : phaseLabel(bandit);
  const questionVariantCount =
    questionSeeds.phase === "ready"
      ? questionSeeds.data.question_seeds.reduce(
          (sum, seed) => sum + Number(seed.variant_count ?? 0),
          0,
        )
      : null;
  const questionCount =
    questionSeeds.phase === "ready"
      ? `${questionSeeds.data.count} / ${questionVariantCount ?? 0}`
      : phaseLabel(questionSeeds);
  const questionDetail =
    questionUsages.phase === "ready"
      ? `${questionUsages.data.count} 次题目调用`
      : "题目 / 变体";
  const playbookCount =
    skillPlaybooks.phase === "ready"
      ? `${skillPlaybooks.data.active_count}/${skillPlaybooks.data.count}`
      : phaseLabel(skillPlaybooks);
  const strategyCount =
    strategies.phase === "ready" ? String(strategies.data.count) : phaseLabel(strategies);
  const strategyDetail =
    strategyUsages.phase === "ready"
      ? `${strategyUsages.data.count} 次归因`
      : "策略记忆 / 归因";

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Waypoints className="h-4 w-4 text-amber-400" />
          策略学习总览
        </CardTitle>
        <CardDescription className="mt-1">
          汇总当前进程和数据库里的策略学习资产，先看全局状态，再进入下面的治理模块。
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <StrategyOverviewTile
            label="Bandit 后验"
            value={banditCount}
            detail="Thompson 策略状态"
          />
          <StrategyOverviewTile
            label="题库资产"
            value={questionCount}
            detail={questionDetail}
          />
          <StrategyOverviewTile
            label="技能打法"
            value={playbookCount}
            detail="启用 / 总数"
          />
          <StrategyOverviewTile
            label="策略记忆"
            value={strategyCount}
            detail={strategyDetail}
          />
        </div>
      </CardContent>
    </Card>
  );
}

function StrategyOverviewTile({
  label,
  value,
  detail,
}: {
  label: string;
  value: string;
  detail: string;
}) {
  return (
    <div className="rounded-md border bg-card/50 p-3">
      <p className="text-[10px] font-medium text-muted-foreground">{label}</p>
      <p className="mt-1 break-words font-mono text-lg font-bold text-foreground">
        {value}
      </p>
      <p className="mt-1 text-[11px] text-muted-foreground">{detail}</p>
    </div>
  );
}

function BanditCard({ state }: { state: Loadable<BanditSnapshot> }) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <Cpu className="h-4 w-4 text-emerald-400" />
              策略学习（Thompson）
            </CardTitle>
            <CardDescription className="mt-1">
              默认展示后验均值最高的策略状态；原始参数保留在开发详情里。
            </CardDescription>
          </div>
          {state.phase === "ready" && (
            <Badge variant="outline" className="font-mono text-[10px]">
              {state.data.persisted_prior_count ??
                Object.keys(state.data.priors || {}).length} 个策略状态
            </Badge>
          )}
        </div>
      </CardHeader>
      <CardContent>
        {state.phase === "loading" && <LoadingList rows={4} />}
        {state.phase === "error" && <ErrorBox message={state.message} />}
        {state.phase === "ready" && (
          <div className="space-y-3">
            <PolicyMeta snapshot={state.data} />
            <Separator />
            <BanditTable priors={state.data.priors || {}} />
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function PolicyMeta({ snapshot }: { snapshot: BanditSnapshot }) {
  return (
    <div className="flex flex-wrap gap-2 text-xs">
      <MetaPill label="模式" value={snapshot.policy_mode ?? "—"} />
      <MetaPill
        label="探索率"
        value={
          typeof snapshot.exploration_rate === "number"
            ? snapshot.exploration_rate.toFixed(3)
            : "—"
        }
      />
      <MetaPill
        label="衰减"
        value={
          snapshot.decay?.enabled
            ? `factor=${snapshot.decay?.factor ?? "-"} · floor=${
                snapshot.decay?.floor ?? "-"
              } · every ${snapshot.decay?.interval_days ?? "-"}d`
            : "关闭"
        }
      />
    </div>
  );
}

function BanditTable({
  priors,
}: {
  priors: Record<string, { alpha: number; beta: number }>;
}) {
  const rows = Object.entries(priors)
    .map(([key, { alpha, beta }]) => {
      const { contextKey, actionId } = splitBanditStrategyKey(key);
      const canonicalActionId = canonicalBanditActionId(actionId || key);
      const mean = alpha / (alpha + beta || 1);
      return {
        key,
        contextKey,
        actionId,
        canonicalActionId,
        canonicalKey: `${contextKey}::${canonicalActionId}`,
        alpha,
        beta,
        mean,
        display: parseBanditStrategyKey(key),
        rawCount: 1,
        rawActionIds: [actionId || key],
      };
    })
    .sort((a, b) => b.mean - a.mean);
  const [rawDetailsQuery, setRawDetailsQuery] = useState("");
  const [rawDetailsFilterField, setRawDetailsFilterField] =
    useState<BanditRawDetailsFilterField>("all");
  const [rawDetailsLimit, setRawDetailsLimit] = useState(
    BANDIT_RAW_DETAILS_PAGE_SIZE,
  );
  const normalizedRawDetailsQuery = rawDetailsQuery.trim().toLowerCase();
  const filteredRawRows = rows.filter((r) => {
    if (!normalizedRawDetailsQuery) return true;
    return banditRawDetailsSearchValues(r, rawDetailsFilterField).some(
      (value) => value.toLowerCase().includes(normalizedRawDetailsQuery),
    );
  });
  const visibleRawRows = filteredRawRows.slice(0, rawDetailsLimit);
  const handleRawDetailsQueryChange = (nextQuery: string) => {
    setRawDetailsQuery(nextQuery);
    setRawDetailsLimit(BANDIT_RAW_DETAILS_PAGE_SIZE);
  };
  const handleRawDetailsFilterFieldChange = (
    nextField: BanditRawDetailsFilterField,
  ) => {
    setRawDetailsFilterField(nextField);
    setRawDetailsLimit(BANDIT_RAW_DETAILS_PAGE_SIZE);
  };

  if (rows.length === 0) {
    return (
      <p className="text-xs text-muted-foreground">
        暂无后验数据，这不是错误。跑完一场面试后会出现策略状态。
      </p>
    );
  }

  const canonicalRows = buildCanonicalBanditRows(rows);
  const topRows = canonicalRows.slice(0, 5);
  return (
    <div className="space-y-3">
      <div>
        <p className="text-xs font-medium text-muted-foreground">Top 后验策略</p>
        <p className="mt-1 text-[11px] text-muted-foreground">
          按 canonical plan_* 动作归并；同组存在新旧 action
          时优先展示 plan_* 后验，原始 rows 留在开发详情。
          key = context_key::action_id，context_key 由方向、级别、维度组成。
        </p>
        <div className="mt-2 overflow-x-auto rounded-md border">
          <table className="w-full min-w-[820px] text-xs">
            <thead className="bg-secondary/50 text-[10px] text-muted-foreground">
              <tr>
                <th className="px-3 py-2 text-left font-medium">上下文 key</th>
                <th className="px-3 py-2 text-left font-medium">策略动作</th>
                <th className="px-3 py-2 text-left font-medium">粒度</th>
                <th className="px-3 py-2 text-right font-medium">后验权重</th>
                <th className="px-3 py-2 text-right font-medium">成功倾向</th>
                <th className="px-3 py-2 font-medium">后验</th>
              </tr>
            </thead>
            <tbody>
              {topRows.map((r) => (
                <tr
                  key={r.canonicalKey}
                  aria-label={formatBanditStrategyLabel(r.canonicalKey)}
                  className="border-t"
                >
                  <td className="max-w-[320px] px-3 py-2">
                    <div className="min-w-0 truncate font-mono font-medium text-foreground">
                      {r.contextKey}
                    </div>
                    <div className="mt-0.5 min-w-0 truncate text-[11px] text-muted-foreground">
                      {r.display.context}
                    </div>
                  </td>
                  <td className="px-3 py-2">
                    <div className="font-mono font-medium text-foreground">
                      {r.canonicalActionId}
                    </div>
                    <div className="mt-0.5 text-[11px] text-muted-foreground">
                      {r.display.action}
                    </div>
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex flex-wrap gap-1">
                      <Badge variant="outline" className="text-[10px]">
                        {r.display.granularity}
                      </Badge>
                      {r.rawCount > 1 && (
                        <Badge variant="secondary" className="text-[10px]">
                          原始 {r.rawCount} 条
                        </Badge>
                      )}
                    </div>
                  </td>
                  <td className="px-3 py-2 text-right font-mono tabular-nums">
                    {(r.alpha + r.beta).toFixed(0)}
                  </td>
                  <td className="px-3 py-2 text-right font-mono tabular-nums">
                    {r.mean.toFixed(3)}
                  </td>
                  <td className="px-3 py-2">
                    <div className="h-1.5 w-full overflow-hidden rounded-full bg-secondary">
                      <div
                        className="h-full bg-emerald-400/70"
                        style={{
                          width: `${Math.max(0, Math.min(100, r.mean * 100))}%`,
                        }}
                      />
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      <details className="rounded-md border bg-muted/10 p-3 text-xs">
        <summary className="cursor-pointer font-medium text-muted-foreground">
          开发详情：原始后验参数
        </summary>
        <div className="mt-3 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
            <select
              aria-label="选择原始后验筛选字段"
              className="h-8 rounded-md border border-input bg-background px-2 text-xs text-foreground"
              value={rawDetailsFilterField}
              onChange={(event) =>
                handleRawDetailsFilterFieldChange(
                  event.currentTarget.value as BanditRawDetailsFilterField,
                )
              }
            >
              {BANDIT_RAW_DETAILS_FILTER_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
            <Input
              aria-label="筛选原始后验参数"
              className="h-8 text-xs sm:w-72"
              placeholder="输入关键词"
              value={rawDetailsQuery}
              onChange={(event) =>
                handleRawDetailsQueryChange(event.currentTarget.value)
              }
            />
          </div>
          <p className="text-[11px] text-muted-foreground">
            显示 {visibleRawRows.length} / 共 {filteredRawRows.length} 条
            {filteredRawRows.length !== rows.length ? `，原始 ${rows.length} 条` : ""}
          </p>
        </div>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[820px] text-xs">
            <thead className="text-[10px] text-muted-foreground">
              <tr>
                <th className="px-2 py-1 text-left font-medium">
                  原始键（context_key::action_id）
                </th>
                <th className="px-2 py-1 text-left font-medium">canonical 动作</th>
                <th className="px-2 py-1 text-right font-medium">alpha</th>
                <th className="px-2 py-1 text-right font-medium">beta</th>
                <th className="px-2 py-1 text-right font-medium">均值</th>
              </tr>
            </thead>
            <tbody>
              {visibleRawRows.map((r) => (
                <tr key={r.key} className="border-t border-border/50">
                  <td className="max-w-[420px] truncate px-2 py-1 font-mono">
                    {r.key}
                  </td>
                  <td className="px-2 py-1 text-left font-mono">
                    {r.canonicalActionId}
                  </td>
                  <td className="px-2 py-1 text-right font-mono tabular-nums">
                    {r.alpha.toFixed(2)}
                  </td>
                  <td className="px-2 py-1 text-right font-mono tabular-nums">
                    {r.beta.toFixed(2)}
                  </td>
                  <td className="px-2 py-1 text-right font-mono tabular-nums">
                    {r.mean.toFixed(3)}
                  </td>
                </tr>
              ))}
              {visibleRawRows.length === 0 && (
                <tr className="border-t border-border/50">
                  <td
                    colSpan={5}
                    className="px-2 py-6 text-center text-muted-foreground"
                  >
                    没有匹配的原始后验参数
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        {visibleRawRows.length < filteredRawRows.length && (
          <div className="mt-3 flex justify-end">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() =>
                setRawDetailsLimit(
                  (current) => current + BANDIT_RAW_DETAILS_PAGE_SIZE,
                )
              }
            >
              显示更多
            </Button>
          </div>
        )}
      </details>
    </div>
  );
}

type BanditPriorRow = {
  key: string;
  contextKey: string;
  actionId: string;
  canonicalActionId: string;
  canonicalKey: string;
  alpha: number;
  beta: number;
  mean: number;
  display: ReturnType<typeof parseBanditStrategyKey>;
  rawCount: number;
  rawActionIds: string[];
};

function banditRawDetailsSearchValues(
  row: BanditPriorRow,
  field: BanditRawDetailsFilterField,
): string[] {
  if (field === "context_key") return [row.contextKey];
  if (field === "action_id") return [row.actionId || row.key];
  if (field === "canonical_action") return [row.canonicalActionId];
  return [row.key, row.contextKey, row.actionId, row.canonicalActionId];
}

function buildCanonicalBanditRows(rows: BanditPriorRow[]): BanditPriorRow[] {
  const groups = new Map<string, BanditPriorRow[]>();
  for (const row of rows) {
    const bucket = groups.get(row.canonicalKey) ?? [];
    bucket.push(row);
    groups.set(row.canonicalKey, bucket);
  }

  return Array.from(groups.values())
    .map((group) => {
      const representative =
        group.find((row) => row.actionId === row.canonicalActionId) ??
        [...group].sort((a, b) => b.alpha + b.beta - (a.alpha + a.beta))[0];
      const canonicalKey = representative.canonicalKey;
      const rawActionIds = Array.from(
        new Set(group.map((row) => row.actionId || row.key)),
      );
      // Do not sum alpha/beta here: reward_update may mirror-write legacy
      // and canonical arms for one event, so summing can double count evidence.
      return {
        ...representative,
        key: canonicalKey,
        actionId: representative.canonicalActionId,
        display: parseBanditStrategyKey(canonicalKey),
        rawCount: group.length,
        rawActionIds,
      };
    })
    .sort((a, b) => b.mean - a.mean);
}

function splitBanditStrategyKey(key: string): {
  contextKey: string;
  actionId: string;
} {
  const [contextKey, ...actionParts] = key.split("::");
  return {
    contextKey,
    actionId: actionParts.join("::"),
  };
}

function parseBanditStrategyKey(key: string): {
  context: string;
  action: string;
  granularity: string;
} {
  const { contextKey, actionId } = splitBanditStrategyKey(key);
  return {
    context: formatBanditContextLabel(contextKey),
    action: formatBanditActionLabel(canonicalBanditActionId(actionId || key)),
    granularity: getBanditContextGranularity(contextKey),
  };
}

function formatBanditStrategyLabel(key: string): string {
  const parsed = parseBanditStrategyKey(key);
  return `${parsed.context} / ${parsed.action} / ${parsed.granularity}`;
}

function formatBanditContextLabel(contextKey: string): string {
  const parts = contextKey.split(":").filter(Boolean);
  if (parts.length >= 3) {
    const [direction, level, ...dimensionParts] = parts;
    return [
      formatDirectionLabel(direction),
      formatLevelLabel(level),
      formatDimensionLabel(dimensionParts.join(":")),
    ].join(" · ");
  }
  if (parts.length === 2) {
    const [level, dimension] = parts;
    return [formatLevelLabel(level), formatDimensionLabel(dimension)].join(" · ");
  }
  return formatTokenLabel(contextKey || "未命名上下文");
}

function canonicalBanditActionId(actionId: string): string {
  const aliases: Record<string, string> = {
    deepen_technical: "plan_adaptive",
    switch_dimension: "plan_switch",
    give_hint: "plan_hint",
    skip_to_next: "plan_simple",
  };
  return aliases[actionId] ?? actionId;
}

function formatBanditActionLabel(actionId: string): string {
  const labels: Record<string, string> = {
    plan_simple: "轻量探问",
    plan_quick_review: "快速复核",
    plan_adaptive: "自适应追问",
    plan_deep_probe: "深挖追问",
    plan_hint: "提示引导",
    plan_switch: "切换维度",
    deepen_technical: "技术深挖",
    switch_dimension: "切换维度",
    give_hint: "提示引导",
    skip_to_next: "跳到下一题",
  };
  return labels[actionId] ?? formatTokenLabel(actionId || "未知动作");
}

function getBanditContextGranularity(contextKey: string): string {
  const parts = contextKey.split(":").filter(Boolean);
  if (parts.length >= 3) return "方向级";
  if (parts.length === 2) return "全局级";
  return "未知粒度";
}

function formatDirectionLabel(direction: string): string {
  const labels: Record<string, string> = {
    java_backend: "Java 后端",
    backend: "后端",
    frontend: "前端",
    fullstack: "全栈",
    product: "产品",
    data: "数据",
  };
  return labels[direction] ?? formatTokenLabel(direction);
}

function formatLevelLabel(level: string): string {
  const labels: Record<string, string> = {
    intern: "实习",
    junior: "初级",
    mid: "中级",
    senior: "高级",
    staff: "资深",
    principal: "专家",
  };
  return labels[level] ?? formatTokenLabel(level);
}

function formatDimensionLabel(dimension: string): string {
  const labels: Record<string, string> = {
    communication: "沟通表达",
    technical_depth: "技术深度",
    system_design: "系统设计",
    problem_solving: "问题解决",
    coding: "编码能力",
    collaboration: "协作",
  };
  return labels[dimension] ?? formatTokenLabel(dimension);
}

function formatTokenLabel(value: string): string {
  return value
    .split(/[_:\s-]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

// ---------------------------------------------------------------------------
// Verifier drift
// ---------------------------------------------------------------------------

function DriftCard({ state }: { state: Loadable<VerifierDriftSnapshot> }) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <AlertTriangle className="h-4 w-4 text-amber-400" />
              复核分歧观测
            </CardTitle>
            <CardDescription className="mt-1">
              评估器和复核器的分歧窗口；观测开关只代表 drift 统计是否开启，不代表 Verifier 未运行。
            </CardDescription>
          </div>
          {state.phase === "ready" && (
            <Badge
              variant={state.data.enabled ? "success" : "outline"}
              className="font-mono text-[10px]"
            >
              {state.data.enabled ? "观测开启" : "观测关闭"}
            </Badge>
          )}
        </div>
      </CardHeader>
      <CardContent>
        {state.phase === "loading" && <LoadingList rows={4} />}
        {state.phase === "error" && <ErrorBox message={state.message} />}
        {state.phase === "ready" && <DriftBody snapshot={state.data} />}
      </CardContent>
    </Card>
  );
}

function DriftBody({ snapshot }: { snapshot: VerifierDriftSnapshot }) {
  const rate = (n?: number) =>
    typeof n === "number" ? `${(n * 100).toFixed(1)}%` : "—";

  if (!snapshot.samples) {
    return (
      <p className="text-xs text-muted-foreground">
        暂无复核样本，这不是错误。跑完一场面试后会出现评分复核窗口数据。
      </p>
    );
  }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-2 text-xs">
        <StatBox label="样本数" value={String(snapshot.samples ?? 0)} />
        <StatBox label="推翻率" value={rate(snapshot.override_rate)} />
        <StatBox label="弃权率" value={rate(snapshot.abstain_rate)} />
      </div>
      <div className="flex flex-wrap gap-2 text-xs">
        <MetaPill
          label="窗口"
          value={String(snapshot.window_size ?? "—")}
        />
        <MetaPill
          label="跨度缺失"
          value={rate(snapshot.span_miss_rate)}
        />
      </div>

      {snapshot.per_verdict && Object.keys(snapshot.per_verdict).length > 0 && (
        <div>
          <div className="mb-1.5 text-[10px] font-mono uppercase tracking-wider text-muted-foreground">
            按裁定
          </div>
          <div className="flex gap-2 text-xs">
            {Object.entries(snapshot.per_verdict).map(([v, n]) => (
              <MetaPill key={v} label={v} value={String(n)} />
            ))}
          </div>
        </div>
      )}

      {snapshot.per_dimension && Object.keys(snapshot.per_dimension).length > 0 && (
        <div>
          <div className="mb-1.5 text-[10px] font-mono uppercase tracking-wider text-muted-foreground">
            按维度
          </div>
          <div className="overflow-x-auto rounded-lg border border-border/60">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border/40 bg-muted/30">
                  <th className="px-2 py-1.5 text-left text-[10px] font-medium text-muted-foreground">维度</th>
                  <th className="px-2 py-1.5 text-right text-[10px] font-medium text-muted-foreground">样本</th>
                  <th className="px-2 py-1.5 text-right text-[10px] font-medium text-muted-foreground">推翻率</th>
                  <th className="px-2 py-1.5 text-right text-[10px] font-medium text-muted-foreground">弃权率</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/30">
                {Object.entries(snapshot.per_dimension)
                  .sort(([, a], [, b]) => (b.override_rate ?? 0) - (a.override_rate ?? 0))
                  .map(([dim, d]) => (
                    <tr key={dim} className="hover:bg-muted/20">
                      <td className="px-2 py-1.5 font-mono text-emerald-400/80">{dim.replaceAll("_", " ")}</td>
                      <td className="px-2 py-1.5 text-right tabular-nums">{d.calls ?? 0}</td>
                      <td className={cn(
                        "px-2 py-1.5 text-right font-mono tabular-nums",
                        (d.override_rate ?? 0) >= 0.25 ? "text-red-400" : (d.override_rate ?? 0) >= 0.1 ? "text-amber-400" : "text-foreground/70",
                      )}>
                        {rate(d.override_rate)}
                      </td>
                      <td className="px-2 py-1.5 text-right font-mono tabular-nums text-foreground/70">{rate(d.abstain_rate)}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {snapshot.overruled_patterns && snapshot.overruled_patterns.length > 0 && (
        <div>
          <div className="mb-1.5 text-[10px] font-mono uppercase tracking-wider text-muted-foreground">
            主要推翻模式
          </div>
          <ul className="space-y-1.5 text-xs">
            {snapshot.overruled_patterns.slice(0, 5).map((p, i) => (
              <li
                key={i}
                className="rounded border bg-card/50 px-3 py-2"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-emerald-400/80">
                    {p.dimension ?? "—"}
                  </span>
                  <span className="font-mono tabular-nums">×{p.count ?? 0}</span>
                </div>
                <div className="mt-0.5 text-muted-foreground">{p.check}</div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Active sessions
// ---------------------------------------------------------------------------

const SessionsCard = React.memo(function SessionsCard({ state }: { state: Loadable<AdminSessions> }) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <Clock className="h-4 w-4 text-emerald-400" />
              内存会话
            </CardTitle>
            <CardDescription className="mt-1">
              当前后端进程保留的会话句柄；超过 60 分钟无用户会话操作后清理，历史记录不受影响。
            </CardDescription>
          </div>
          {state.phase === "ready" && (
            <Badge variant="outline" className="font-mono text-[10px]">
              {state.data.count} 个会话
            </Badge>
          )}
        </div>
      </CardHeader>
      <CardContent>
        {state.phase === "loading" && <LoadingList rows={3} />}
        {state.phase === "error" && <ErrorBox message={state.message} />}
        {state.phase === "ready" && state.data.sessions.length === 0 && (
          <p className="text-xs text-muted-foreground">
            当前进程暂无会话句柄，这不是错误。开始一场面试后会出现可追踪会话。
          </p>
        )}
        {state.phase === "ready" && state.data.sessions.length > 0 && (
          <>
            {/* Desktop Table View */}
            <div className="hidden md:block overflow-x-auto rounded-lg border">
              <table className="min-w-[760px] w-full text-xs">
                <thead className="bg-secondary/50 text-[10px] uppercase tracking-wider text-muted-foreground">
                  <tr>
                    <th className="px-3 py-2 text-left">会话</th>
                    <th className="px-3 py-2 text-left">追踪</th>
                    <th className="px-3 py-2 text-left">LangSmith</th>
                    <th className="px-3 py-2 text-right">轮次</th>
                    <th className="px-3 py-2">状态</th>
                    <th className="px-3 py-2 text-left">创建时间</th>
                    <th className="px-3 py-2 text-left">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {state.data.sessions.map((session) => (
                    <tr key={session.session_id} className="border-t">
                      <td className="px-3 py-2 font-mono">
                        {truncate(session.session_id)}
                      </td>
                      <td className="px-3 py-2 font-mono text-muted-foreground">
                        {truncate(session.trace_id)}
                      </td>
                      <td className="px-3 py-2">
                        <LangSmithCell
                          session={session}
                          langsmith={state.data.langsmith}
                        />
                      </td>
                      <td className="px-3 py-2 text-right font-mono tabular-nums">
                        {session.turn_idx}
                      </td>
                      <td className="px-3 py-2">
                        <SessionStatusBadge session={session} />
                      </td>
                      <td className="px-3 py-2 font-mono text-muted-foreground">
                        <TimeCell iso={session.created_at} />
                      </td>
                      <td className="px-3 py-2">
                        <SessionLinks session={session} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Mobile Card Stack View */}
            <div className="grid gap-3 md:hidden">
              {state.data.sessions.map((session) => (
                <div key={session.session_id} className="flex flex-col gap-2 rounded-lg border bg-card/50 p-3 text-xs">
                  <div className="flex items-center justify-between">
                    <span className="font-mono text-foreground font-medium">{truncate(session.session_id)}</span>
                    <SessionStatusBadge session={session} />
                  </div>
                  <div className="flex items-center justify-between text-muted-foreground">
                    <span>轮次: <span className="font-mono text-foreground">{session.turn_idx}</span></span>
                    <span className="font-mono">{formatDateTime(session.created_at)}</span>
                  </div>
                  <div className="pt-2 border-t mt-1 flex items-center justify-between">
                    <span className="text-[10px] text-muted-foreground">Trace: {truncate(session.trace_id)}</span>
                    <LangSmithCell session={session} langsmith={state.data.langsmith} />
                  </div>
                  <SessionLinks session={session} />
                </div>
              ))}
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
});

function SessionLinks({ session }: { session: { session_id: string } }) {
  return (
    <div className="flex items-center justify-end gap-1.5">
      <Button asChild size="sm" variant="outline" className="h-7 gap-1.5 px-3 text-[11px]">
        <PendingNavigationLink href={`/interview/${session.session_id}/report`}>
          <ClipboardList className="h-3 w-3" />
          报告
        </PendingNavigationLink>
      </Button>
      <Button asChild size="sm" variant="ghost" className="h-7 gap-1 px-2.5 text-[11px] text-muted-foreground hover:text-foreground">
        <PendingNavigationLink href={`/interview/${session.session_id}/replay`}>
          <Play className="h-3 w-3" />
          Replay
        </PendingNavigationLink>
      </Button>
      <Button asChild size="sm" variant="ghost" className="h-7 gap-1 px-2.5 text-[11px] text-muted-foreground hover:text-foreground">
        <PendingNavigationLink href={`/admin/trace?sessionId=${session.session_id}`}>
          <Waypoints className="h-3 w-3" />
          Trace
        </PendingNavigationLink>
      </Button>
    </div>
  );
}

const HistoricalSessionsCard = React.memo(function HistoricalSessionsCard({
  state,
  historyPage,
  pageSize,
  filters,
  searchText,
  onHistoryPageChange,
  onHistoryFiltersChange,
  onHistorySearchTextChange,
  onRefresh,
}: {
  state: Loadable<InterviewSessionHistory>;
  historyPage: number;
  pageSize: number;
  filters: InterviewSessionHistoryFilters;
  searchText: string;
  onHistoryPageChange: (page: number) => void;
  onHistoryFiltersChange: (filters: InterviewSessionHistoryFilters) => void;
  onHistorySearchTextChange: (text: string) => void;
  onRefresh: () => void;
}) {
  const [deletedSessionIds, setDeletedSessionIds] = useState<Set<string>>(
    () => new Set(),
  );
  const markSessionDeleted = useCallback((sessionId: string) => {
    setDeletedSessionIds((prev) => {
      const next = new Set(prev);
      next.add(sessionId);
      return next;
    });
  }, []);

  useEffect(() => {
    if (state.phase !== "ready") return;
    const total = Math.max(state.data.total_count ?? state.data.count, 0);
    if (total === 0 || historyPage * pageSize < total) return;
    onHistoryPageChange(Math.max(0, Math.ceil(total / pageSize) - 1));
  }, [state, historyPage, pageSize, onHistoryPageChange]);

  const { filteredSessions, totalCount } = React.useMemo(() => {
    if (state.phase !== "ready")
      return {
        filteredSessions: [] as InterviewSessionHistory["sessions"],
        totalCount: 0,
      };
    const visibleSessions = state.data.sessions.filter(
      (s) => !deletedSessionIds.has(s.session_id),
    );
    return {
      filteredSessions: visibleSessions,
      totalCount: visibleSessions.length,
    };
  }, [state, deletedSessionIds]);

  const hasHistoryFilters = Boolean(
    filters.status ||
      filters.traceHealth ||
      typeof filters.hasReport === "boolean" ||
      filters.since ||
      searchText.trim(),
  );
  const setHistoryFilter = useCallback(
    <K extends keyof InterviewSessionHistoryFilters>(
      key: K,
      value: InterviewSessionHistoryFilters[K] | undefined,
    ) => {
      const next: InterviewSessionHistoryFilters = { ...filters };
      if (value === undefined || value === "") {
        delete next[key];
      } else {
        next[key] = value;
      }
      onHistoryFiltersChange(next);
    },
    [filters, onHistoryFiltersChange],
  );
  const clearHistoryFilters = useCallback(() => {
    onHistoryFiltersChange({});
    onHistorySearchTextChange("");
  }, [onHistoryFiltersChange, onHistorySearchTextChange]);
  const historyReturnedCount = totalCount;
  const historyOffset =
    state.phase === "ready"
      ? (state.data.offset ?? historyPage * pageSize)
      : historyPage * pageSize;
  const historyPageRowCount =
    state.phase === "ready" ? state.data.count : historyReturnedCount;
  const historyTotalCount =
    state.phase === "ready"
      ? Math.max(
          state.data.total_count ?? historyOffset + historyPageRowCount,
          historyOffset + historyPageRowCount,
          historyReturnedCount,
        )
      : historyReturnedCount;
  const historyBadgeLabel =
    historyTotalCount > historyReturnedCount
      ? `共 ${historyTotalCount} 条 · 第 ${historyPage + 1}/${Math.max(1, Math.ceil(historyTotalCount / pageSize))} 页`
      : `${historyReturnedCount} 条`;
  const historyPageCount = Math.max(1, Math.ceil(historyTotalCount / pageSize));
  const historyPageStart =
    historyTotalCount === 0 || historyPageRowCount === 0 ? 0 : historyOffset + 1;
  const historyPageEnd =
    historyPageRowCount === 0
      ? 0
      : Math.min(historyOffset + historyPageRowCount, historyTotalCount);
  const canGoPrev = historyPage > 0;
  const canGoNext = historyOffset + pageSize < historyTotalCount;

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between gap-3">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-emerald-500/10">
                <History className="h-4 w-4 text-emerald-400" />
              </div>
              历史面试
            </CardTitle>
            <CardDescription className="mt-1">
              数据库持久化记录，后端重启后仍可用于查看报告和回放。
            </CardDescription>
          </div>
          {state.phase === "ready" && (
            <Badge variant="outline" className="font-mono text-xs tabular-nums">
              {historyBadgeLabel}
            </Badge>
          )}
        </div>
      </CardHeader>
      <CardContent>
        {state.phase === "loading" && <LoadingList rows={4} />}
        {state.phase === "error" && <ErrorBox message={state.message} />}
        {state.phase === "ready" && state.data.sessions.length === 0 && (
          <div className="space-y-3">
            <HistoryFilterBar
              filters={filters}
              searchText={searchText}
              hasHistoryFilters={hasHistoryFilters}
              onFilterChange={setHistoryFilter}
              onSearchTextChange={onHistorySearchTextChange}
              onClear={clearHistoryFilters}
            />
            <p className="text-xs text-muted-foreground">
              {hasHistoryFilters
                ? "没有匹配的面试记录，可清除筛选条件。"
                : "暂无数据库持久化记录。完成或取消一场面试后会出现在这里。"}
            </p>
          </div>
        )}
        {state.phase === "ready" && state.data.sessions.length > 0 && (
          <div className="space-y-3">
            <HistoryFilterBar
              filters={filters}
              searchText={searchText}
              hasHistoryFilters={hasHistoryFilters}
              onFilterChange={setHistoryFilter}
              onSearchTextChange={onHistorySearchTextChange}
              onClear={clearHistoryFilters}
            />

            {filteredSessions.length === 0 ? (
              <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-border/60 py-10 text-sm text-muted-foreground">
                <Search className="mb-3 h-8 w-8 text-muted-foreground/20" />
                <p>没有匹配的面试记录</p>
                <p className="mt-1 text-[11px] text-muted-foreground/50">
                  筛选已在全部历史记录上生效。
                </p>
                <button
                  type="button"
                  onClick={clearHistoryFilters}
                  className="mt-3 rounded-md bg-muted px-3 py-1.5 text-xs text-foreground/70 transition-colors hover:bg-muted/80"
                >
                  清除筛选条件
                </button>
              </div>
            ) : (
              <>
                {/* Desktop Table */}
                <div className="hidden md:block rounded-xl border border-border/60 bg-background/50">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b border-border/60 bg-muted/40">
                        <th className="whitespace-nowrap px-3 py-3 text-left text-[11px] font-semibold text-muted-foreground">会话</th>
                        <th className="px-3 py-3 text-left text-[11px] font-semibold text-muted-foreground">岗位</th>
                        <th className="whitespace-nowrap px-3 py-3 text-left text-[11px] font-semibold text-muted-foreground">候选人</th>
                        <th className="whitespace-nowrap px-3 py-3 text-center text-[11px] font-semibold text-muted-foreground">分数</th>
                        <th className="whitespace-nowrap px-3 py-3 text-center text-[11px] font-semibold text-muted-foreground">状态 / Trace 状态</th>
                        <th className="whitespace-nowrap px-3 py-3 text-center text-[11px] font-semibold text-muted-foreground">LLM 调用</th>
                        <th className="whitespace-nowrap px-3 py-3 text-left text-[11px] font-semibold text-muted-foreground">时间</th>
                        <th className="whitespace-nowrap px-3 py-3 text-center text-[11px] font-semibold text-muted-foreground">操作</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border/40">
                      {filteredSessions.map((session, idx) => (
                        <tr
                          key={session.session_id}
                          className={cn(
                            "group transition-colors hover:bg-muted/30",
                            session.status === "completed" && session.has_report
                              ? "bg-emerald-500/[0.03]"
                              : idx % 2 === 1 && "bg-muted/10",
                          )}
                        >
                          <td className="whitespace-nowrap px-3 py-2.5">
                            <div className="flex items-center gap-1 overflow-hidden">
                              <code className="rounded bg-muted/50 px-1.5 py-0.5 font-mono text-[11px] text-foreground/80">
                                {truncate(session.session_id)}
                              </code>
                              <Button
                                type="button"
                                size="icon"
                                variant="ghost"
                                className="h-5 w-5 shrink-0 opacity-0 transition-opacity group-hover:opacity-100"
                                aria-label="复制完整 ID"
                                onClick={() => void copyToClipboard(session.session_id)}
                              >
                                <Copy className="h-3 w-3" />
                              </Button>
                            </div>
                          </td>
                          <td className="max-w-[200px] px-3 py-2.5">
                            <CellWithTooltip text={session.job_title || "未填写岗位"}>
                              <div className="overflow-hidden">
                                <div className="truncate font-medium text-foreground/90">
                                  {session.job_title || "未填写岗位"}
                                </div>
                                {session.job_level && (
                                  <div className="mt-0.5 text-[10px] text-muted-foreground/70">
                                    {session.job_level}
                                  </div>
                                )}
                              </div>
                            </CellWithTooltip>
                          </td>
                          <td className="max-w-[100px] px-2 py-2.5">
                            <CellWithTooltip text={session.candidate_name || "未填写"}>
                              <div className="overflow-hidden">
                                <div
                                  className={cn(
                                    "truncate",
                                    session.candidate_name
                                      ? "font-medium text-foreground/90"
                                      : "text-muted-foreground/60 italic",
                                  )}
                                >
                                  {session.candidate_name || "未填写"}
                                </div>
                                <div className="mt-0.5 truncate text-[10px] text-muted-foreground/70">
                                  {session.owner_email
                                    ? `Owner: ${session.owner_email}`
                                    : session.owner_user_id
                                      ? `Owner #${session.owner_user_id}`
                                      : "Anonymous"}
                                </div>
                              </div>
                            </CellWithTooltip>
                          </td>
                          <td className="whitespace-nowrap px-2 py-2.5 text-center">
                            <ScoreCell score={session.overall_score} />
                          </td>
                          <td className="whitespace-nowrap px-3 py-2.5 text-center">
                            <CombinedStatusCell session={session} />
                          </td>
                          <td className="whitespace-nowrap px-2 py-2.5 text-center">
                            <LlmCostCell cost={session.cost_summary} />
                          </td>
                          <td className="whitespace-nowrap px-3 py-2.5">
                            <HistoryTimeCell iso={session.created_at || ""} />
                          </td>
                          <td className="whitespace-nowrap px-3 py-2.5">
                            <HistorySessionActions
                              session={session}
                              onDeleted={markSessionDeleted}
                              onRefresh={onRefresh}
                            />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                {/* Mobile Card Stack */}
                <div className="grid gap-3 md:hidden">
                  {filteredSessions.map((session) => (
                    <HistoryMobileCard
                      key={session.session_id}
                      session={session}
                      onDeleted={markSessionDeleted}
                      onRefresh={onRefresh}
                    />
                  ))}
                </div>

                {/* Filtered result count */}
                {hasHistoryFilters && (
                  <p className="text-[11px] text-muted-foreground">
                    已筛选 {historyTotalCount} 条记录，当前页显示{" "}
                    {filteredSessions.length} 条。
                  </p>
                )}
                {historyTotalCount > pageSize && (
                  <div className="flex flex-col gap-2 border-t border-border/50 pt-3 sm:flex-row sm:items-center sm:justify-between">
                    <p className="text-[11px] text-muted-foreground">
                      显示 {historyPageStart}-{historyPageEnd} / {historyTotalCount} 条
                    </p>
                    <div className="flex items-center justify-end gap-2">
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        className="h-7 gap-1 px-2 text-[11px]"
                        disabled={!canGoPrev}
                        onClick={() => onHistoryPageChange(Math.max(0, historyPage - 1))}
                      >
                        <ChevronLeft className="h-3 w-3" />
                        上一页
                      </Button>
                      <span className="min-w-16 text-center font-mono text-[11px] text-muted-foreground">
                        {historyPage + 1}/{historyPageCount}
                      </span>
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        className="h-7 gap-1 px-2 text-[11px]"
                        disabled={!canGoNext}
                        onClick={() =>
                          onHistoryPageChange(
                            Math.min(historyPageCount - 1, historyPage + 1),
                          )
                        }
                      >
                        下一页
                        <ChevronRight className="h-3 w-3" />
                      </Button>
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
});

function HistoryFilterBar({
  filters,
  searchText,
  hasHistoryFilters,
  onFilterChange,
  onSearchTextChange,
  onClear,
}: {
  filters: InterviewSessionHistoryFilters;
  searchText: string;
  hasHistoryFilters: boolean;
  onFilterChange: <K extends keyof InterviewSessionHistoryFilters>(
    key: K,
    value: InterviewSessionHistoryFilters[K] | undefined,
  ) => void;
  onSearchTextChange: (text: string) => void;
  onClear: () => void;
}) {
  return (
    <div className="space-y-2 rounded-lg border border-border/50 bg-muted/20 p-3">
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-[1fr_1fr_1fr_1fr_1.4fr_auto] lg:items-end">
        <label className="grid gap-1 text-[11px] text-muted-foreground">
          状态
          <select
            aria-label="筛选面试状态"
            value={filters.status ?? ""}
            onChange={(event) =>
              onFilterChange("status", event.target.value || undefined)
            }
            className="h-8 rounded-md border bg-background px-2 text-xs text-foreground"
          >
            <option value="">全部</option>
            <option value="completed">已完成</option>
            <option value="running">进行中</option>
            <option value="cancelled">已取消</option>
            <option value="errored">出错</option>
          </select>
        </label>
        <label className="grid gap-1 text-[11px] text-muted-foreground">
          Trace 状态
          <select
            aria-label="筛选 Trace 状态"
            value={filters.traceHealth ?? ""}
            onChange={(event) =>
              onFilterChange("traceHealth", event.target.value || undefined)
            }
            className="h-8 rounded-md border bg-background px-2 text-xs text-foreground"
          >
            <option value="">全部</option>
            <option value="complete">完整</option>
            <option value="partial">部分</option>
            <option value="missing">缺失</option>
          </select>
        </label>
        <label className="grid gap-1 text-[11px] text-muted-foreground">
          报告
          <select
            aria-label="筛选报告状态"
            value={
              typeof filters.hasReport === "boolean"
                ? filters.hasReport
                  ? "with"
                  : "without"
                : ""
            }
            onChange={(event) =>
              onFilterChange(
                "hasReport",
                event.target.value === "with"
                  ? true
                  : event.target.value === "without"
                    ? false
                    : undefined,
              )
            }
            className="h-8 rounded-md border bg-background px-2 text-xs text-foreground"
          >
            <option value="">全部</option>
            <option value="with">有报告</option>
            <option value="without">无报告</option>
          </select>
        </label>
        <label className="grid gap-1 text-[11px] text-muted-foreground">
          时间范围
          <select
            aria-label="筛选创建时间范围"
            value={filters.since ?? ""}
            onChange={(event) =>
              onFilterChange("since", event.target.value || undefined)
            }
            className="h-8 rounded-md border bg-background px-2 text-xs text-foreground"
          >
            <option value="">全部</option>
            <option value="24h">最近 24 小时</option>
            <option value="7d">最近 7 天</option>
            <option value="30d">最近 30 天</option>
          </select>
        </label>
        <label className="grid gap-1 text-[11px] text-muted-foreground">
          全量搜索
          <span className="relative">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input
              type="text"
              placeholder="候选人、岗位、Session ID"
              value={searchText}
              onChange={(event) => onSearchTextChange(event.target.value)}
              className="h-8 pl-8 text-xs"
            />
          </span>
        </label>
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="h-8 px-3 text-xs"
          disabled={!hasHistoryFilters}
          onClick={onClear}
        >
          清除筛选条件
        </Button>
      </div>
      <p className="text-[11px] text-muted-foreground">
        筛选在全部历史记录上生效，再按每页 20 条分页展示。
      </p>
    </div>
  );
}

function HistoryMobileCard({
  session,
  onDeleted,
  onRefresh,
}: {
  session: InterviewSessionHistory["sessions"][number];
  onDeleted: (sessionId: string) => void;
  onRefresh: () => void;
}) {
  return (
    <div className="space-y-3 rounded-xl border border-border/60 bg-card/50 p-4">
      <div className="flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <code className="truncate rounded bg-muted/50 px-1.5 py-0.5 font-mono text-[10px] text-foreground/70">
            {truncate(session.session_id)}
          </code>
          <Button
            type="button"
            size="icon"
            variant="ghost"
            className="h-5 w-5 shrink-0"
            onClick={() => void copyToClipboard(session.session_id)}
          >
            <Copy className="h-2.5 w-2.5" />
          </Button>
        </div>
        <CombinedStatusCell session={session} />
      </div>

      <div>
        <div className="truncate text-sm font-medium">
          {session.job_title || "未填写岗位"}
        </div>
        <div className="mt-0.5 flex items-center justify-between">
          <span
            className={cn(
              "text-xs",
              session.candidate_name
                ? "text-foreground/70"
                : "italic text-muted-foreground/50",
            )}
          >
            {session.candidate_name || "未填写"}
          </span>
          {session.job_level && (
            <span className="text-[10px] text-muted-foreground/60">
              {session.job_level}
            </span>
          )}
        </div>
        <div className="mt-0.5 truncate text-[10px] text-muted-foreground/60">
          {session.owner_email
            ? `Owner: ${session.owner_email}`
            : session.owner_user_id
              ? `Owner #${session.owner_user_id}`
              : "Anonymous"}
        </div>
      </div>

      <div className="flex items-center justify-between border-t border-border/40 pt-2.5">
        <ScoreCell score={session.overall_score} />
        <LlmCostCell cost={session.cost_summary} />
        <span className="text-[11px] text-muted-foreground">
          {formatRelativeTime(session.created_at || "")}
        </span>
      </div>

      <div className="border-t border-border/40 pt-2.5">
        <HistorySessionActions
          session={session}
          onDeleted={onDeleted}
          onRefresh={onRefresh}
        />
      </div>
    </div>
  );
}

function HistorySessionActions({
  session,
  onDeleted,
  onRefresh,
}: {
  session: InterviewSessionHistory["sessions"][number];
  onDeleted: (sessionId: string) => void;
  onRefresh: () => void;
}) {
  const [deleting, setDeleting] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const { toast } = useToast();

  const handleConfirmDelete = async () => {
    setDeleting(true);
    setDeleteError(null);
    try {
      const result = await adminDeleteSession(session.session_id);
      removeEntry(session.session_id);
      onDeleted(session.session_id);
      setConfirming(false);
      toast({
        title: result.deleted ? "删除成功" : "记录已不存在",
        description: result.deleted
          ? `已删除面试记录 ${truncate(session.session_id)}${result.traces_deleted ? ` · ${result.traces_deleted} 条 trace` : ""}`
          : `后台没有找到可删除的数据；已从当前列表移除 ${truncate(session.session_id)}。`,
      });
      onRefresh();
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setDeleteError(msg);
      toast({ title: "删除失败", description: msg, variant: "destructive" });
    } finally {
      setDeleting(false);
    }
  };

  if (confirming) {
    return (
      <div className="flex items-center justify-center gap-2">
        <span className="text-[11px] text-red-400/80">永久删除？</span>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          disabled={deleting}
          className="h-6 gap-1 rounded-md border border-red-500/40 bg-red-500/10 px-2.5 text-[11px] text-red-400 hover:bg-red-500/20"
          onClick={() => void handleConfirmDelete()}
        >
          {deleting ? <Loader2 className="h-3 w-3 animate-spin" /> : <Trash2 className="h-3 w-3" />}
          确认
        </Button>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          disabled={deleting}
          className="h-6 px-2.5 text-[11px] text-muted-foreground hover:text-foreground"
          onClick={() => { setConfirming(false); setDeleteError(null); }}
        >
          取消
        </Button>
        {deleteError && (
          <span className="text-[10px] text-destructive" aria-label={deleteError}>失败</span>
        )}
      </div>
    );
  }

  return (
    <div className="flex items-center justify-center gap-1.5">
      <Button
        asChild={!!session.has_report}
        size="sm"
        variant={session.has_report ? "outline" : "ghost"}
        className={cn(
          "h-7 w-[76px] justify-center gap-1 px-2.5 text-[11px]",
          session.has_report
            ? "border-emerald-500/30 text-emerald-400 hover:bg-emerald-500/10"
            : "pointer-events-none text-muted-foreground/30",
        )}
      >
        {session.has_report ? (
          <PendingNavigationLink href={`/interview/${session.session_id}/report`}>
            <ClipboardList className="h-3 w-3" />
            查看报告
          </PendingNavigationLink>
        ) : (
          <span>
            <ClipboardList className="h-3 w-3" />
            查看报告
          </span>
        )}
      </Button>
      <Button
        asChild
        size="sm"
        variant="ghost"
        className="h-7 gap-1 px-2 text-[11px] text-muted-foreground hover:text-foreground"
      >
        <PendingNavigationLink href={`/interview/${session.session_id}/replay`}>
          <Play className="h-3 w-3" />
          回放
        </PendingNavigationLink>
      </Button>
      <Button
        asChild
        size="sm"
        variant="ghost"
        className="h-7 gap-1 px-2 text-[11px] text-muted-foreground hover:text-foreground"
      >
        <PendingNavigationLink href={`/admin/trace?sessionId=${session.session_id}`}>
          <Waypoints className="h-3 w-3" />
          Trace
        </PendingNavigationLink>
      </Button>
      <div className="group/del relative">
        <Button
          type="button"
          size="sm"
          variant="ghost"
          className="h-7 px-2 text-[11px] text-muted-foreground/50 hover:text-red-400 hover:bg-red-500/10"
          onClick={() => setConfirming(true)}
        >
          <Trash2 className="h-3 w-3" />
        </Button>
        <div className="pointer-events-none absolute bottom-full left-1/2 z-[100] mb-2 hidden -translate-x-1/2 group-hover/del:block">
          <div className="whitespace-nowrap rounded-lg border border-border bg-popover px-3 py-1.5 text-xs text-popover-foreground shadow-xl">
            删除此面试记录
          </div>
        </div>
      </div>
    </div>
  );
}

function CombinedStatusCell({
  session,
}: {
  session: InterviewSessionHistory["sessions"][number];
}) {
  return (
    <div className="flex flex-col items-center gap-1">
      <HistoryStatusBadge session={session} />
      {session.status === "completed" && session.trace_health && (
        <TraceStatusBadge health={session.trace_health} />
      )}
    </div>
  );
}

function HistoryTimeCell({ iso }: { iso: string }) {
  const compact = formatCompactDate(iso);
  const full = formatDateTime(iso);
  const relative = formatRelativeTime(iso);
  return (
    <div className="group/time relative">
      <span className="whitespace-nowrap font-mono text-[11px] text-muted-foreground/70">
        {compact}
      </span>
      <div className="pointer-events-none absolute bottom-full left-0 z-[100] mb-2 hidden group-hover/time:block">
        <div className="whitespace-nowrap rounded-lg border border-border bg-popover px-3 py-1.5 text-xs text-popover-foreground shadow-xl">
          <span className="font-mono">{full}</span>
          <span className="ml-2 text-muted-foreground">{relative}</span>
        </div>
      </div>
    </div>
  );
}

function formatCompactDate(iso: string): string {
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "\u2014";
    const now = new Date();
    const month = d.getMonth() + 1;
    const day = d.getDate();
    const h = d.getHours().toString().padStart(2, "0");
    const m = d.getMinutes().toString().padStart(2, "0");
    if (d.getFullYear() === now.getFullYear()) {
      return `${month}/${day} ${h}:${m}`;
    }
    return `${d.getFullYear()}/${month}/${day}`;
  } catch {
    return iso;
  }
}

function CellWithTooltip({
  text,
  children,
}: {
  text: string;
  children: React.ReactNode;
}) {
  if (!text || text.length <= 12) return <>{children}</>;
  return (
    <div className="group/tip relative overflow-visible">
      {children}
      <div className="pointer-events-none absolute bottom-full left-0 z-[100] mb-2 hidden group-hover/tip:block">
        <div className="whitespace-nowrap rounded-lg border border-border bg-popover px-3 py-1.5 text-xs text-popover-foreground shadow-xl">
          {text}
        </div>
      </div>
    </div>
  );
}

function LlmCostCell({
  cost,
}: {
  cost?: InterviewSessionHistoryItem["cost_summary"];
}) {
  if (!cost || !cost.calls) {
    return <span className="text-[10px] italic text-muted-foreground/25">—</span>;
  }
  const totalTokens = (cost.prompt_tokens ?? 0) + (cost.completion_tokens ?? 0);
  const tokenLabel =
    totalTokens >= 1_000_000
      ? `${(totalTokens / 1_000_000).toFixed(1)}M`
      : totalTokens >= 1_000
        ? `${(totalTokens / 1_000).toFixed(1)}K`
        : String(totalTokens);
  return (
    <span className="inline-flex flex-col items-center gap-0.5">
      <span className="font-mono text-[11px] font-medium tabular-nums text-foreground/80">
        {cost.calls}<span className="text-muted-foreground/50">{" "}次</span>
      </span>
      {totalTokens > 0 && (
        <span className="text-[10px] text-muted-foreground/60">{tokenLabel} tok</span>
      )}
      {typeof cost.est_usd === "number" && cost.est_usd > 0 && (
        <span className="text-[10px] font-mono text-amber-400/80">
          ${cost.est_usd < 0.01 ? "<0.01" : cost.est_usd.toFixed(2)}
        </span>
      )}
    </span>
  );
}

function ScoreCell({ score }: { score?: number | null }) {
  if (typeof score !== "number") {
    return (
      <span className="inline-flex flex-col items-center gap-0.5">
        <span className="text-[10px] italic text-muted-foreground/25">未评分</span>
      </span>
    );
  }
  const pct = Math.min(100, Math.max(0, (score / 10) * 100));
  const barColor =
    score >= 8
      ? "bg-emerald-400"
      : score >= 6
        ? "bg-sky-400"
        : score >= 4
          ? "bg-amber-400"
          : "bg-red-400";
  const textColor =
    score >= 8
      ? "text-emerald-400"
      : score >= 6
        ? "text-sky-400"
        : score >= 4
          ? "text-amber-400"
          : "text-red-400";
  return (
    <span className="inline-flex flex-col items-center gap-1">
      <span className="flex items-baseline gap-0.5 font-mono tabular-nums">
        <span className={`text-sm font-bold ${textColor}`}>{score.toFixed(1)}</span>
        <span className="text-[9px] text-muted-foreground/50">/10</span>
      </span>
      <span className="h-1 w-12 overflow-hidden rounded-full bg-muted/40">
        <span
          className={`block h-full rounded-full ${barColor} transition-all`}
          style={{ width: `${pct}%` }}
        />
      </span>
    </span>
  );
}

function HistoryStatusBadge({
  session,
}: {
  session: InterviewSessionHistory["sessions"][number];
}) {
  const status = formatHistoryStatus(session.status);
  if (status.variant === "success") {
    return (
      <Badge variant="success" className="gap-1 text-[10px]">
        <span className="inline-block h-1.5 w-1.5 rounded-full bg-emerald-400" />
        {status.label}
      </Badge>
    );
  }
  if (status.variant === "warn") {
    return (
      <Badge variant="warn" className="gap-1 text-[10px]">
        <span className="inline-block h-1.5 w-1.5 rounded-full bg-amber-400" />
        {status.label}
      </Badge>
    );
  }
  if (status.variant === "destructive" || session.error_kind) {
    return (
      <Badge variant="destructive" className="gap-1 text-[10px]">
        <span className="inline-block h-1.5 w-1.5 rounded-full bg-red-400" />
        {status.label}
      </Badge>
    );
  }
  return (
    <Badge variant="outline" className="gap-1 text-[10px] text-muted-foreground">
      <span className="inline-block h-1.5 w-1.5 rounded-full bg-muted-foreground/50" />
      {status.label}
    </Badge>
  );
}

function formatHistoryStatus(status: string): {
  label: string;
  variant: "success" | "warn" | "destructive" | "outline";
} {
  switch (status) {
    case "completed":
      return { label: "已完成", variant: "success" };
    case "cancelled":
      return { label: "已取消", variant: "warn" };
    case "errored":
      return { label: "出错", variant: "destructive" };
    case "running":
      return { label: "进行中", variant: "outline" };
    case "interrupted":
      return { label: "可恢复", variant: "outline" };
    default:
      return { label: status || "未知", variant: "outline" };
  }
}

function TraceStatusBadge({
  health,
}: {
  health?: InterviewSessionHistory["sessions"][number]["trace_health"];
}) {
  if (health === "complete") {
    return (
      <Badge variant="success" className="gap-1 text-[10px]">
        <span className="inline-block h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" />
        Trace 完整
      </Badge>
    );
  }
  if (health === "partial") {
    return (
      <Badge variant="warn" className="gap-1 text-[10px]">
        <span className="inline-block h-1.5 w-1.5 rounded-full bg-amber-400" />
        Trace 部分
      </Badge>
    );
  }
  if (health === "missing") {
    return (
      <Badge variant="destructive" className="gap-1 text-[10px]">
        <span className="inline-block h-1.5 w-1.5 rounded-full bg-destructive" />
        Trace 缺失
      </Badge>
    );
  }
  return (
    <span className="text-[10px] text-muted-foreground/30">—</span>
  );
}

function LangSmithCell({
  session,
  langsmith,
}: {
  session: AdminSessions["sessions"][number];
  langsmith: AdminSessions["langsmith"];
}) {
  const webUrl = langsmith?.web_url || "https://smith.langchain.com";
  const runId = session.langsmith_run_id;
  const copyValue = runId || session.trace_id;
  const projectHint = langsmith?.project ? ` (${langsmith.project})` : "";
  const openTitle = runId
    ? `打开 LangSmith${projectHint}，复制 run id 后可定位该运行`
    : `打开 LangSmith${projectHint}，复制 trace id 后可搜索该会话`;

  return (
    <div className="flex min-w-[160px] items-center gap-1.5">
      <Button
        asChild
        size="sm"
        variant={runId ? "outline" : "ghost"}
        className="h-7 gap-1.5 px-2 text-[11px]"
        aria-label={openTitle}
      >
        <a href={webUrl} target="_blank" rel="noreferrer">
          {runId ? (
            <ExternalLink className="h-3.5 w-3.5" />
          ) : (
            <Search className="h-3.5 w-3.5" />
          )}
          <span className="font-mono">{runId ? truncate(runId) : "trace"}</span>
        </a>
      </Button>
      <Button
        type="button"
        size="icon"
        variant="ghost"
        className="h-7 w-7"
        aria-label={runId ? "复制 LangSmith run id" : "复制 trace id"}
        onClick={() => void copyToClipboard(copyValue)}
      >
        <Copy className="h-3.5 w-3.5" />
      </Button>
    </div>
  );
}

function SessionStatusBadge({ session }: { session: AdminSessions["sessions"][number] }) {
  if (session.cancelled) {
    return <Badge variant="destructive" className="text-[10px]">已取消</Badge>;
  }
  if (session.error) {
    return <Badge variant="destructive" className="text-[10px]">出错</Badge>;
  }
  if (session.done) {
    return <Badge variant="success" className="text-[10px]">已完成</Badge>;
  }
  if (session.has_question) {
    return <Badge variant="warn" className="text-[10px]">等待回答</Badge>;
  }
  return (
    <Badge variant="outline" className="text-[10px]">
      <Loader2 className="mr-1 h-3 w-3 animate-spin" />
      运行中
    </Badge>
  );
}

// ---------------------------------------------------------------------------
// Strategies memory
// ---------------------------------------------------------------------------

function QuestionBankCard({
  state,
  usages,
  usageStats,
  usageStatsPage,
  onUsageStatsPageChange,
  rewardReadiness,
  rerankUsages,
  reviews,
  onRefresh,
}: {
  state: Loadable<QuestionSeeds>;
  usages: Loadable<QuestionUsages>;
  usageStats: Loadable<QuestionUsageStatsResponse>;
  usageStatsPage: number;
  onUsageStatsPageChange: (page: number) => void;
  rewardReadiness: Loadable<QuestionRewardReadiness>;
  rerankUsages: Loadable<QuestionRerankUsages>;
  reviews: Loadable<QuestionReviews>;
  onRefresh: () => void;
}) {
  const { toast } = useToast();
  const [selectedSeedId, setSelectedSeedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<Loadable<QuestionSeedDetail> | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [seedSearch, setSeedSearch] = useState("");
  const [seedDimension, setSeedDimension] = useState("all");
  const [seedDirection, setSeedDirection] = useState("all");
  const [seedRole, setSeedRole] = useState("all");
  const [seedStatus, setSeedStatus] = useState("active");
  const questionSeedRows = useMemo(
    () => (state.phase === "ready" ? state.data.question_seeds : []),
    [state],
  );
  const questionSeedTitleById = useMemo(
    () => new Map(questionSeedRows.map((seed) => [seed.id, seed.title])),
    [questionSeedRows],
  );
  const seedReadinessById = useMemo(() => {
    const rows = rewardReadiness.phase === "ready" ? rewardReadiness.data.seeds ?? [] : [];
    return new Map(rows.map((row) => [row.seed_id ?? row.scope_key, row]));
  }, [rewardReadiness]);
  const questionStatusCounts = useMemo(
    () =>
      questionSeedRows.reduce<Record<string, number>>((acc, seed) => {
        const status = seed.status || "unknown";
        acc[status] = (acc[status] ?? 0) + 1;
        return acc;
      }, {}),
    [questionSeedRows],
  );
  const questionDimensions = useMemo(
    () =>
      Array.from(new Set(questionSeedRows.map((seed) => seed.dimension).filter(Boolean))).sort(),
    [questionSeedRows],
  );
  const questionDirections = useMemo(
    () =>
      Array.from(
        new Set(questionSeedRows.flatMap((seed) => seed.direction_tags).filter(Boolean)),
      ).sort(),
    [questionSeedRows],
  );
  const questionRoles = useMemo(
    () =>
      Array.from(
        new Set(questionSeedRows.flatMap((seed) => seed.role_tags).filter(Boolean)),
      ).sort(),
    [questionSeedRows],
  );
  const questionStatuses = useMemo(
    () =>
      Array.from(
        new Set(questionSeedRows.map((seed) => seed.status || "unknown")),
      ).sort(),
    [questionSeedRows],
  );
  const filteredQuestionSeeds = useMemo(() => {
    const q = seedSearch.trim().toLowerCase();
    return questionSeedRows
      .filter((seed) => {
        const matchesSearch =
          !q ||
          seed.title.toLowerCase().includes(q) ||
          seed.id.toLowerCase().includes(q) ||
          seed.skill_tags.some((tag) => tag.toLowerCase().includes(q));
        const matchesDimension =
          seedDimension === "all" || seed.dimension === seedDimension;
        const matchesDirection =
          seedDirection === "all" || seed.direction_tags.includes(seedDirection);
        const matchesRole =
          seedRole === "all" || seed.role_tags.includes(seedRole);
        const matchesStatus = seedStatus === "all" || (seed.status || "unknown") === seedStatus;
        return (
          matchesSearch &&
          matchesDimension &&
          matchesDirection &&
          matchesRole &&
          matchesStatus
        );
      })
      .sort(compareQuestionSeedRows);
  }, [
    questionSeedRows,
    seedDimension,
    seedDirection,
    seedRole,
    seedSearch,
    seedStatus,
  ]);
  const displayedQuestionUsageEvents = useMemo(
    () =>
      usages.phase === "ready"
        ? groupQuestionUsageEvents(usages.data.usages).slice(0, 5)
        : [],
    [usages],
  );
  const displayedQuestionReranks = useMemo(
    () =>
      rerankUsages.phase === "ready"
        ? [...rerankUsages.data.rerank_usages]
            .sort(compareQuestionRerankRows)
            .slice(0, 3)
        : [],
    [rerankUsages],
  );
  const displayedQuestionReviews = useMemo(
    () =>
      reviews.phase === "ready"
        ? [...reviews.data.reviews].sort(compareQuestionReviewRows).slice(0, 3)
        : [],
    [reviews],
  );

  useEffect(() => {
    if (state.phase !== "ready") return;
    const selectedStillVisible = filteredQuestionSeeds.some(
      (seed) => seed.id === selectedSeedId,
    );
    if (selectedSeedId && selectedStillVisible) return;
    setSelectedSeedId(filteredQuestionSeeds[0]?.id ?? null);
  }, [filteredQuestionSeeds, selectedSeedId, state.phase]);

  useEffect(() => {
    if (!selectedSeedId) {
      setDetail(null);
      return;
    }
    const ctrl = new AbortController();
    setDetail({ phase: "loading" });
    getQuestionSeed(selectedSeedId, ctrl.signal)
      .then((data) => {
        if (!ctrl.signal.aborted) setDetail({ phase: "ready", data });
      })
      .catch((err) => {
        if (!ctrl.signal.aborted) {
          setDetail({
            phase: "error",
            message: err instanceof Error ? err.message : String(err),
          });
        }
      });
    return () => ctrl.abort();
  }, [selectedSeedId]);

  async function handleImport(archiveMissing: boolean) {
    if (busy) return;
    setBusy(archiveMissing ? "import-archive" : "import");
    try {
      const result = await importQuestionSeeds(archiveMissing);
      toast({
        title: "结构化题库已导入",
        description: `主题 +${result.imported_seeds}/${result.updated_seeds}，题目变体 +${result.imported_variants}/${result.updated_variants}，归档 ${result.archived_seeds + result.archived_variants}`,
      });
      onRefresh();
    } catch (err) {
      toast({
        title: "结构化题库导入失败",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    } finally {
      setBusy(null);
    }
  }

  async function handleLint(strictQuality: boolean) {
    if (busy) return;
    setBusy(strictQuality ? "lint-strict" : "lint");
    try {
      const result = await runQuestionSeedLint(strictQuality);
      toast({
        title: result.passed ? "题库质量 lint 通过" : "题库质量 lint 有阻断项",
        description: `warnings=${result.warning_count}, errors=${result.error_count}`,
        variant: result.passed ? undefined : "destructive",
      });
      onRefresh();
    } catch (err) {
      toast({
        title: "题库质量 lint 失败",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    } finally {
      setBusy(null);
    }
  }

  async function handleReviewFromRerank(winner: "rule" | "llm" | "tie" | "neither") {
    if (busy || rerankUsages.phase !== "ready") return;
    const row = displayedQuestionReranks[0];
    if (!row) return;
    setBusy(`review:${winner}`);
    try {
      await createQuestionReview({
        question_rerank_usage_id: row.id,
        session_id: row.session_id,
        turn_idx: row.turn_idx,
        trace_id: row.trace_id,
        rule_variant_id: row.rule_top_variant_id,
        llm_variant_id: row.llm_top_variant_id,
        winner,
        reasons: ["admin_pairwise_review"],
        notes: "",
        reviewer: "admin",
        context_summary: {
          dimension: row.dimension,
          probe_intent: row.probe_intent,
          anchor_choice: row.anchor_choice,
        },
      });
      toast({ title: "pairwise review 已记录" });
      onRefresh();
    } catch (err) {
      toast({
        title: "pairwise review 记录失败",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    } finally {
      setBusy(null);
    }
  }

  async function handleSeedAction(seedId: string, action: "disable" | "archive") {
    if (busy) return;
    setBusy(`${action}:${seedId}`);
    try {
      const result =
        action === "disable"
          ? await disableQuestionSeed(seedId)
          : await archiveQuestionSeed(seedId);
      toast({
        title: "题目主题状态已更新",
        description: `${result.id} -> ${result.status}`,
      });
      onRefresh();
      setSelectedSeedId(seedId);
    } catch (err) {
      toast({
        title: "题目主题操作失败",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    } finally {
      setBusy(null);
    }
  }

  async function handleVariantAction(
    variantId: string,
    action: "disable" | "archive",
  ) {
    if (busy) return;
    setBusy(`${action}:${variantId}`);
    try {
      const result =
        action === "disable"
          ? await disableQuestionVariant(variantId)
          : await archiveQuestionVariant(variantId);
      toast({
        title: "题目变体状态已更新",
        description: `${result.id} -> ${result.status}`,
      });
      onRefresh();
      if (selectedSeedId) {
        const refreshed = await getQuestionSeed(selectedSeedId);
        setDetail({ phase: "ready", data: refreshed });
      }
    } catch (err) {
      toast({
        title: "题目变体操作失败",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    } finally {
      setBusy(null);
    }
  }

  async function handleQuestionRewardRollout(
    scope: QuestionRewardRolloutScope,
    scopeKey: string,
    mode: QuestionRewardRolloutMode,
  ) {
    if (busy) return;
    const busyKey = `question-rollout:${scope}:${scopeKey}:${mode}`;
    setBusy(busyKey);
    try {
      await setQuestionRewardRollout(scope, scopeKey, {
        mode,
        reason:
          mode === "reward"
            ? "admin reward ranking pilot"
            : "admin fallback to reward shadow",
      });
      const rolloutTarget =
        scope === "context" ? "context" : scope === "seed" ? "seed" : "scope";
      toast({
        title: `题库 ${rolloutTarget} reward 排序灰度已更新`,
        description: `${scopeKey} -> ${mode}`,
      });
      onRefresh();
    } catch (err) {
      toast({
        title: "题库 reward 排序灰度更新失败",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    } finally {
      setBusy(null);
    }
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <ClipboardList className="h-4 w-4 text-sky-400" />
              结构化题库
            </CardTitle>
            <CardDescription className="mt-1">
              YAML 导入的结构化出题资产，用于候选题匹配、题干生成和评分约束。
            </CardDescription>
          </div>
          <div className="flex flex-wrap justify-end gap-2">
            {state.phase === "ready" && (
              <Badge variant="outline" className="font-mono text-[10px]">
                {state.data.count} 主题
              </Badge>
            )}
            {usages.phase === "ready" && (
              <Badge variant="secondary" className="font-mono text-[10px]">
                {usages.data.count} 调用
              </Badge>
            )}
            {rerankUsages.phase === "ready" && (
              <Badge variant="outline" className="font-mono text-[10px]">
                {rerankUsages.data.count} 重排
              </Badge>
            )}
            {reviews.phase === "ready" && (
              <Badge variant="outline" className="font-mono text-[10px]">
                {reviews.data.count} 评审
              </Badge>
            )}
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border bg-secondary/20 p-3">
          <div>
            <p className="text-sm font-medium">YAML 导入</p>
            <p className="text-xs text-muted-foreground">
              内容编辑仍在 knowledge/question_seeds；一个 seed 是一个题目主题，一个
              variant 是该主题下的一种问法/追问角度。
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => handleImport(false)}
              disabled={busy !== null}
            >
              {busy === "import" && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              导入 YAML
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => handleImport(true)}
              disabled={busy !== null}
            >
              {busy === "import-archive" && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              归档缺失
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => handleLint(false)}
              disabled={busy !== null}
            >
              {busy === "lint" && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              检查
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => handleLint(true)}
              disabled={busy !== null}
            >
              {busy === "lint-strict" && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              严格检查
            </Button>
          </div>
        </div>

        <QuestionRewardRolloutPanel
          readiness={rewardReadiness}
          onQuestionRewardRollout={handleQuestionRewardRollout}
        />

        <QuestionRewardShadowDiagnosticsPanel
          stats={usageStats}
          statsPage={usageStatsPage}
          onStatsPageChange={onUsageStatsPageChange}
          readiness={rewardReadiness}
          onRefresh={onRefresh}
        />

        {state.phase === "loading" && <LoadingList rows={3} />}
        {state.phase === "error" && <ErrorBox message={state.message} />}
        {state.phase === "ready" && state.data.question_seeds.length === 0 && (
          <p className="text-xs text-muted-foreground">
            暂无结构化题目主题。先导入 YAML 后再查看题库资产。
          </p>
        )}
        {state.phase === "ready" && state.data.question_seeds.length > 0 && (
          <>
          <QuestionBankFilters
            search={seedSearch}
            onSearchChange={setSeedSearch}
            dimension={seedDimension}
            onDimensionChange={setSeedDimension}
            dimensions={questionDimensions}
            direction={seedDirection}
            onDirectionChange={setSeedDirection}
            directions={questionDirections}
            role={seedRole}
            onRoleChange={setSeedRole}
            roles={questionRoles}
            status={seedStatus}
            onStatusChange={setSeedStatus}
            statuses={questionStatuses}
            statusCounts={questionStatusCounts}
            shown={filteredQuestionSeeds.length}
            total={state.data.question_seeds.length}
          />
          {filteredQuestionSeeds.length === 0 ? (
            <p className="rounded-md border border-dashed bg-muted/10 p-3 text-xs text-muted-foreground">
              当前筛选下没有题目主题。调整筛选条件后再看。
            </p>
          ) : (
          <div className="grid gap-3 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.25fr)]">
            <aside className="space-y-2" aria-label="题库资产概览">
              <div>
                <p className="text-xs font-medium text-foreground">
                  题库资产概览
                </p>
                <p className="mt-0.5 text-[11px] text-muted-foreground">
                  当前筛选下的题目主题多展示一些，超过后在左侧滚动。
                </p>
              </div>
              <ul className="max-h-[1440px] space-y-2 overflow-y-auto pr-1">
                {filteredQuestionSeeds.map((seed) => {
                  const seedReadiness = seedReadinessById.get(seed.id);
                  return (
                  <li
                    key={seed.id}
                    className={cn(
                      "rounded-lg border bg-card/50 p-3 text-sm",
                      selectedSeedId === seed.id && "border-primary/50",
                    )}
                  >
                    <button
                      type="button"
                      className="w-full text-left"
                      onClick={() => setSelectedSeedId(seed.id)}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <span className="min-w-0 truncate font-medium">{seed.title}</span>
                        <Badge variant="outline" className="font-mono text-[10px]">
                          {formatQuestionAssetStatus(seed.status)}
                        </Badge>
                      </div>
                      <div className="mt-1 font-mono text-[10px] text-muted-foreground">
                        {seed.id}
                      </div>
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        <Badge variant="secondary" className="font-mono text-[10px]">
                          {seed.dimension}
                        </Badge>
                        {seed.direction_tags.slice(0, 2).map((tag) => (
                          <Badge key={tag} variant="outline" className="font-mono text-[10px]">
                            {tag}
                          </Badge>
                        ))}
                        {seed.role_tags.slice(0, 2).map((tag) => (
                          <Badge key={tag} variant="outline" className="font-mono text-[10px]">
                            {tag}
                          </Badge>
                        ))}
                        <Badge variant="outline" className="font-mono text-[10px]">
                          {seed.variant_count ?? 0} 题目变体
                        </Badge>
                        {seedReadiness && (
                          <Badge variant="outline" className="font-mono text-[10px]">
                            reward 排序灰度: {seedReadiness.rollout.mode}
                          </Badge>
                        )}
                        {seedReadiness && (
                          <Badge variant="secondary" className="font-mono text-[10px]">
                            reward {seedReadiness.rewarded_usage_count}
                          </Badge>
                        )}
                        {seed.job_levels.slice(0, 3).map((level) => (
                          <Badge key={level} variant="outline" className="font-mono text-[10px]">
                            {level}
                          </Badge>
                        ))}
                      </div>
                    </button>
                    <div className="mt-3 flex flex-wrap gap-2">
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        onClick={() => handleSeedAction(seed.id, "disable")}
                        disabled={busy !== null || seed.status !== "active"}
                      >
                        禁用
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        variant="ghost"
                        onClick={() => handleSeedAction(seed.id, "archive")}
                        disabled={busy !== null || seed.status === "archived"}
                      >
                        归档
                      </Button>
                    </div>
                  </li>
                  );
                })}
              </ul>
            </aside>

            <QuestionSeedDetailPanel
              detail={detail}
              busy={busy}
              readiness={
                detail?.phase === "ready"
                  ? seedReadinessById.get(detail.data.seed.id) ?? null
                  : null
              }
              onQuestionRewardRollout={handleQuestionRewardRollout}
              onVariantAction={handleVariantAction}
            />
          </div>
          )}
          </>
        )}

        <details className="rounded-md border border-dashed bg-muted/10 px-3 py-2">
          <summary className="cursor-pointer text-xs font-medium text-muted-foreground">
            选题诊断
          </summary>
          <div className="mt-3 space-y-3">
            <p className="text-[11px] text-muted-foreground">
              观察最近选题记录、规则 selector 与 Shadow reranker 的分歧，以及人工评审样本。
            </p>
        {usages.phase === "ready" && displayedQuestionUsageEvents.length > 0 && (
          <div className="space-y-2">
            <div>
              <p className="text-xs font-medium text-muted-foreground">最近出题事件</p>
              <p className="mt-0.5 text-[11px] text-muted-foreground">
                按 session + turn 聚合同轮候选，快速观察最近真实出题和备选分差。
              </p>
            </div>
            <ul className="space-y-1.5">
              {displayedQuestionUsageEvents.map((event) => {
                const injected = event.injected;
                const eventTitle = injected
                  ? formatQuestionUsageTitle(injected, questionSeedTitleById)
                  : "未记录实际出题";
                return (
                <li key={event.key} className="rounded-md border bg-card/30 p-3 text-[11px]">
                  <div className="space-y-2">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <Badge
                        variant={injected ? "success" : "outline"}
                        className="font-mono text-[10px]"
                      >
                        {injected ? formatQuestionUsageSelectionLabel(injected) : "无实际题"}
                      </Badge>
                      {(event.role_tags ?? []).map((tag) => (
                        <Badge key={tag} variant="outline" className="font-mono text-[10px]">
                          {tag}
                        </Badge>
                      ))}
                    </div>
                    <div
                      aria-label="出题事件元信息"
                      className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-foreground"
                    >
                      <span className="inline-flex min-w-0 items-center gap-1">
                        <span>Session：</span>
                        <SessionIdTooltip sessionId={event.session_id} side="top" />
                      </span>
                      <span>第 {event.turn_idx} 轮</span>
                      <span>{event.question_selector_mode}</span>
                    </div>
                  </div>
                  <p className="mt-2 text-sm font-medium text-foreground">
                    {eventTitle}
                  </p>
                  <div className="mt-1 flex flex-wrap gap-3 text-muted-foreground">
                    <span>{formatQuestionUsageEventCandidateSummary(event)}</span>
                    <span>{formatQuestionUsageEventScore(event)}</span>
                  </div>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {event.candidates.slice(0, 3).map((candidate) => (
                      <Badge
                        key={candidate.id}
                        variant={candidate.injected ? "success" : "outline"}
                        className="whitespace-normal font-mono text-[10px] leading-snug"
                      >
                        #{candidate.rank} {candidate.injected ? "实际" : "候选"}{" "}
                        {formatMaybeNumber(candidate.match_score)}
                      </Badge>
                    ))}
                  </div>
                  <details className="mt-2">
                    <summary className="cursor-pointer text-[11px] text-muted-foreground">
                      候选 Top 与开发详情
                    </summary>
                    <div className="mt-2 space-y-2">
                      {event.candidates.map((candidate) => (
                        <div
                          key={candidate.id}
                          className="rounded-md border bg-background/30 px-2 py-1.5"
                        >
                          <div className="flex flex-wrap gap-2 text-muted-foreground">
                            <span className="font-mono">rank {candidate.rank}</span>
                            <span>匹配分 {formatMaybeNumber(candidate.match_score)}</span>
                            <span>
                              {candidate.injected
                                ? formatQuestionUsageCandidateScore(candidate)
                                : "未采用，不回填"}
                            </span>
                          </div>
                          <div className="mt-1 break-words font-mono text-[10px] text-muted-foreground">
                            {formatQuestionUsageTitle(candidate, questionSeedTitleById)}
                          </div>
                        </div>
                      ))}
                    </div>
                    <div className="mt-2 space-y-1 font-mono text-[10px] text-muted-foreground">
                      <div>selector: {event.question_selector_mode}</div>
                      <div className="break-all">session_id: {event.session_id}</div>
                      {injected && (
                        <>
                          <div className="break-all">seed_id: {injected.seed_id}</div>
                          <div className="break-all">variant_id: {injected.variant_id}</div>
                        </>
                      )}
                    </div>
                  </details>
                  <div className="mt-2">
                    <Button asChild variant="ghost" size="sm" className="h-7 px-2 text-[11px]">
                      <PendingNavigationLink href={`/admin/trace?sessionId=${event.session_id}`}>
                        <ExternalLink className="mr-1 h-3 w-3" />
                        Trace Explorer
                      </PendingNavigationLink>
                    </Button>
                  </div>
                </li>
                );
              })}
            </ul>
          </div>
        )}

        {usages.phase === "ready" &&
          usages.data.usages.length > 0 &&
          displayedQuestionUsageEvents.length === 0 && (
            <p className="rounded-md border border-dashed bg-muted/10 p-3 text-xs text-muted-foreground">
              最近 question_usages 暂时无法聚合成出题事件。
            </p>
          )}

        {rerankUsages.phase === "ready" && rerankUsages.data.rerank_usages.length > 0 && (
          <div className="space-y-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <p className="text-xs font-medium text-muted-foreground">
                  重排分歧观察
                </p>
                <p className="mt-0.5 text-[11px] text-muted-foreground">
                  Shadow reranker 只做旁路观察，不直接改写实际出题。
                </p>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {(["rule", "llm", "tie", "neither"] as const).map((winner) => (
                  <Button
                    key={winner}
                    type="button"
                    size="sm"
                    variant={winner === "llm" ? "outline" : "ghost"}
                    onClick={() => handleReviewFromRerank(winner)}
                    disabled={busy !== null || displayedQuestionReranks.length === 0}
                  >
                    {formatQuestionReviewWinner(winner)}
                  </Button>
                ))}
              </div>
            </div>
            <ul className="space-y-1.5">
              {displayedQuestionReranks.map((row) => (
                <li key={row.id} className="rounded-md border bg-card/30 p-3 text-[11px]">
                  <div className="flex flex-wrap gap-1.5">
                    <Badge
                      variant={row.status === "ok" ? "success" : "warn"}
                      className="font-mono text-[10px]"
                    >
                      {formatQuestionRerankStatus(row.status)}
                    </Badge>
                    <Badge variant="outline" className="font-mono text-[10px]">
                      第 {row.turn_idx} 轮
                    </Badge>
                    <Badge variant="secondary" className="font-mono text-[10px]">
                      置信度 {formatMaybeNumber(row.confidence)}
                    </Badge>
                    <Badge variant="outline" className="font-mono text-[10px]">
                      {formatQuestionRerankDecision(row)}
                    </Badge>
                  </div>
                  <div className="mt-2 grid gap-2 sm:grid-cols-2">
                    <QuestionDiagnosticChoice
                      label="规则首选"
                      value={row.rule_top_variant_id}
                    />
                    <QuestionDiagnosticChoice
                      label="模型首选"
                      value={row.llm_top_variant_id}
                    />
                  </div>
                  {row.anchor_choice && (
                    <p className="mt-2 text-[11px] text-muted-foreground">
                      候选锚点：{row.anchor_choice}
                    </p>
                  )}
                  <details className="mt-2">
                    <summary className="cursor-pointer text-[11px] text-muted-foreground">
                      开发详情
                    </summary>
                    <div className="mt-1 space-y-1 font-mono text-[10px] text-muted-foreground">
                      <div>selector: {row.question_selector_mode}</div>
                      <div>model: {row.model ?? "-"}</div>
                      <div>latency_ms: {row.latency_ms ?? "-"}</div>
                      {row.reasons.length > 0 && (
                        <div className="break-words">
                          reasons: {row.reasons.slice(0, 3).join(", ")}
                        </div>
                      )}
                    </div>
                  </details>
                </li>
              ))}
            </ul>
          </div>
        )}

        {reviews.phase === "ready" && reviews.data.reviews.length > 0 && (
          <div className="space-y-2">
            <div>
              <p className="text-xs font-medium text-muted-foreground">
                人工评审样本
              </p>
              <p className="mt-0.5 text-[11px] text-muted-foreground">
                记录人工对规则首选和模型首选的判断，用来校准 selector/reranker。
              </p>
            </div>
            <ul className="space-y-1.5">
              {displayedQuestionReviews.map((review) => (
                <li key={review.id} className="rounded-md border bg-card/30 p-3 text-[11px]">
                  <div className="flex flex-wrap gap-1.5">
                    <Badge variant="outline" className="font-mono text-[10px]">
                      第 {review.turn_idx} 轮
                    </Badge>
                    <Badge variant="secondary" className="font-mono text-[10px]">
                      结论：{formatQuestionReviewWinner(review.winner)}
                    </Badge>
                  </div>
                  <div className="mt-2 grid gap-2 sm:grid-cols-2">
                    <QuestionDiagnosticChoice
                      label="规则题"
                      value={review.rule_variant_id}
                    />
                    <QuestionDiagnosticChoice
                      label="模型题"
                      value={review.llm_variant_id}
                    />
                  </div>
                  {review.reasons.length > 0 && (
                    <p className="mt-1 text-muted-foreground">
                      原因：{review.reasons.slice(0, 2).join(", ")}
                    </p>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}
        {usages.phase === "ready" &&
          rerankUsages.phase === "ready" &&
          reviews.phase === "ready" &&
          usages.data.usages.length === 0 &&
          rerankUsages.data.rerank_usages.length === 0 &&
          reviews.data.reviews.length === 0 && (
            <p className="text-xs text-muted-foreground">
              当前暂无选题调用、重排或评审样本，这不是错误。完成几轮面试后会出现选题诊断数据。
            </p>
          )}
          </div>
        </details>
      </CardContent>
    </Card>
  );
}

function QuestionRewardTopKList({
  label,
  description,
  suffix = "完整 Top K",
  values,
}: {
  label: string;
  description?: string;
  suffix?: string;
  values: string[];
}) {
  return (
    <div className="min-w-0 rounded-md border bg-background/40 px-2 py-1.5">
      <p className="text-[10px] text-muted-foreground">
        {label}
        {suffix ? ` · ${suffix}` : ""}
      </p>
      {description && (
        <p className="mt-0.5 text-[10px] leading-relaxed text-muted-foreground">
          {description}
        </p>
      )}
      {values.length > 0 ? (
        <ol className="mt-1 space-y-1">
          {values.map((value, index) => (
            <li key={`${label}:${value}:${index}`} className="flex min-w-0 gap-2">
              <span className="shrink-0 font-mono text-[10px] text-muted-foreground">
                #{index + 1}
              </span>
              <span className="min-w-0 break-all font-mono text-[11px] font-medium text-foreground">
                {value}
              </span>
            </li>
          ))}
        </ol>
      ) : (
        <p className="mt-1 text-[11px] text-muted-foreground">—</p>
      )}
    </div>
  );
}

function QuestionRewardRolloutPanel({
  readiness,
  onQuestionRewardRollout,
}: {
  readiness: Loadable<QuestionRewardReadiness>;
  onQuestionRewardRollout: (
    scope: QuestionRewardRolloutScope,
    scopeKey: string,
    mode: QuestionRewardRolloutMode,
  ) => void;
}) {
  const readinessData = readiness.phase === "ready" ? readiness.data : null;
  const summary = readinessData?.summary ?? null;
  return (
    <section className="rounded-lg border bg-card/35 p-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-foreground">
            题库 Reward 排序灰度
          </h3>
          <p className="mt-1 text-xs text-muted-foreground">
            只控制候选题排序，不切换 structured_primary / structured_shadow；context 控制跨 Seed 排序，seed 控制同 Seed 内 Variant。
          </p>
        </div>
        {readinessData && (
          <Badge variant="outline" className="font-mono text-[10px]">
            ranking: {readinessData.reward_ranking_mode}
          </Badge>
        )}
      </div>

      {readiness.phase === "loading" && (
        <div className="mt-3">
          <LoadingList rows={2} />
        </div>
      )}
      {readiness.phase === "error" && (
        <ErrorBox message={`question reward readiness: ${readiness.message}`} />
      )}

      {summary && (
        <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
          <StrategyMemoryInlineMetric
            label="候选题 variants"
            value={String(readinessData?.candidate_count ?? summary.total_variants)}
          />
          <StrategyMemoryInlineMetric
            label="usage 样本"
            value={String(readinessData?.usage_count ?? summary.usage_count ?? 0)}
          />
          <StrategyMemoryInlineMetric
            label="reward 样本"
            value={String(
              readinessData?.rewarded_usage_count
                ?? summary.rewarded_usage_count
                ?? 0,
            )}
          />
          <StrategyMemoryInlineMetric
            label="readiness"
            value={readinessData?.readiness ?? summary.readiness ?? "unknown"}
          />
        </div>
      )}

      {readinessData && (
        <QuestionRewardContextReadinessList
          contexts={readinessData.contexts ?? []}
          onQuestionRewardRollout={onQuestionRewardRollout}
        />
      )}
    </section>
  );
}

function QuestionRewardModeStatus({
  label,
  backendKey,
  value,
}: {
  label: string;
  backendKey: string;
  value: string;
}) {
  return (
    <div className="min-w-[220px] rounded-md border bg-muted/10 px-2.5 py-1.5">
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
        <span className="text-[10px] font-medium uppercase tracking-normal text-muted-foreground">
          {label}
        </span>
        <span className="font-mono text-[10px] text-muted-foreground">
          {backendKey}
        </span>
      </div>
      <p className="mt-0.5 break-all font-mono text-[11px] font-semibold text-foreground">
        {value}
      </p>
    </div>
  );
}

function QuestionRewardShadowDiagnosticsPanel({
  stats,
  statsPage,
  onStatsPageChange,
  readiness,
  onRefresh,
}: {
  stats: Loadable<QuestionUsageStatsResponse>;
  statsPage: number;
  onStatsPageChange: (page: number) => void;
  readiness: Loadable<QuestionRewardReadiness>;
  onRefresh: () => void;
}) {
  const { toast } = useToast();
  const [busy, setBusy] = useState(false);
  const readinessData = readiness.phase === "ready" ? readiness.data : null;
  const statRows = stats.phase === "ready" ? stats.data.stats : [];

  async function handleRefreshQuestionStats() {
    if (busy) return;
    setBusy(true);
    try {
      const result = await refreshQuestionUsageStats();
      toast({
        title: "题库 reward shadow 已刷新",
        description: `refreshed=${result.refreshed}, deleted=${result.deleted}`,
      });
      onStatsPageChange(0);
      onRefresh();
    } catch (err) {
      toast({
        title: "题库 reward shadow 刷新失败",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="rounded-lg border bg-card/35 p-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-[11px] font-medium text-muted-foreground">
            全局总览
          </p>
          <h3 className="text-sm font-semibold text-foreground">
            全局题库排序模拟
          </h3>
          <p className="mt-1 text-xs text-muted-foreground">
            范围：全局。基于历史 QuestionUsage 中出现过、当前仍启用的题目变体做整体信号观察；这里不直接开启 live 排序，真实单轮候选请看 Trace Explorer 的 ask_question / 结构化题库。
          </p>
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={handleRefreshQuestionStats}
          disabled={busy}
        >
          {busy && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
          刷新 stats
        </Button>
      </div>

      {(stats.phase === "loading" || readiness.phase === "loading") && (
        <div className="mt-3">
          <LoadingList rows={2} />
        </div>
      )}
      {stats.phase === "error" && (
        <ErrorBox message={`question usage stats: ${stats.message}`} />
      )}
      {readiness.phase === "error" && (
        <ErrorBox message={`question reward readiness: ${readiness.message}`} />
      )}

      {readinessData && (
        <div className="mt-3 rounded-md border bg-background/40 p-2 text-[11px]">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div className="flex flex-wrap gap-2">
              <QuestionRewardModeStatus
                label="范围"
                backendKey="scope"
                value="global"
              />
              <QuestionRewardModeStatus
                label="题库选择模式"
                backendKey="selector_rollout_mode"
                value={readinessData.selector_rollout_mode}
              />
              <QuestionRewardModeStatus
                label="Reward 排序模式"
                backendKey="reward_ranking_mode"
                value={readinessData.reward_ranking_mode}
              />
            </div>
            <Badge
              variant={readinessData.rank_changed ? "warn" : "outline"}
              className="text-[10px]"
            >
              {readinessData.rank_changed
                ? "模拟 reward 后 Top K 会变化"
                : "模拟 reward 后 Top K 不变"}
            </Badge>
          </div>
          <details className="mt-2 rounded-md border border-dashed bg-background/40 p-2">
            <summary className="cursor-pointer text-muted-foreground">
              展开排序模拟与就绪诊断
            </summary>
            <div className="mt-2 grid gap-2">
              <QuestionRewardTopKList
                label="静态优先级 Top K · metadata_top_variant_ids"
                description="按 seed.priority + variant.priority 排序。"
                suffix=""
                values={readinessData.metadata_top_variant_ids}
              />
              <QuestionRewardTopKList
                label="reward 模拟 Top K · reward_top_variant_ids"
                description="在静态优先级基础上叠加历史 reward、样本置信度和使用次数。"
                suffix=""
                values={readinessData.reward_top_variant_ids}
              />
            </div>
            {readinessData.reasons.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {readinessData.reasons.map((reason) => (
                  <Badge key={reason} variant="outline" className="text-[10px]">
                    {formatQuestionRewardReason(reason)} · {reason}
                  </Badge>
                ))}
              </div>
            )}
          </details>
        </div>
      )}

      {stats.phase === "ready" && statRows.length > 0 && (
        <QuestionUsageStatsList
          rows={statRows}
          count={stats.data.count}
          limit={stats.data.limit ?? QUESTION_USAGE_STATS_PAGE_SIZE}
          offset={
            stats.data.offset ?? statsPage * QUESTION_USAGE_STATS_PAGE_SIZE
          }
          onPageChange={onStatsPageChange}
        />
      )}
    </section>
  );
}

type QuestionUsageStatsRow = QuestionUsageStatsResponse["stats"][number];

function QuestionRewardContextReadinessList({
  contexts,
  onQuestionRewardRollout,
}: {
  contexts: QuestionRewardReadinessGroup[];
  onQuestionRewardRollout: (
    scope: QuestionRewardRolloutScope,
    scopeKey: string,
    mode: QuestionRewardRolloutMode,
  ) => void;
}) {
  const visibleContexts = contexts.slice(0, 8);
  return (
    <section className="mt-3 rounded-md border bg-background/40 px-3 py-2">
      <div className="text-xs font-semibold text-foreground">
        Context 级灰度候选
      </div>
      <p className="mt-0.5 text-[11px] text-muted-foreground">
        范围：direction / role / level / dimension。这里才是 context 级 reward 灰度开关；context 只按历史 usage 分组，不重放单轮 resume anchor / skills / qa_history 等动态匹配条件。
      </p>
      <div className="mt-2 space-y-2">
        {visibleContexts.length === 0 ? (
          <p className="text-[11px] text-muted-foreground">
            暂无带 question_context_key 的 usage；新跑面试后会出现 context 级诊断。
          </p>
        ) : (
          visibleContexts.map((context) => (
            <QuestionRewardReadinessRow
              key={context.context_key ?? context.scope_key}
              group={context}
              primaryLabel={context.context_key ?? context.scope_key}
              onQuestionRewardRollout={onQuestionRewardRollout}
            />
          ))
        )}
        {contexts.length > visibleContexts.length && (
          <p className="text-[11px] text-muted-foreground">
            已展示前 {visibleContexts.length} 个 context；完整列表保留在 readiness payload。
          </p>
        )}
      </div>
    </section>
  );
}

function QuestionRewardReadinessRow({
  group,
  primaryLabel,
  onQuestionRewardRollout,
}: {
  group: QuestionRewardReadinessGroup;
  primaryLabel: string;
  onQuestionRewardRollout: (
    scope: QuestionRewardRolloutScope,
    scopeKey: string,
    mode: QuestionRewardRolloutMode,
  ) => void;
}) {
  const scope = group.scope;
  const scopeKey = group.scope_key;
  return (
    <div className="rounded-md border bg-background/40 p-2 text-[11px]">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="break-all font-mono text-xs font-semibold text-foreground">
            {primaryLabel}
          </p>
          <p className="mt-1 text-muted-foreground">
            candidates {group.candidate_count} · usage {group.usage_count} · reward {group.rewarded_usage_count}
          </p>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-1.5">
          <Badge variant={group.rank_changed ? "warn" : "outline"} className="text-[10px]">
            {group.rank_changed ? "模拟 reward 后 Top K 会变化" : "模拟 reward 后 Top K 不变"}
          </Badge>
          <Badge variant="secondary" className="font-mono text-[10px]">
            override {group.rollout.mode}
          </Badge>
        </div>
      </div>
      <div className="mt-2 grid gap-2 md:grid-cols-2">
        <QuestionRewardTopKList
          label="静态优先级 Top K"
          description="按 seed.priority + variant.priority 排序。"
          suffix=""
          values={group.metadata_top_variant_ids}
        />
        <QuestionRewardTopKList
          label="reward 模拟 Top K"
          description="叠加历史 reward、样本置信度和使用次数的 shadow 排序。"
          suffix=""
          values={group.reward_top_variant_ids}
        />
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        {group.reasons.map((reason) => (
          <Badge key={reason} variant="outline" className="text-[10px]">
            {formatQuestionRewardReason(reason)} · {reason}
          </Badge>
        ))}
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="h-7 text-[11px]"
          onClick={() => onQuestionRewardRollout(scope, scopeKey, "reward")}
        >
          开启 reward
        </Button>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          className="h-7 text-[11px]"
          onClick={() => onQuestionRewardRollout(scope, scopeKey, "reward_shadow")}
        >
          回退 shadow
        </Button>
      </div>
    </div>
  );
}

function QuestionUsageStatsList({
  rows,
  count,
  limit,
  offset,
  onPageChange,
}: {
  rows: QuestionUsageStatsRow[];
  count: number;
  limit: number;
  offset: number;
  onPageChange: (page: number) => void;
}) {
  const currentPageIndex = Math.floor(offset / Math.max(1, limit));
  const currentPage = currentPageIndex + 1;
  const totalPages = Math.max(1, Math.ceil(count / Math.max(1, limit)));
  const hasPrevious = currentPageIndex > 0;
  const hasNext = offset + rows.length < count;
  return (
    <details className="mt-3 rounded-md border border-dashed bg-muted/10 px-3 py-2">
      <summary className="cursor-pointer text-xs font-medium text-muted-foreground">
        question_usage_stats
      </summary>
      <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
        <div className="space-y-0.5">
          <p className="text-[11px] font-medium text-foreground">
            第 {currentPage} / {totalPages} 页 · 已加载 {rows.length} / 共{" "}
            {count} 条
          </p>
          <p className="text-[11px] text-muted-foreground">
            每页 {limit} 条，按后端稳定排序分页；variant_id 保持完整展示。
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={!hasPrevious}
            onClick={() => onPageChange(Math.max(0, currentPageIndex - 1))}
            className="h-7 text-[11px]"
          >
            上一页
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={!hasNext}
            onClick={() => onPageChange(currentPageIndex + 1)}
            className="h-7 text-[11px]"
          >
            下一页
          </Button>
        </div>
      </div>
      <ul className="mt-2 space-y-2">
        {rows.map((row) => (
          <li key={row.id} className="rounded-md border bg-background/40 p-2 text-[11px]">
            <div className="flex min-w-0 flex-col gap-1">
              <div className="flex flex-wrap items-center gap-1.5">
                <Badge variant="secondary" className="font-mono text-[10px]">
                  {row.question_selector_mode}
                </Badge>
                <span className="text-[10px] text-muted-foreground">
                  variant_id
                </span>
              </div>
              <p className="break-all font-mono text-[11px] font-medium text-foreground">
                {row.variant_id}
              </p>
            </div>
            <div className="mt-2 grid gap-1.5 sm:grid-cols-2 lg:grid-cols-4">
              <QuestionUsageStatsMetric
                label="使用次数 uses"
                value={String(row.uses)}
              />
              <QuestionUsageStatsMetric
                label="注入次数 injected"
                value={String(row.injected_uses)}
              />
              <QuestionUsageStatsMetric
                label="奖励样本 rewarded"
                value={String(row.rewarded_uses)}
              />
              <QuestionUsageStatsMetric
                label="平均分 avg_score"
                value={formatMaybeNumber(row.avg_score)}
              />
              <QuestionUsageStatsMetric
                label="通过率 pass_rate"
                value={row.pass_rate == null ? "—" : formatPercent(row.pass_rate)}
              />
              <QuestionUsageStatsMetric
                label="平均奖励 avg_reward"
                value={formatMaybeNumber(row.avg_immediate_reward)}
              />
              <QuestionUsageStatsMetric
                label="最近使用 last_used"
                value={formatQuestionUsageStatsTime(row.last_used_at)}
              />
              <QuestionUsageStatsMetric
                label="更新时间 updated"
                value={formatQuestionUsageStatsTime(row.updated_at)}
              />
            </div>
          </li>
        ))}
      </ul>
    </details>
  );
}

function QuestionUsageStatsMetric({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div className="min-w-0 rounded-md border bg-background/40 px-2 py-1.5">
      <p className="text-[10px] text-muted-foreground">{label}</p>
      <p className="mt-0.5 break-words font-mono text-[11px] font-medium text-foreground">
        {value}
      </p>
    </div>
  );
}

function formatQuestionUsageStatsTime(value?: string | null): string {
  return value ? formatDateTime(value) : "—";
}

type QuestionVariantAction = "disable" | "archive";
type QuestionVariantRow = QuestionSeedDetail["variants"][number];

function QuestionSeedDetailPanel({
  detail,
  busy,
  readiness,
  onQuestionRewardRollout,
  onVariantAction,
}: {
  detail: Loadable<QuestionSeedDetail> | null;
  busy: string | null;
  readiness: QuestionRewardReadinessGroup | null;
  onQuestionRewardRollout: (
    scope: QuestionRewardRolloutScope,
    scopeKey: string,
    mode: QuestionRewardRolloutMode,
  ) => void;
  onVariantAction: (
    variantId: string,
    action: QuestionVariantAction,
  ) => void;
}) {
  if (!detail) {
    return (
      <div className="rounded-lg border border-dashed bg-card/30 p-4 text-xs text-muted-foreground">
        选择左侧题目主题后查看题目变体和出题配置。
      </div>
    );
  }

  if (detail.phase === "loading") {
    return (
      <div className="rounded-lg border bg-card/40 p-3">
        <LoadingList rows={4} />
      </div>
    );
  }

  if (detail.phase === "error") {
    return (
      <div className="rounded-lg border bg-card/40 p-3">
        <ErrorBox message={detail.message} />
      </div>
    );
  }

  const { seed, variants } = detail.data;
  return (
    <div className="rounded-lg border bg-card/40 p-4">
      <div className="space-y-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-[11px] font-medium text-muted-foreground">
              题目主题
            </p>
            <h3 className="mt-1 text-sm font-semibold text-foreground">
              {seed.title}
            </h3>
            <p className="mt-1 break-all font-mono text-[10px] text-muted-foreground">
              {seed.id}
            </p>
          </div>
          <div className="flex flex-wrap justify-end gap-1.5">
            <Badge variant="outline" className="font-mono text-[10px]">
              状态：{formatQuestionAssetStatus(seed.status)}
            </Badge>
            <Badge variant="secondary" className="font-mono text-[10px]">
              priority {seed.priority ?? 0}
            </Badge>
            <Badge variant="outline" className="font-mono text-[10px]">
              {variants.length} 题目变体
            </Badge>
          </div>
        </div>

        <p className="rounded-md border border-dashed bg-background/30 px-3 py-2 text-[11px] text-muted-foreground">
          一个 seed 是一个题目主题，一个 variant 是该主题下的一种问法/追问角度。
        </p>

        <QuestionSeedRewardReadinessPanel
          readiness={readiness}
          seedId={seed.id}
          onQuestionRewardRollout={onQuestionRewardRollout}
        />

        <div className="grid gap-2 text-xs sm:grid-cols-2">
          <QuestionMetaItem label="维度" value={seed.dimension} />
          <QuestionMetaItem
            label="适用级别"
            value={seed.job_levels.join(" / ") || "-"}
          />
          <QuestionMetaItem label="来源" value={seed.source || "-"} />
          <QuestionMetaItem label="语言" value={seed.language || "-"} />
        </div>

        <div className="space-y-2">
          <QuestionConfigRow label="方向标签" values={seed.direction_tags} />
          <QuestionConfigRow label="角色标签" values={seed.role_tags} />
          <QuestionConfigRow
            label="技能标签"
            values={seed.skill_tags}
            badgeVariant="secondary"
          />
        </div>

        <Separator />

        <div className="space-y-3">
          <div className="flex flex-wrap items-end justify-between gap-2">
            <div>
              <p className="text-sm font-semibold text-foreground">题目变体</p>
              <p className="mt-0.5 text-[11px] text-muted-foreground">
                默认先看出题内容；评分与诊断配置折叠保存。
              </p>
            </div>
            <Badge variant="outline" className="font-mono text-[10px]">
              {variants.length} 题目变体
            </Badge>
          </div>

          {variants.map((variant) => (
            <QuestionVariantDetailCard
              key={variant.id}
              variant={variant}
              busy={busy}
              onAction={onVariantAction}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

function QuestionSeedRewardReadinessPanel({
  readiness,
  seedId,
  onQuestionRewardRollout,
}: {
  readiness: QuestionRewardReadinessGroup | null;
  seedId: string;
  onQuestionRewardRollout: (
    scope: QuestionRewardRolloutScope,
    scopeKey: string,
    mode: QuestionRewardRolloutMode,
  ) => void;
}) {
  if (!readiness) {
    return (
      <div className="rounded-md border border-dashed bg-muted/10 px-3 py-2 text-[11px] text-muted-foreground">
        Seed 内 Variant 灰度暂无 usage 样本；新跑面试后会出现 Seed 级诊断。
      </div>
    );
  }
  return (
    <div className="rounded-md border bg-background/40 p-3 text-[11px]">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="text-xs font-semibold text-foreground">
            Seed 内 Variant 灰度
          </p>
          <p className="mt-1 text-muted-foreground">
            范围：当前 Seed。只影响该 Seed 下多个 Variant 的 reward 排序；不按 context 分组，也不切换 structured_primary。
          </p>
        </div>
        <div className="flex flex-wrap justify-end gap-1.5">
          <Badge variant="secondary" className="font-mono text-[10px]">
            override {readiness.rollout.mode}
          </Badge>
          <Badge variant={readiness.rank_changed ? "warn" : "outline"} className="text-[10px]">
            {readiness.rank_changed ? "模拟 reward 后 Top K 会变化" : "模拟 reward 后 Top K 不变"}
          </Badge>
        </div>
      </div>
      <div className="mt-2 grid gap-2 sm:grid-cols-3">
        <QuestionUsageStatsMetric
          label="active variants"
          value={String(readiness.active_variant_count ?? readiness.candidate_count)}
        />
        <QuestionUsageStatsMetric
          label="usage 样本"
          value={String(readiness.usage_count)}
        />
        <QuestionUsageStatsMetric
          label="reward 样本"
          value={String(readiness.rewarded_usage_count)}
        />
      </div>
      <div className="mt-2 grid gap-2 md:grid-cols-2">
        <QuestionRewardTopKList
          label="静态优先级 Top K"
          description="按当前 Seed 内 active Variant 的 priority 排序。"
          suffix=""
          values={readiness.metadata_top_variant_ids}
        />
        <QuestionRewardTopKList
          label="reward 模拟 Top K"
          description="在静态优先级基础上叠加该 Seed 下 Variant 的历史 reward。"
          suffix=""
          values={readiness.reward_top_variant_ids}
        />
      </div>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {readiness.reasons.map((reason) => (
          <Badge key={reason} variant="outline" className="text-[10px]">
            {formatQuestionRewardReason(reason)} · {reason}
          </Badge>
        ))}
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="h-7 text-[11px]"
          onClick={() => onQuestionRewardRollout("seed", seedId, "reward")}
        >
          开启 reward
        </Button>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          className="h-7 text-[11px]"
          onClick={() => onQuestionRewardRollout("seed", seedId, "reward_shadow")}
        >
          回退 shadow
        </Button>
      </div>
    </div>
  );
}

function QuestionMetaItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border bg-background/30 px-3 py-2">
      <p className="text-[10px] text-muted-foreground">{label}</p>
      <p className="mt-1 break-words font-mono text-[11px] text-foreground">
        {value}
      </p>
    </div>
  );
}

function QuestionVariantDetailCard({
  variant,
  busy,
  onAction,
}: {
  variant: QuestionVariantRow;
  busy: string | null;
  onAction: (variantId: string, action: QuestionVariantAction) => void;
}) {
  return (
    <article className="space-y-3 rounded-md border bg-background/40 p-3 text-xs">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div>
            <span className="font-medium text-foreground">题目变体</span>
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            <Badge variant="secondary" className="font-mono text-[10px]">
              问法：{variant.intent}
            </Badge>
            <Badge variant="outline" className="font-mono text-[10px]">
              难度：{variant.difficulty}
            </Badge>
          </div>
          <p className="mt-1 break-all font-mono text-[10px] text-muted-foreground">
            {variant.id}
          </p>
        </div>
        <div className="flex flex-wrap justify-end gap-1.5">
          <Badge
            variant={questionAssetStatusBadgeVariant(variant.status)}
            className="font-mono text-[10px]"
          >
            状态：{formatQuestionAssetStatus(variant.status)}
          </Badge>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            onClick={() => onAction(variant.id, "disable")}
            disabled={busy !== null || variant.status !== "active"}
          >
            禁用
          </Button>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            onClick={() => onAction(variant.id, "archive")}
            disabled={busy !== null || variant.status === "archived"}
          >
            归档
          </Button>
        </div>
      </div>

      <section className="space-y-2">
        <p className="text-[11px] font-medium text-foreground">出题内容</p>
        <QuestionTextBlock label="场景" value={variant.scenario_brief} />
        <QuestionTextBlock label="题干" value={variant.question_stem} />
        <QuestionTextBlock
          label="生成模板"
          value={variant.prompt_template}
          mono
        />
      </section>

      <details className="rounded-md border border-dashed bg-muted/10 px-3 py-2">
        <summary className="cursor-pointer text-[11px] font-medium text-muted-foreground">
          评分与诊断配置
        </summary>
        <div className="mt-3 space-y-2">
          <QuestionConfigRow
            label="匹配技能"
            values={variant.scenario_skill_tags}
            badgeVariant="secondary"
          />
          <QuestionConfigRow
            label="简历锚点"
            values={variant.resume_anchor_hints}
          />
          <QuestionConfigRow
            label="失败类型"
            values={variant.failure_categories}
          />
          <QuestionConfigRow
            label="评分补充"
            values={variant.rubric_additions}
          />
          <QuestionConfigRow
            label="期望信号"
            values={variant.expected_signals}
          />
          <QuestionConfigRow label="反模式" values={variant.anti_patterns} />
          <QuestionConfigRow
            label="好答案提示"
            values={variant.good_answer_hints}
          />
          <QuestionConfigRow label="角色标签" values={variant.role_tags} />
        </div>
      </details>
    </article>
  );
}

function QuestionTextBlock({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  if (!value) return null;
  return (
    <div className="rounded-md bg-muted/15 px-3 py-2">
      <p className="text-[10px] text-muted-foreground">{label}</p>
      <p
        className={cn(
          "mt-1 whitespace-pre-wrap break-words leading-relaxed text-foreground",
          mono && "font-mono text-[11px]",
        )}
      >
        {value}
      </p>
    </div>
  );
}

function QuestionConfigRow({
  label,
  values,
  badgeVariant = "outline",
}: {
  label: string;
  values: string[];
  badgeVariant?: React.ComponentProps<typeof Badge>["variant"];
}) {
  if (values.length === 0) return null;
  return (
    <div className="grid gap-1.5 sm:grid-cols-[88px_minmax(0,1fr)]">
      <span className="text-[10px] text-muted-foreground">{label}</span>
      <div className="flex min-w-0 flex-wrap gap-1.5">
        {values.map((value, index) => (
          <Badge
            key={`${label}-${value}-${index}`}
            variant={badgeVariant}
            className="max-w-full whitespace-normal break-words font-mono text-[10px] leading-snug"
          >
            {value}
          </Badge>
        ))}
      </div>
    </div>
  );
}

type QuestionSeedRow = QuestionSeeds["question_seeds"][number];
type QuestionUsageRow = QuestionUsages["usages"][number];
type QuestionUsageEvent = {
  key: string;
  session_id: string;
  turn_idx: number;
  trace_id?: string | null;
  question_selector_mode: string;
  createdAtMs: number;
  candidates: QuestionUsageRow[];
  injected: QuestionUsageRow | null;
  role_tags: string[];
  direction_tags: string[];
};
type QuestionRerankRow = QuestionRerankUsages["rerank_usages"][number];
type QuestionReviewRow = QuestionReviews["reviews"][number];

function compareQuestionSeedRows(a: QuestionSeedRow, b: QuestionSeedRow): number {
  return (
    questionStatusRank(a.status) - questionStatusRank(b.status) ||
    a.dimension.localeCompare(b.dimension) ||
    (b.priority ?? 0) - (a.priority ?? 0) ||
    a.id.localeCompare(b.id)
  );
}

function questionStatusRank(status?: string | null): number {
  if (status === "active") return 0;
  if (status === "disabled") return 1;
  if (status === "archived") return 2;
  return 3;
}

function formatQuestionAssetStatus(status?: string | null): string {
  if (status === "active") return "可用";
  if (status === "disabled") return "禁用";
  if (status === "archived") return "归档";
  return status || "未知";
}

function questionAssetStatusBadgeVariant(
  status?: string | null,
): React.ComponentProps<typeof Badge>["variant"] {
  if (status === "active") return "secondary";
  if (status === "disabled") return "warn";
  if (status === "archived") return "outline";
  return "outline";
}

function formatQuestionUsageSelectionLabel(usage: QuestionUsageRow): string {
  if (usage.injected) return "实际出题";
  return `候选第 ${usage.rank} 名`;
}

function groupQuestionUsageEvents(usages: QuestionUsageRow[]): QuestionUsageEvent[] {
  const events = new Map<string, QuestionUsageEvent>();
  for (const usage of usages) {
    const key = `${usage.session_id}::${usage.turn_idx}::${usage.question_selector_mode}`;
    const createdAtMs = questionUsageCreatedAtMs(usage);
    const existing = events.get(key);
    if (!existing) {
      events.set(key, {
        key,
        session_id: usage.session_id,
        turn_idx: usage.turn_idx,
        trace_id: usage.trace_id,
        question_selector_mode: usage.question_selector_mode,
        createdAtMs,
        candidates: [usage],
        injected: usage.injected ? usage : null,
        role_tags: usage.role_tags ?? [],
        direction_tags: usage.direction_tags ?? [],
      });
      continue;
    }
    existing.candidates.push(usage);
    existing.createdAtMs = Math.max(existing.createdAtMs, createdAtMs);
    existing.trace_id = existing.trace_id ?? usage.trace_id;
    if (usage.injected) existing.injected = usage;
    if (existing.role_tags.length === 0 && usage.role_tags?.length) {
      existing.role_tags = usage.role_tags;
    }
    if (existing.direction_tags.length === 0 && usage.direction_tags?.length) {
      existing.direction_tags = usage.direction_tags;
    }
  }
  return Array.from(events.values())
    .map((event) => ({
      ...event,
      candidates: [...event.candidates].sort(
        (a, b) =>
          a.rank - b.rank ||
          Number(b.injected) - Number(a.injected) ||
          compareQuestionUsageRows(a, b),
      ),
    }))
    .sort(compareQuestionUsageEvents);
}

function compareQuestionUsageEvents(a: QuestionUsageEvent, b: QuestionUsageEvent): number {
  return b.createdAtMs - a.createdAtMs || b.turn_idx - a.turn_idx;
}

function compareQuestionUsageRows(a: QuestionUsageRow, b: QuestionUsageRow): number {
  return (
    questionUsageCreatedAtMs(b) - questionUsageCreatedAtMs(a) ||
    b.turn_idx - a.turn_idx ||
    Number(b.injected) - Number(a.injected) ||
    a.rank - b.rank
  );
}

function compareQuestionRerankRows(a: QuestionRerankRow, b: QuestionRerankRow): number {
  return (
    questionRerankCreatedAtMs(b) - questionRerankCreatedAtMs(a) ||
    b.turn_idx - a.turn_idx
  );
}

function compareQuestionReviewRows(a: QuestionReviewRow, b: QuestionReviewRow): number {
  return (
    questionReviewCreatedAtMs(b) - questionReviewCreatedAtMs(a) ||
    b.turn_idx - a.turn_idx
  );
}

function questionUsageCreatedAtMs(usage: QuestionUsageRow): number {
  const value = Date.parse(usage.created_at ?? "");
  return Number.isFinite(value) ? value : 0;
}

function questionRerankCreatedAtMs(row: QuestionRerankRow): number {
  const value = Date.parse(row.created_at ?? "");
  return Number.isFinite(value) ? value : 0;
}

function questionReviewCreatedAtMs(row: QuestionReviewRow): number {
  const value = Date.parse(row.created_at ?? "");
  return Number.isFinite(value) ? value : 0;
}

function formatQuestionUsageTitle(
  usage: QuestionUsageRow,
  seedTitleById: Map<string, string>,
): string {
  const seedTitle = seedTitleById.get(usage.seed_id) ?? compactQuestionAssetId(usage.seed_id);
  const variantTail = compactQuestionAssetId(usage.variant_id);
  return `${seedTitle}：${variantTail}`;
}

function formatQuestionUsageEventCandidateSummary(event: QuestionUsageEvent): string {
  const injectedRank = event.injected?.rank;
  const rankCopy = injectedRank == null ? "无实际题" : `实际题 rank ${injectedRank}`;
  return `候选 Top ${event.candidates.length}，${rankCopy}`;
}

function formatQuestionUsageEventScore(event: QuestionUsageEvent): string {
  if (!event.injected) return "无评分回填目标";
  return formatQuestionUsageCandidateScore(event.injected);
}

function formatQuestionUsageCandidateScore(candidate: QuestionUsageRow): string {
  const score =
    candidate.score == null
      ? "评分未回填"
      : `评分 ${formatMaybeNumber(candidate.score)}`;
  const reward =
    candidate.immediate_reward == null
      ? "奖励未回填"
      : `奖励 ${formatMaybeNumber(candidate.immediate_reward)}`;
  return `${score} / ${reward}`;
}

function compactQuestionAssetId(value: string): string {
  const parts = value.split(".").filter(Boolean);
  const tail = parts.at(-1) ?? value;
  return tail.replace(/_/g, " ");
}

function formatQuestionRerankStatus(status?: string | null): string {
  if (status === "ok") return "已完成";
  if (status === "error") return "异常";
  if (status === "skipped") return "跳过";
  return status || "未知";
}

function formatQuestionRerankDecision(row: QuestionRerankRow): string {
  if (!row.rule_top_variant_id && !row.llm_top_variant_id) return "无首选";
  if (row.rule_top_variant_id === row.llm_top_variant_id) return "规则与模型一致";
  return "存在分歧";
}

function formatQuestionReviewWinner(winner: QuestionReviewRow["winner"]): string {
  if (winner === "rule") return "规则更好";
  if (winner === "llm") return "模型更好";
  if (winner === "tie") return "两者接近";
  if (winner === "neither") return "都不合适";
  return winner;
}

function QuestionDiagnosticChoice({
  label,
  value,
}: {
  label: string;
  value?: string | null;
}) {
  return (
    <div className="rounded-md border bg-background/30 px-3 py-2">
      <p className="text-[10px] text-muted-foreground">{label}</p>
      <p className="mt-1 break-words font-mono text-[11px] text-foreground">
        {value ? compactQuestionAssetId(value) : "未记录"}
      </p>
    </div>
  );
}

function QuestionBankFilters({
  search,
  onSearchChange,
  dimension,
  onDimensionChange,
  dimensions,
  direction,
  onDirectionChange,
  directions,
  role,
  onRoleChange,
  roles,
  status,
  onStatusChange,
  statuses,
  statusCounts,
  shown,
  total,
}: {
  search: string;
  onSearchChange: (value: string) => void;
  dimension: string;
  onDimensionChange: (value: string) => void;
  dimensions: string[];
  direction: string;
  onDirectionChange: (value: string) => void;
  directions: string[];
  role: string;
  onRoleChange: (value: string) => void;
  roles: string[];
  status: string;
  onStatusChange: (value: string) => void;
  statuses: string[];
  statusCounts: Record<string, number>;
  shown: number;
  total: number;
}) {
  const statusOptions = Array.from(new Set(["active", ...statuses]));
  return (
    <div className="rounded-md border bg-muted/10 p-3">
      <div className="flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <p className="text-xs font-medium text-foreground">题库筛选</p>
          <p className="mt-0.5 text-[11px] text-muted-foreground">
            当前显示 {shown}/{total} 个题目主题。
          </p>
        </div>
        <div className="grid min-w-0 gap-2 sm:grid-cols-2 lg:min-w-[720px] lg:grid-cols-3 xl:min-w-[900px] xl:grid-cols-5">
          <Input
            name="question-seed-search"
            autoComplete="off"
            aria-label="搜索题目主题"
            placeholder="搜索标题、ID、技能…"
            value={search}
            onChange={(event) => onSearchChange(event.target.value)}
            className="h-8 text-xs"
          />
          <select
            name="question-seed-status"
            aria-label="按状态筛选题目主题"
            value={status}
            onChange={(event) => onStatusChange(event.target.value)}
            className="h-8 rounded-md border bg-background px-2 text-xs text-foreground"
          >
            <option value="all">全部状态 ({total})</option>
            {statusOptions.map((item) => (
              <option key={item} value={item}>
                {formatQuestionAssetStatus(item)} ({statusCounts[item] ?? 0})
              </option>
            ))}
          </select>
          <select
            name="question-seed-dimension"
            aria-label="按能力维度筛选题目主题"
            value={dimension}
            onChange={(event) => onDimensionChange(event.target.value)}
            className="h-8 rounded-md border bg-background px-2 text-xs text-foreground"
          >
            <option value="all">全部维度</option>
            {dimensions.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
          <select
            name="question-seed-direction"
            aria-label="按方向筛选题目主题"
            value={direction}
            onChange={(event) => onDirectionChange(event.target.value)}
            className="h-8 rounded-md border bg-background px-2 text-xs text-foreground"
          >
            <option value="all">全部方向</option>
            {directions.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
          <select
            name="question-seed-role"
            aria-label="按角色筛选题目主题"
            value={role}
            onChange={(event) => onRoleChange(event.target.value)}
            className="h-8 rounded-md border bg-background px-2 text-xs text-foreground"
          >
            <option value="all">全部角色</option>
            {roles.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
        </div>
      </div>
    </div>
  );
}

type SkillPlaybookRow = SkillPlaybooks["skill_playbooks"][number];

function SkillRewardRolloutPanel({
  readiness,
  busyKey,
  onSkillRewardRollout,
}: {
  readiness: Loadable<SkillRewardReadiness>;
  busyKey: string | null;
  onSkillRewardRollout: (
    contextKey: string,
    mode: SkillRewardRolloutMode,
  ) => void;
}) {
  const readinessData = readiness.phase === "ready" ? readiness.data : null;
  const summary = readinessData?.summary ?? null;
  const contexts = readinessData?.contexts ?? [];
  return (
    <section className="rounded-lg border bg-card/35 p-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-foreground">
            Skill Reward 排序灰度
          </h3>
          <p className="mt-1 text-xs text-muted-foreground">
            Context 级开关只控制 retrieve_skills() 的 live reward 排序；默认 reward_shadow 只模拟，不改变真实返回顺序。
          </p>
        </div>
        {readinessData && (
          <Badge variant="outline" className="font-mono text-[10px]">
            ranking: {readinessData.reward_ranking_mode ?? "reward_shadow"}
          </Badge>
        )}
      </div>

      {readiness.phase === "loading" && (
        <div className="mt-3">
          <LoadingList rows={2} />
        </div>
      )}
      {readiness.phase === "error" && (
        <ErrorBox message={`skill reward readiness: ${readiness.message}`} />
      )}

      {summary && (
        <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
          <StrategyMemoryInlineMetric
            label="Skill 总数"
            value={String(summary.total_skills)}
          />
          <StrategyMemoryInlineMetric
            label="候选 Skill"
            value={String(readinessData?.candidate_count ?? 0)}
          />
          <StrategyMemoryInlineMetric
            label="usage 样本"
            value={String(readinessData?.usage_count ?? 0)}
          />
          <StrategyMemoryInlineMetric
            label="reward 样本"
            value={String(readinessData?.rewarded_usage_count ?? 0)}
          />
        </div>
      )}

      {readinessData && (
        <SkillRewardContextReadinessList
          contexts={contexts}
          busyKey={busyKey}
          onSkillRewardRollout={onSkillRewardRollout}
        />
      )}
    </section>
  );
}

function SkillRewardContextReadinessList({
  contexts,
  busyKey,
  onSkillRewardRollout,
}: {
  contexts: SkillRewardReadiness["contexts"];
  busyKey: string | null;
  onSkillRewardRollout: (
    contextKey: string,
    mode: SkillRewardRolloutMode,
  ) => void;
}) {
  const visibleContexts = [...contexts]
    .sort(compareSkillRewardContextReadiness)
    .slice(0, 8);
  return (
    <section className="mt-3 rounded-md border bg-background/40 px-3 py-2">
      <div className="text-xs font-semibold text-foreground">
        Context 级灰度候选
      </div>
      <p className="mt-0.5 text-[11px] text-muted-foreground">
        按 role / level / dimension / probe_intent 聚合；同一 context 会累加样本，默认优先展示已开启、可灰度或排序变化的 context。单轮实际命中仍以 Trace Explorer 的 ask_question / SKILLS 命中为准。
      </p>
      <div className="mt-2 space-y-2">
        {visibleContexts.length === 0 ? (
          <p className="text-[11px] text-muted-foreground">
            暂无带 skill_context_key 的 usage；新跑面试后会出现 context 级诊断。
          </p>
        ) : (
          visibleContexts.map((context) => (
            <SkillRewardReadinessRow
              key={context.skill_context_key}
              context={context}
              busyKey={busyKey}
              onSkillRewardRollout={onSkillRewardRollout}
            />
          ))
        )}
      </div>
      {contexts.length > visibleContexts.length && (
        <p className="mt-2 text-[11px] text-muted-foreground">
          已按灰度价值展示前 {visibleContexts.length} / {contexts.length} 个 context；低样本上下文后续可接筛选或分页。
        </p>
      )}
    </section>
  );
}

function compareSkillRewardContextReadiness(
  a: SkillRewardReadiness["contexts"][number],
  b: SkillRewardReadiness["contexts"][number],
): number {
  return (
    skillRewardContextPriority(b) - skillRewardContextPriority(a) ||
    (b.rewarded_usage_count ?? 0) - (a.rewarded_usage_count ?? 0) ||
    (b.usage_count ?? 0) - (a.usage_count ?? 0) ||
    String(a.skill_context_key).localeCompare(String(b.skill_context_key))
  );
}

function skillRewardContextPriority(
  context: SkillRewardReadiness["contexts"][number],
): number {
  let score = 0;
  if (context.rollout?.mode === "reward") score += 100;
  if (context.readiness === "ready") score += 40;
  if (context.rank_changed) score += 20;
  if ((context.rewarded_usage_count ?? 0) > 0) score += 5;
  return score;
}

function SkillRewardReadinessRow({
  context,
  busyKey,
  onSkillRewardRollout,
}: {
  context: SkillRewardReadiness["contexts"][number];
  busyKey: string | null;
  onSkillRewardRollout: (
    contextKey: string,
    mode: SkillRewardRolloutMode,
  ) => void;
}) {
  const rolloutMode = context.rollout?.mode ?? "reward_shadow";
  const rolloutBusy =
    busyKey === `skill-rollout:${context.skill_context_key}:reward` ||
    busyKey === `skill-rollout:${context.skill_context_key}:reward_shadow`;
  return (
    <div className="rounded-md border bg-card/30 p-2 text-[11px]">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-1.5">
            <Badge
              variant="outline"
              className={cn("text-[10px]", skillRewardReadinessTone(context.readiness))}
            >
              {formatSkillRewardReadiness(context.readiness)}
            </Badge>
            <Badge
              variant="outline"
              className={cn("font-mono text-[10px]", skillRewardRolloutTone(rolloutMode))}
            >
              {formatSkillRewardRolloutMode(rolloutMode)}
            </Badge>
            <span className="min-w-0 break-all font-mono text-muted-foreground">
              {context.skill_context_key}
            </span>
          </div>
          {context.rollout?.reason && (
            <p className="mt-1 text-[11px] text-muted-foreground">
              灰度说明：{context.rollout.reason}
            </p>
          )}
        </div>
        {rolloutMode === "reward" ? (
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={rolloutBusy}
            onClick={() =>
              onSkillRewardRollout(context.skill_context_key, "reward_shadow")
            }
            className="h-7 shrink-0 text-[11px]"
          >
            {rolloutBusy ? "处理中" : "回退 shadow"}
          </Button>
        ) : (
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={rolloutBusy}
            onClick={() => onSkillRewardRollout(context.skill_context_key, "reward")}
            className="h-7 shrink-0 border-emerald-500/40 text-[11px] text-emerald-600 hover:bg-emerald-500/10"
          >
            {rolloutBusy ? "处理中" : "开启 reward"}
          </Button>
        )}
      </div>
      <div className="mt-1 flex flex-wrap gap-3 text-muted-foreground">
        <span>候选 {context.candidate_count ?? 0}</span>
        <span>usage {context.usage_count ?? 0}</span>
        <span>reward {context.rewarded_usage_count ?? 0}</span>
      </div>
      <div className="mt-2 grid gap-2 md:grid-cols-2">
        <QuestionRewardTopKList
          label="匹配规则 Top K"
          description="按 Skill 卡片的 priority、role/job_level/dimension/probe_intent 匹配分排序。"
          suffix=""
          values={context.metadata_top_skill_ids}
        />
        <QuestionRewardTopKList
          label="reward 模拟 Top K"
          description="在匹配规则基础上叠加历史 reward、样本置信度、使用次数和否决惩罚。"
          suffix=""
          values={context.reward_top_skill_ids}
        />
      </div>
      {context.reasons.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {context.reasons.map((reason) => (
            <Badge key={reason} variant="outline" className="text-[10px]">
              {formatSkillRewardReason(reason)} · {reason}
            </Badge>
          ))}
        </div>
      )}
    </div>
  );
}

function SkillRewardShadowDiagnosticsPanel({
  stats,
  statsPage,
  onStatsPageChange,
  readiness,
  onRefresh,
}: {
  stats: Loadable<SkillUsageStatsResponse>;
  statsPage: number;
  onStatsPageChange: (page: number) => void;
  readiness: Loadable<SkillRewardReadiness>;
  onRefresh: () => void;
}) {
  const { toast } = useToast();
  const [busy, setBusy] = useState(false);
  const readinessData = readiness.phase === "ready" ? readiness.data : null;
  const statRows = stats.phase === "ready" ? stats.data.stats : [];

  async function handleRefreshSkillStats() {
    if (busy) return;
    setBusy(true);
    try {
      const result = await refreshSkillUsageStats();
      toast({
        title: "Skill reward shadow 已刷新",
        description: `refreshed=${result.refreshed}, deleted=${result.deleted}`,
      });
      onStatsPageChange(0);
      onRefresh();
    } catch (err) {
      toast({
        title: "Skill reward shadow 刷新失败",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="rounded-lg border bg-card/35 p-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-[11px] font-medium text-muted-foreground">
            Skill Shadow 模拟诊断
          </p>
          <h3 className="text-sm font-semibold text-foreground">
            Skill Reward 排序模拟
          </h3>
          <p className="mt-1 text-xs text-muted-foreground">
            基于历史 SkillUsage 中出现过、当前仍启用的 Skill 卡片做治理模拟；默认 reward_shadow 不改变 retrieve_skills() 的真实返回顺序。
          </p>
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={handleRefreshSkillStats}
          disabled={busy}
        >
          {busy && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
          刷新 stats
        </Button>
      </div>

      {(stats.phase === "loading" || readiness.phase === "loading") && (
        <div className="mt-3">
          <LoadingList rows={2} />
        </div>
      )}
      {stats.phase === "error" && (
        <ErrorBox message={`skill usage stats: ${stats.message}`} />
      )}
      {readiness.phase === "error" && (
        <ErrorBox message={`skill reward readiness: ${readiness.message}`} />
      )}

      {readinessData && (
        <div className="mt-3 rounded-md border bg-background/40 p-2 text-[11px]">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <Badge variant="outline" className="font-mono text-[10px]">
              reward_ranking_mode: {readinessData.reward_ranking_mode ?? "reward_shadow"}
            </Badge>
            <Badge
              variant={readinessData.summary.shadow_changed_contexts > 0 ? "warn" : "outline"}
              className="text-[10px]"
            >
              {readinessData.summary.shadow_changed_contexts > 0
                ? "模拟 reward 后 Top K 会变化"
                : "模拟 reward 后 Top K 不变"}
            </Badge>
          </div>
          <details className="mt-2 rounded-md border border-dashed bg-background/40 p-2">
            <summary className="cursor-pointer text-muted-foreground">
              展开 Skill Shadow 模拟诊断
            </summary>
            <div className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
              <StrategyMemoryInlineMetric
                label="低样本 context"
                value={String(readinessData.summary.low_sample_contexts)}
              />
              <StrategyMemoryInlineMetric
                label="Shadow 改变 context"
                value={String(readinessData.summary.shadow_changed_contexts)}
              />
              <StrategyMemoryInlineMetric
                label="高 reward 低样本"
                value={String(readinessData.summary.high_reward_low_sample_skills)}
              />
              <StrategyMemoryInlineMetric
                label="已统计 Skill"
                value={String(readinessData.summary.skills_with_stats)}
              />
            </div>
          </details>
        </div>
      )}

      {stats.phase === "ready" && statRows.length > 0 && (
        <SkillUsageStatsList
          rows={statRows}
          count={stats.data.count}
          limit={stats.data.limit ?? SKILL_USAGE_STATS_PAGE_SIZE}
          offset={stats.data.offset ?? statsPage * SKILL_USAGE_STATS_PAGE_SIZE}
          onPageChange={onStatsPageChange}
        />
      )}
    </section>
  );
}

type SkillUsageStatsRow = SkillUsageStatsResponse["stats"][number];

function SkillUsageStatsList({
  rows,
  count,
  limit,
  offset,
  onPageChange,
}: {
  rows: SkillUsageStatsRow[];
  count: number;
  limit: number;
  offset: number;
  onPageChange: (page: number) => void;
}) {
  const currentPageIndex = Math.floor(offset / Math.max(1, limit));
  const currentPage = currentPageIndex + 1;
  const totalPages = Math.max(1, Math.ceil(count / Math.max(1, limit)));
  const hasPrevious = currentPageIndex > 0;
  const hasNext = offset + rows.length < count;
  return (
    <details className="mt-3 rounded-md border border-dashed bg-muted/10 px-3 py-2">
      <summary className="cursor-pointer text-xs font-medium text-muted-foreground">
        skill_usage_stats
      </summary>
      <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
        <p className="text-[11px] font-medium text-foreground">
          第 {currentPage} / {totalPages} 页 · 已加载 {rows.length} / 共 {count} 条
        </p>
        <div className="flex items-center gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={!hasPrevious}
            onClick={() => onPageChange(Math.max(0, currentPageIndex - 1))}
            className="h-7 text-[11px]"
          >
            上一页
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={!hasNext}
            onClick={() => onPageChange(currentPageIndex + 1)}
            className="h-7 text-[11px]"
          >
            下一页
          </Button>
        </div>
      </div>
      <ul className="mt-2 space-y-2">
        {rows.map((row) => (
          <li key={row.id} className="rounded-md border bg-background/40 p-2 text-[11px]">
            <div className="grid gap-1.5 sm:grid-cols-2">
              <StrategyMemoryFact label="skill_context_key" value={row.skill_context_key} mono />
              <StrategyMemoryFact label="skill_id" value={row.skill_id} mono />
            </div>
            <div className="mt-2 grid gap-1.5 sm:grid-cols-2 lg:grid-cols-4">
              <QuestionUsageStatsMetric label="uses" value={String(row.uses)} />
              <QuestionUsageStatsMetric
                label="injected / rewarded"
                value={`${row.injected_uses} / ${row.rewarded_uses}`}
              />
              <QuestionUsageStatsMetric
                label="avg_score / pass_rate"
                value={`${formatMaybeNumber(row.avg_score)} / ${
                  row.pass_rate == null ? "—" : formatPercent(row.pass_rate)
                }`}
              />
              <QuestionUsageStatsMetric
                label="reward / last_used_at"
                value={`${formatMaybeNumber(row.avg_blended_reward)} / ${
                  row.last_used_at ? formatDateTime(row.last_used_at) : "—"
                }`}
              />
            </div>
          </li>
        ))}
      </ul>
    </details>
  );
}

function SkillsPlaybookCard({
  state,
  usageStats,
  usageStatsPage,
  onUsageStatsPageChange,
  rewardReadiness,
  onRefresh,
}: {
  state: Loadable<SkillPlaybooks>;
  usageStats: Loadable<SkillUsageStatsResponse>;
  usageStatsPage: number;
  onUsageStatsPageChange: (page: number) => void;
  rewardReadiness: Loadable<SkillRewardReadiness>;
  onRefresh: () => void;
}) {
  const { toast } = useToast();
  const [selectedCardId, setSelectedCardId] = useState<string | null>(null);
  const [detail, setDetail] = useState<Loadable<SkillPlaybookDetail> | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [playbookSearch, setPlaybookSearch] = useState("");
  const [playbookStatus, setPlaybookStatus] = useState("active");
  const [playbookDirection, setPlaybookDirection] = useState("all");
  const [playbookRole, setPlaybookRole] = useState("all");
  const [playbookDimension, setPlaybookDimension] = useState("all");
  const playbookRows = useMemo(
    () => (state.phase === "ready" ? state.data.skill_playbooks : []),
    [state],
  );
  const playbookStatusCounts = useMemo(
    () =>
      playbookRows.reduce<Record<string, number>>((acc, card) => {
        const status = card.status || "unknown";
        acc[status] = (acc[status] ?? 0) + 1;
        return acc;
      }, {}),
    [playbookRows],
  );
  const playbookStatuses = useMemo(
    () =>
      Array.from(
        new Set(playbookRows.map((card) => card.status || "unknown")),
      ).sort(),
    [playbookRows],
  );
  const playbookDirections = useMemo(
    () => collectSkillPlaybookValues(playbookRows, (card) => card.direction_tags),
    [playbookRows],
  );
  const playbookRoles = useMemo(
    () => collectSkillPlaybookValues(playbookRows, (card) => card.role_tags),
    [playbookRows],
  );
  const playbookDimensions = useMemo(
    () => collectSkillPlaybookValues(playbookRows, (card) => card.dimensions),
    [playbookRows],
  );
  const filteredSkillPlaybooks = useMemo(() => {
    const q = playbookSearch.trim().toLowerCase();
    return playbookRows
      .filter((card) => {
        const matchesSearch = matchesSkillPlaybookSearch(card, q);
        const matchesStatus =
          playbookStatus === "all" || (card.status || "unknown") === playbookStatus;
        const matchesDirection =
          playbookDirection === "all" || card.direction_tags.includes(playbookDirection);
        const matchesRole =
          playbookRole === "all" || card.role_tags.includes(playbookRole);
        const matchesDimension =
          playbookDimension === "all" || card.dimensions.includes(playbookDimension);
        return (
          matchesSearch &&
          matchesStatus &&
          matchesDirection &&
          matchesRole &&
          matchesDimension
        );
      })
      .sort(compareSkillPlaybookRows);
  }, [
    playbookDimension,
    playbookDirection,
    playbookRows,
    playbookRole,
    playbookSearch,
    playbookStatus,
  ]);

  useEffect(() => {
    if (state.phase !== "ready") return;
    const selectedStillVisible = filteredSkillPlaybooks.some(
      (card) => card.id === selectedCardId,
    );
    if (selectedCardId && selectedStillVisible) return;
    setSelectedCardId(filteredSkillPlaybooks[0]?.id ?? null);
  }, [filteredSkillPlaybooks, selectedCardId, state.phase]);

  useEffect(() => {
    if (!selectedCardId) {
      setDetail(null);
      return;
    }
    const ctrl = new AbortController();
    setDetail({ phase: "loading" });
    getSkillPlaybook(selectedCardId, ctrl.signal)
      .then((data) => {
        if (!ctrl.signal.aborted) setDetail({ phase: "ready", data });
      })
      .catch((err) => {
        if (!ctrl.signal.aborted) {
          setDetail({
            phase: "error",
            message: err instanceof Error ? err.message : String(err),
          });
        }
      });
    return () => ctrl.abort();
  }, [selectedCardId]);

  async function handleSkillRewardRollout(
    contextKey: string,
    mode: SkillRewardRolloutMode,
  ) {
    if (busy) return;
    const busyKey = `skill-rollout:${contextKey}:${mode}`;
    setBusy(busyKey);
    try {
      await setSkillRewardRollout(contextKey, {
        mode,
        reason:
          mode === "reward"
            ? "admin skill reward ranking pilot"
            : "admin fallback to reward shadow",
      });
      toast({
        title: "Skill reward 排序灰度已更新",
        description: `${contextKey} -> ${mode}`,
      });
      onRefresh();
    } catch (err) {
      toast({
        title: "Skill reward 排序灰度更新失败",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    } finally {
      setBusy(null);
    }
  }

  async function handleImport(archiveMissing: boolean) {
    if (busy) return;
    setBusy(archiveMissing ? "import-archive" : "import");
    try {
      const result = await importSkillPlaybooks(archiveMissing);
      toast({
        title: "技能打法库已导入",
        description: `新增 ${result.imported}，更新 ${result.updated}，未变更 ${result.unchanged}，归档 ${result.archived}，跳过 ${result.skipped}`,
      });
      onRefresh();
    } catch (err) {
      toast({
        title: "技能打法库导入失败",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    } finally {
      setBusy(null);
    }
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <BookMarked className="h-4 w-4 text-cyan-400" />
              技能打法库
            </CardTitle>
            <CardDescription className="mt-1">
              Markdown 导入的出题指导资产；运行时由出题链路按角色、方向和能力维度匹配，完整使用链路请看 Trace。
            </CardDescription>
          </div>
          <div className="flex flex-wrap justify-end gap-2">
            {state.phase === "ready" && (
              <>
                <Badge variant="outline" className="font-mono text-[10px]">
                  {state.data.count} 张卡
                </Badge>
                <Badge variant="secondary" className="font-mono text-[10px]">
                  {state.data.active_count} 启用
                </Badge>
                <Badge variant="outline" className="font-mono text-[10px]">
                  后端 {formatSkillPlaybookBackend(state.data.runtime_backend)}
                </Badge>
              </>
            )}
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border bg-secondary/20 p-3">
          <div>
            <p className="text-sm font-medium">Markdown 导入</p>
            <p className="text-xs text-muted-foreground">
              Markdown 文件仍是权威来源；面板负责触发导入和查看数据库中的卡片。
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => handleImport(false)}
              disabled={busy !== null}
            >
              {busy === "import" && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              导入
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => handleImport(true)}
              disabled={busy !== null}
            >
              {busy === "import-archive" && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              导入并归档缺失
            </Button>
          </div>
        </div>

        <SkillRewardRolloutPanel
          readiness={rewardReadiness}
          busyKey={busy}
          onSkillRewardRollout={handleSkillRewardRollout}
        />

        <SkillRewardShadowDiagnosticsPanel
          stats={usageStats}
          statsPage={usageStatsPage}
          onStatsPageChange={onUsageStatsPageChange}
          readiness={rewardReadiness}
          onRefresh={onRefresh}
        />

        {state.phase === "loading" && <LoadingList rows={3} />}
        {state.phase === "error" && <ErrorBox message={state.message} />}
        {state.phase === "ready" && (
          <div className="space-y-3">
            <SkillPlaybookFilters
              search={playbookSearch}
              onSearchChange={setPlaybookSearch}
              status={playbookStatus}
              onStatusChange={setPlaybookStatus}
              statuses={playbookStatuses}
              statusCounts={playbookStatusCounts}
              direction={playbookDirection}
              onDirectionChange={setPlaybookDirection}
              directions={playbookDirections}
              role={playbookRole}
              onRoleChange={setPlaybookRole}
              roles={playbookRoles}
              dimension={playbookDimension}
              onDimensionChange={setPlaybookDimension}
              dimensions={playbookDimensions}
              shown={filteredSkillPlaybooks.length}
              total={playbookRows.length}
            />

            {playbookRows.length === 0 ? (
              <p className="text-xs text-muted-foreground">
                数据库中暂无技能打法卡。导入 Markdown 后会出现在这里。
              </p>
            ) : (
              <div className="grid min-w-0 gap-3 lg:grid-cols-[minmax(280px,0.82fr)_minmax(0,1.35fr)]">
                <div className="min-w-0 rounded-lg border bg-card/40 p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div>
                      <p className="text-xs font-medium text-foreground">打法目录</p>
                      <p className="mt-0.5 text-[11px] text-muted-foreground">
                        轻量浏览资产卡，完整内容在右侧查看。
                      </p>
                    </div>
                    <Badge variant="outline" className="font-mono text-[10px]">
                      {filteredSkillPlaybooks.length}/{playbookRows.length}
                    </Badge>
                  </div>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {Object.entries(playbookStatusCounts).map(([status, count]) => (
                      <Badge
                        key={status}
                        variant={skillPlaybookStatusBadgeVariant(status)}
                        className="font-mono text-[10px]"
                      >
                        {formatSkillPlaybookStatus(status)} {count}
                      </Badge>
                    ))}
                  </div>
                  {filteredSkillPlaybooks.length === 0 ? (
                    <p className="mt-4 text-xs text-muted-foreground">
                      没有匹配的打法卡。放宽筛选条件再看。
                    </p>
                  ) : (
                    <ul className="mt-3 max-h-[1040px] min-w-0 space-y-2 overflow-y-auto pr-1">
                      {filteredSkillPlaybooks.map((card) => (
                        <li key={card.id}>
                          <button
                            type="button"
                            className={cn(
                              "w-full overflow-hidden rounded-md border px-3 py-2.5 text-left text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                              selectedCardId === card.id
                                ? "border-primary/60 bg-primary/10"
                                : "border-border/70 bg-background/40 hover:bg-muted/30",
                            )}
                            onClick={() => setSelectedCardId(card.id)}
                          >
                            <div className="flex items-start justify-between gap-2">
                              <span className="min-w-0 truncate font-medium">
                                {skillPlaybookDisplayName(card)}
                              </span>
                              <Badge
                                variant={skillPlaybookStatusBadgeVariant(card.status)}
                                className="shrink-0 font-mono text-[10px]"
                              >
                                {formatSkillPlaybookStatus(card.status)}
                              </Badge>
                            </div>
                            <p className="mt-1 line-clamp-1 text-xs text-muted-foreground">
                              {skillPlaybookDisplayDescription(card) || "暂无描述"}
                            </p>
                            <div className="mt-2 flex min-w-0 flex-nowrap gap-1.5 overflow-hidden">
                              <Badge variant="secondary" className="shrink-0 font-mono text-[10px]">
                                p{card.priority}
                              </Badge>
                              <SkillPlaybookTagPreview values={card.role_tags} max={2} />
                              <SkillPlaybookTagPreview
                                values={card.dimensions}
                                max={2}
                                variant="secondary"
                              />
                            </div>
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>

                <div className="min-w-0 rounded-lg border bg-card/40 p-4">
                  {detail?.phase === "loading" && <LoadingList rows={4} />}
                  {detail?.phase === "error" && <ErrorBox message={detail.message} />}
                  {detail?.phase === "ready" && (
                    <SkillPlaybookDetailView card={detail.data.skill_playbook} />
                  )}
                  {!detail && (
                    <p className="text-xs text-muted-foreground">
                      选择一张打法卡查看适用范围、出题指导、评分观察和开发详情。
                    </p>
                  )}
                </div>
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function SkillPlaybookFilters({
  search,
  onSearchChange,
  status,
  onStatusChange,
  statuses,
  statusCounts,
  direction,
  onDirectionChange,
  directions,
  role,
  onRoleChange,
  roles,
  dimension,
  onDimensionChange,
  dimensions,
  shown,
  total,
}: {
  search: string;
  onSearchChange: (value: string) => void;
  status: string;
  onStatusChange: (value: string) => void;
  statuses: string[];
  statusCounts: Record<string, number>;
  direction: string;
  onDirectionChange: (value: string) => void;
  directions: string[];
  role: string;
  onRoleChange: (value: string) => void;
  roles: string[];
  dimension: string;
  onDimensionChange: (value: string) => void;
  dimensions: string[];
  shown: number;
  total: number;
}) {
  const statusOptions = Array.from(new Set(["active", ...statuses]));
  return (
    <div className="rounded-md border bg-muted/10 p-3">
      <div className="flex flex-col gap-2 xl:flex-row xl:items-center xl:justify-between">
        <div>
          <p className="text-xs font-medium text-foreground">打法筛选</p>
          <p className="mt-0.5 text-[11px] text-muted-foreground">
            当前显示 {shown}/{total} 张打法卡，默认只看启用资产。
          </p>
        </div>
        <div className="grid gap-2 sm:grid-cols-2 xl:min-w-[860px] xl:grid-cols-5">
          <Input
            name="skill-playbook-search"
            autoComplete="off"
            aria-label="搜索技能打法卡"
            placeholder="搜索名称、ID、标签…"
            value={search}
            onChange={(event) => onSearchChange(event.target.value)}
            className="h-8 text-xs"
          />
          <select
            name="skill-playbook-status"
            aria-label="按状态筛选技能打法卡"
            value={status}
            onChange={(event) => onStatusChange(event.target.value)}
            className="h-8 rounded-md border bg-background px-2 text-xs text-foreground"
          >
            <option value="all">全部状态 ({total})</option>
            {statusOptions.map((item) => (
              <option key={item} value={item}>
                {formatSkillPlaybookStatus(item)} ({statusCounts[item] ?? 0})
              </option>
            ))}
          </select>
          <select
            name="skill-playbook-direction"
            aria-label="按方向筛选技能打法卡"
            value={direction}
            onChange={(event) => onDirectionChange(event.target.value)}
            className="h-8 rounded-md border bg-background px-2 text-xs text-foreground"
          >
            <option value="all">全部方向</option>
            {directions.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
          <select
            name="skill-playbook-role"
            aria-label="按角色筛选技能打法卡"
            value={role}
            onChange={(event) => onRoleChange(event.target.value)}
            className="h-8 rounded-md border bg-background px-2 text-xs text-foreground"
          >
            <option value="all">全部角色</option>
            {roles.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
          <select
            name="skill-playbook-dimension"
            aria-label="按能力维度筛选技能打法卡"
            value={dimension}
            onChange={(event) => onDimensionChange(event.target.value)}
            className="h-8 rounded-md border bg-background px-2 text-xs text-foreground"
          >
            <option value="all">全部维度</option>
            {dimensions.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
        </div>
      </div>
    </div>
  );
}

function SkillPlaybookDetailView({ card }: { card: SkillPlaybookRow }) {
  const displayName = skillPlaybookDisplayName(card);
  const displayDescription = skillPlaybookDisplayDescription(card);
  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="min-w-0">
            <p className="text-base font-semibold leading-tight">{displayName}</p>
            {card.name && (
              <p className="mt-0.5 break-all font-mono text-[11px] text-muted-foreground">
                name:{card.name}
              </p>
            )}
            <p className="mt-1 break-all font-mono text-[11px] text-muted-foreground">
              {card.id}
            </p>
          </div>
          <div className="flex shrink-0 flex-wrap justify-end gap-1.5">
            <Badge
              variant={skillPlaybookStatusBadgeVariant(card.status)}
              className="font-mono text-[10px]"
            >
              {formatSkillPlaybookStatus(card.status)}
            </Badge>
            <Badge variant="secondary" className="font-mono text-[10px]">
              p{card.priority}
            </Badge>
          </div>
        </div>
        {displayDescription && (
          <p className="text-sm leading-relaxed text-muted-foreground">
            {displayDescription}
          </p>
        )}
      </div>

      <SkillPlaybookDetailSection heading="适用范围">
        <div className="grid gap-3 md:grid-cols-2">
          <SkillPlaybookTagGroup label="方向" values={card.direction_tags} />
          <SkillPlaybookTagGroup label="角色" values={card.role_tags} />
          <SkillPlaybookTagGroup label="能力维度" values={card.dimensions} />
          <SkillPlaybookTagGroup label="级别" values={card.job_levels} />
          <SkillPlaybookTagGroup label="追问意图" values={card.probe_intents} />
          <SkillPlaybookTagGroup label="失败类别" values={card.failure_categories} />
        </div>
      </SkillPlaybookDetailSection>

      <SkillPlaybookDetailSection heading="出题指导">
        <div className="space-y-3">
          <PlaybookFieldList label="生成动作" items={card.generator_moves} />
          <PlaybookFieldList label="追问观察" items={card.watch_for} />
          <PlaybookFieldList label="避免事项" items={card.avoid} />
        </div>
      </SkillPlaybookDetailSection>

      <SkillPlaybookDetailSection heading="评分观察">
        <div className="mb-3 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <span>这些字段用于观察和治理，是否进入评分运行时由卡片配置决定。</span>
          <Badge variant="outline" className="font-mono text-[10px]">
            {card.evaluator_visibility ? "评分器可见" : "仅治理观察"}
          </Badge>
        </div>
        <div className="space-y-3">
          <PlaybookFieldList label="评分提示" items={card.evaluator_rubric_hints} />
          <PlaybookFieldList label="正向信号" items={card.positive_signals} />
          <PlaybookFieldList label="负向信号" items={card.negative_signals} />
          <PlaybookFieldList label="分数偏置规则" items={card.score_bias_rules} />
        </div>
      </SkillPlaybookDetailSection>

      <details className="rounded-md border border-dashed bg-muted/10 p-3 text-xs">
        <summary className="cursor-pointer font-medium text-muted-foreground">
          开发详情
        </summary>
        <div className="mt-3 grid gap-2 sm:grid-cols-2">
          <SkillPlaybookMetaItem label="来源" value={card.source ?? "未知"} />
          <SkillPlaybookMetaItem label="版本" value={`v${card.version ?? 1}`} />
          <SkillPlaybookMetaItem
            label="内容 hash"
            value={card.content_hash ? truncate(card.content_hash) : "未记录"}
          />
          <SkillPlaybookMetaItem
            label="更新时间"
            value={formatDateTime(card.updated_at || card.created_at || "")}
          />
        </div>
        <details className="mt-3">
          <summary className="cursor-pointer text-muted-foreground">
            正文补充
          </summary>
          <p className="mt-2 text-[11px] text-muted-foreground">
            frontmatter 是运行时读取的主体；这里仅展示 frontmatter 之外的 Markdown 正文。
          </p>
          <pre className="mt-2 max-h-96 overflow-auto whitespace-pre-wrap rounded-md bg-background/70 p-3 text-xs leading-relaxed text-foreground/85">
            {card.body_markdown || ""}
          </pre>
        </details>
      </details>
    </div>
  );
}

function SkillPlaybookDetailSection({
  heading,
  children,
}: {
  heading: string;
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-3 border-t border-border/60 pt-4 first:border-t-0 first:pt-0">
      <p className="text-sm font-semibold">{heading}</p>
      {children}
    </section>
  );
}

function PlaybookFieldList({
  label,
  items,
}: {
  label: string;
  items: string[] | undefined;
}) {
  const values = items ?? [];
  return (
    <div className="rounded-md bg-background/50 p-3">
      <p className="text-xs font-medium">{label}</p>
      {values.length === 0 ? (
        <p className="mt-2 text-[11px] text-muted-foreground">暂无配置</p>
      ) : (
        <ul className="mt-2 space-y-1.5 text-xs leading-relaxed text-muted-foreground">
          {values.map((item, index) => (
            <li key={`${index}:${item}`}>- {item}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function SkillPlaybookTagGroup({
  label,
  values,
}: {
  label: string;
  values: string[] | undefined;
}) {
  const items = values ?? [];
  return (
    <div>
      <p className="text-[11px] text-muted-foreground">{label}</p>
      {items.length === 0 ? (
        <p className="mt-1 text-xs text-muted-foreground">未配置</p>
      ) : (
        <div className="mt-1 flex flex-wrap gap-1.5">
          {items.map((item) => (
            <Badge key={item} variant="outline" className="font-mono text-[10px]">
              {item}
            </Badge>
          ))}
        </div>
      )}
    </div>
  );
}

function SkillPlaybookTagPreview({
  values,
  max,
  variant = "outline",
}: {
  values: string[] | undefined;
  max: number;
  variant?: React.ComponentProps<typeof Badge>["variant"];
}) {
  const items = values ?? [];
  if (items.length === 0) return null;
  const visible = items.slice(0, max);
  return (
    <>
      {visible.map((item) => (
        <Badge
          key={item}
          variant={variant}
          className="max-w-[9rem] shrink-0 truncate font-mono text-[10px]"
        >
          {item}
        </Badge>
      ))}
      {items.length > max && (
        <Badge variant="outline" className="shrink-0 font-mono text-[10px]">
          +{items.length - max}
        </Badge>
      )}
    </>
  );
}

function SkillPlaybookMetaItem({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div className="rounded-md bg-background/50 px-3 py-2">
      <p className="text-[10px] text-muted-foreground">{label}</p>
      <p className="mt-1 break-words font-mono text-[11px] text-foreground">{value}</p>
    </div>
  );
}

function collectSkillPlaybookValues(
  rows: SkillPlaybookRow[],
  select: (row: SkillPlaybookRow) => string[] | undefined,
): string[] {
  return Array.from(
    new Set(rows.flatMap((row) => select(row) ?? []).filter(Boolean)),
  ).sort();
}

function skillPlaybookDisplayName(card: SkillPlaybookRow): string {
  return card.display_name_zh?.trim() || card.name || card.id;
}

function skillPlaybookDisplayDescription(card: SkillPlaybookRow): string {
  return card.display_description_zh?.trim() || card.description || "";
}

function matchesSkillPlaybookSearch(card: SkillPlaybookRow, q: string): boolean {
  if (!q) return true;
  const haystack = [
    card.id,
    card.name,
    card.description ?? "",
    card.display_name_zh ?? "",
    card.display_description_zh ?? "",
    card.source ?? "",
    ...card.direction_tags,
    ...card.role_tags,
    ...card.dimensions,
    ...card.job_levels,
    ...card.probe_intents,
    ...card.failure_categories,
  ]
    .join(" ")
    .toLowerCase();
  return haystack.includes(q);
}

function compareSkillPlaybookRows(
  a: SkillPlaybookRow,
  b: SkillPlaybookRow,
): number {
  return (
    skillPlaybookStatusRank(a.status) - skillPlaybookStatusRank(b.status) ||
    (b.priority ?? 0) - (a.priority ?? 0) ||
    a.name.localeCompare(b.name) ||
    a.id.localeCompare(b.id)
  );
}

function skillPlaybookStatusRank(status?: string | null): number {
  if (status === "active") return 0;
  if (status === "disabled") return 1;
  if (status === "archived") return 2;
  return 3;
}

function formatSkillPlaybookStatus(status?: string | null): string {
  if (status === "active") return "启用";
  if (status === "disabled") return "禁用";
  if (status === "archived") return "归档";
  return status || "未知";
}

function skillPlaybookStatusBadgeVariant(
  status?: string | null,
): React.ComponentProps<typeof Badge>["variant"] {
  if (status === "active") return "secondary";
  if (status === "disabled") return "warn";
  if (status === "archived") return "outline";
  return "outline";
}

function formatSkillPlaybookBackend(value?: string | null): string {
  if (value === "db_with_file_fallback") return "DB 优先，文件兜底";
  if (value === "db") return "DB";
  if (value === "file") return "文件";
  return value || "未知";
}

type StrategyMemoryRow = Strategies["strategies"][number];

function strategyDisplayName(strategy: StrategyMemoryRow): string {
  return strategy.display_name_zh?.trim() || strategy.name || strategy.path;
}

function strategyDisplayDescription(strategy: StrategyMemoryRow): string {
  return strategy.display_description_zh?.trim() || strategy.description || "";
}

function shouldShowStrategyBackendName(strategy: StrategyMemoryRow): boolean {
  const displayName = strategy.display_name_zh?.trim();
  return Boolean(displayName && strategy.name && displayName !== strategy.name);
}

function isPromotedStrategyMemory(strategy: StrategyMemoryRow): boolean {
  return strategy.source === "promoted_signal";
}

function strategyOriginBadgeVariant(
  strategy: StrategyMemoryRow,
): React.ComponentProps<typeof Badge>["variant"] {
  return isPromotedStrategyMemory(strategy) ? "warn" : "secondary";
}

function strategyOriginLabel(strategy: StrategyMemoryRow): string {
  if (isPromotedStrategyMemory(strategy)) return "来源：自动晋升";
  return `来源：${formatStrategySource(strategy.source)}`;
}

function strategyPromotionStageTone(stage?: string | null): string {
  if (stage === "stable" || stage === "stabilized") {
    return "border-emerald-500/50 text-emerald-600";
  }
  if (stage === "low_confidence") {
    return "border-amber-500/50 text-amber-600";
  }
  return "";
}

function strategyPromotionStageLabel(stage?: string | null): string {
  if (stage === "low_confidence") return "阶段：低置信晋升";
  if (stage === "stable" || stage === "stabilized") return "阶段：稳定策略";
  return `阶段：${formatPromotionStage(stage)}`;
}

const StrategiesCard = React.memo(function StrategiesCard({
  state,
  signals,
  usages,
  stats,
  rewardReadiness,
  onRefresh,
}: {
  state: Loadable<Strategies>;
  signals: Loadable<StrategySignals>;
  usages: Loadable<StrategyUsages>;
  stats: Loadable<StrategyStats>;
  rewardReadiness: Loadable<StrategyRewardReadiness>;
  onRefresh: () => void;
}) {
  const { toast } = useToast();
  const [busy, setBusy] = useState<string | null>(null);

  async function handleStatusAction(
    strategyId: string | null | undefined,
    action: "disable" | "archive",
  ) {
    if (!strategyId || busy) return;
    setBusy(`${action}:${strategyId}`);
    try {
      if (action === "disable") {
        await disableStrategy(strategyId);
      } else {
        await archiveStrategy(strategyId);
      }
      toast({ title: action === "disable" ? "策略已禁用" : "策略已归档" });
      onRefresh();
    } catch (err) {
      toast({
        title: "策略操作失败",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    } finally {
      setBusy(null);
    }
  }

  async function handlePromotionRun() {
    if (busy) return;
    setBusy("promotion");
    try {
      const result = await runStrategyPromotion();
      toast({
        title: "策略晋升已执行",
        description: `晋升 ${result.promoted}，未变 ${result.unchanged}，跳过 ${result.skipped}，禁用 ${result.disabled ?? 0}，稳定 ${result.stabilized ?? 0}`,
      });
      onRefresh();
    } catch (err) {
      toast({
        title: "策略晋升失败",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    } finally {
      setBusy(null);
    }
  }

  async function handleStatsRefresh() {
    if (busy) return;
    setBusy("stats");
    try {
      const result = await refreshStrategyStats();
      toast({
        title: "策略统计已刷新",
        description: `刷新 ${result.refreshed} 条，删除 ${result.deleted} 条过期统计。`,
      });
      onRefresh();
    } catch (err) {
      toast({
        title: "策略统计刷新失败",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    } finally {
      setBusy(null);
    }
  }

  async function handleSeedImport() {
    if (busy) return;
    setBusy("seed-import");
    try {
      const result = await importStrategySeeds();
      toast({
        title: "种子策略已导入",
        description: `导入种子策略后会刷新策略资产和 Reward 排序就绪度。新增 ${result.imported}，更新 ${result.updated}，未变 ${result.unchanged}，跳过 ${result.skipped}。`,
      });
      onRefresh();
    } catch (err) {
      toast({
        title: "种子策略导入失败",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    } finally {
      setBusy(null);
    }
  }

  async function handleRewardRollout(
    contextKey: string,
    mode: StrategyRewardRolloutMode,
  ) {
    if (busy) return;
    const actionLabel = mode === "reward" ? "reward 灰度" : "shadow 回退";
    setBusy(`rollout:${contextKey}:${mode}`);
    try {
      await setStrategyRewardRollout(contextKey, {
        mode,
        reason:
          mode === "reward"
            ? "Admin readiness canary enabled"
            : "Admin rollback to reward_shadow",
      });
      toast({
        title: mode === "reward" ? "已开启 reward 灰度" : "已回退 shadow",
        description: `${contextKey} 已切换到 ${actionLabel}。未通过 gate 时仍会自动 metadata_fallback。`,
      });
      onRefresh();
    } catch (err) {
      toast({
        title: "Reward 灰度操作失败",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    } finally {
      setBusy(null);
    }
  }

  const signalCount = signals.phase === "ready" ? signals.data.count : null;
  const usageCount = usages.phase === "ready" ? usages.data.count : null;
  const statCount = stats.phase === "ready" ? stats.data.count : null;
  const strategies = state.phase === "ready" ? state.data.strategies : [];
  const schedulerStatus: StrategyPromotionSchedulerStatus | null =
    state.phase === "ready" ? state.data.scheduler ?? null : null;
  const activeStrategies = strategies.filter((s) => s.status === "active");
  const usageRows = usages.phase === "ready" ? usages.data.usages : [];
  const recent24hUsageCount =
    usages.phase === "ready"
      ? usages.data.recent_24h_count ?? countRecentStrategyUsages(usageRows)
      : null;
  const signalGroups: StrategySignalGroup[] =
    signals.phase === "ready" ? signals.data.groups ?? [] : [];
  const promotionCandidateGroups = signalGroups.filter(
    (group) => group.promotion_readiness !== "diagnostic_only",
  );
  const statRows = stats.phase === "ready" ? stats.data.stats : [];
  const latestStatsUpdatedAt = latestIso(
    statRows.map((row) => row.updated_at).filter(Boolean),
  );
  const globalStatsByStrategy = new Map(
    statRows
      .filter((row) => row.context_key === "__global__")
      .map((row) => [row.strategy_id, row]),
  );
  const contextStatsByStrategy = statRows
    .filter((row) => row.context_key !== "__global__")
    .reduce<Map<string, typeof statRows>>((acc, row) => {
      const rows = acc.get(row.strategy_id) ?? [];
      rows.push(row);
      acc.set(row.strategy_id, rows);
      return acc;
    }, new Map());

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <BookMarked className="h-4 w-4 text-emerald-400" />
              策略记忆
            </CardTitle>
            <CardDescription className="mt-1">
              全局策略记忆资产、最近策略使用归因和晋升候选分开观测。
            </CardDescription>
          </div>
          <div className="flex flex-wrap justify-end gap-2">
            {state.phase === "ready" && (
              <Badge variant="outline" className="font-mono text-[10px]">
                {state.data.count} 策略
              </Badge>
            )}
            {signalCount !== null && (
              <Badge variant="secondary" className="font-mono text-[10px]">
                {signalCount} 信号
              </Badge>
            )}
            {usageCount !== null && (
              <Badge variant="secondary" className="font-mono text-[10px]">
                {usageCount} 归因
              </Badge>
            )}
            {statCount !== null && (
              <Badge variant="secondary" className="font-mono text-[10px]">
                {statCount} 统计
              </Badge>
            )}
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          <StrategyMemoryStatusTile
            label="启用策略"
            value={
              state.phase === "ready"
                ? `${activeStrategies.length}/${state.data.count}`
                : "—"
            }
            note="全局资产里可被运行时召回的策略。"
          />
          <StrategyMemoryStatusTile
            label="最近 24h 召回"
            value={recent24hUsageCount === null ? "—" : String(recent24hUsageCount)}
            note="策略注入出题链路并完成评分后才会记录。"
          />
          <StrategyMemoryStatusTile
            label="待晋升信号组"
            value={
              signals.phase === "ready"
                ? String(promotionCandidateGroups.length)
                : "—"
            }
            note="按 group_key 聚合，不平铺每条 raw signal。"
          />
          <StrategyMemoryStatusTile
            label="排序模式"
            value={
              state.phase === "ready"
                ? formatStrategyRankingMode(state.data.ranking_mode)
                : "—"
            }
            note="reward_shadow 只观测奖励排序，不改变召回顺序。"
          />
          <StrategyMemoryStatusTile
            label="统计更新时间"
            value={
              latestStatsUpdatedAt
                ? formatRelativeTime(latestStatsUpdatedAt)
                : "—"
            }
            note="打开模块时会自动补齐过期统计。"
          />
          <StrategyMemoryStatusTile
            label="自动晋升"
            value={formatSchedulerTileValue(schedulerStatus)}
            note={formatSchedulerTileNote(schedulerStatus)}
            tone={schedulerStatus?.last_error ? "warn" : "default"}
          />
        </div>

        <StrategyRewardReadinessPanel
          state={rewardReadiness}
          busyKey={busy}
          onRolloutChange={handleRewardRollout}
        />

        {state.phase === "loading" && <LoadingList rows={3} />}
        {state.phase === "error" && <ErrorBox message={state.message} />}
        {state.phase === "ready" && strategies.length === 0 && (
          <p className="text-xs text-muted-foreground">
            数据库中暂无策略记忆资产。可以先导入种子策略，或等待观察信号晋升。
          </p>
        )}
        {state.phase === "ready" && strategies.length > 0 && (
          <section className="space-y-3">
            <div>
              <p className="text-xs font-medium text-muted-foreground">
                策略记忆资产
              </p>
              <p className="mt-0.5 text-[11px] text-muted-foreground">
                这些是全局策略资产，不属于单个 session；全局统计和上下文统计分开看。
              </p>
            </div>
            <ul className="space-y-2">
              {strategies.map((s) => {
              const strategyStats = s.id ? globalStatsByStrategy.get(s.id) : undefined;
              const contextRows = s.id ? contextStatsByStrategy.get(s.id) ?? [] : [];
              const displayName = strategyDisplayName(s);
              const displayDescription = strategyDisplayDescription(s);
              const showBackendName = shouldShowStrategyBackendName(s);
              const promotedMemory = isPromotedStrategyMemory(s);
              return (
              <li
                key={s.path}
                className="rounded-lg border bg-card/50 p-3 text-sm"
              >
                <div className="flex items-center justify-between gap-2">
                  <div className="min-w-0">
                    <span className="font-medium">{displayName}</span>
                    {showBackendName && (
                      <p className="mt-0.5 truncate text-[11px] text-muted-foreground">
                        后端名称{" "}
                        <span className="font-mono">{s.name}</span>
                      </p>
                    )}
                    <div className="mt-1 flex flex-wrap gap-1.5">
                      {s.source && (
                        <Badge
                          variant={strategyOriginBadgeVariant(s)}
                          className="text-[10px]"
                        >
                          {strategyOriginLabel(s)}
                        </Badge>
                      )}
                      {s.status && (
                        <Badge variant="outline" className="text-[10px]">
                          状态：{formatStrategyStatus(s.status)}
                        </Badge>
                      )}
                      {s.promotion_stage && (
                        <Badge
                          variant="outline"
                          className={cn(
                            "text-[10px]",
                            strategyPromotionStageTone(s.promotion_stage),
                          )}
                        >
                          {strategyPromotionStageLabel(s.promotion_stage)}
                        </Badge>
                      )}
                      {typeof s.priority === "number" && (
                        <Badge variant="outline" className="text-[10px]">
                          优先级 {s.priority}
                        </Badge>
                      )}
                    </div>
                  </div>
                  <span className="max-w-[220px] truncate font-mono text-[10px] text-muted-foreground">
                    {truncate(s.id ?? s.path)}
                  </span>
                </div>
                {displayDescription && (
                  <p className="mt-1 text-xs text-muted-foreground">
                    {displayDescription}
                  </p>
                )}
                {promotedMemory && (
                  <p className="mt-1 rounded-md border border-amber-500/30 bg-amber-500/5 px-2 py-1.5 text-xs text-muted-foreground">
                    由 StrategySignal 聚合晋升，仍需结合样本量、否决率和 reward 表现治理。
                  </p>
                )}
                {s.quality_reason && (
                  <p className="mt-1 text-xs text-amber-500">
                    质量说明：{s.quality_reason}
                  </p>
                )}
                <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
                  <StrategyMemoryInlineMetric
                    label="置信度"
                    value={formatMaybeNumber(s.confidence)}
                  />
                  <StrategyMemoryInlineMetric
                    label="支撑样本"
                    value={String(s.support_count ?? 0)}
                  />
                  <StrategyMemoryInlineMetric
                    label="全局命中"
                    value={strategyStats ? String(strategyStats.uses) : "—"}
                  />
                  <StrategyMemoryInlineMetric
                    label="全局综合奖励"
                    value={formatMaybeNumber(strategyStats?.avg_blended_reward)}
                  />
                  <StrategyMemoryInlineMetric
                    label="全局 Verifier 否决率"
                    value={
                      strategyStats?.overrule_rate === null ||
                      strategyStats?.overrule_rate === undefined
                        ? "—"
                        : formatPercent(strategyStats.overrule_rate)
                    }
                  />
                  <StrategyMemoryInlineMetric
                    label="上下文统计"
                    value={`${contextRows.length} 条`}
                  />
                  <StrategyMemoryInlineMetric
                    label="建议动作"
                    value={s.recommended_action || "—"}
                    mono
                  />
                  <StrategyMemoryInlineMetric
                    label="建议模板"
                    value={s.recommended_plan_template || "—"}
                    mono
                  />
                </div>
                <div className="mt-2 flex flex-wrap gap-3 text-[11px] text-muted-foreground">
                  {s.recommended_probe_intent && (
                    <span className="font-mono">
                      probe_intent: {s.recommended_probe_intent}
                    </span>
                  )}
                  {s.memory_key && (
                    <details className="basis-full text-[11px]">
                      <summary className="cursor-pointer text-muted-foreground">
                        开发详情
                      </summary>
                      <div className="mt-1 truncate font-mono text-muted-foreground">
                        memory_key: {s.memory_key}
                      </div>
                    </details>
                  )}
                </div>
                <StrategyMemoryDetailPanel
                  strategy={s}
                  failureCategories={s.failure_categories ?? []}
                  bodyMarkdown={s.body_markdown ?? ""}
                  contextCount={contextRows.length}
                  globalUses={strategyStats ? String(strategyStats.uses) : "—"}
                  avgReward={formatMaybeNumber(strategyStats?.avg_blended_reward)}
                  overruleRate={
                    strategyStats?.overrule_rate === null ||
                    strategyStats?.overrule_rate === undefined
                      ? "—"
                      : formatPercent(strategyStats.overrule_rate)
                  }
                />
                <StrategyMemoryScopeSummary
                  dimensions={s.dimensions}
                  jobLevels={s.job_levels}
                />
                {contextRows.length > 0 && (
                  <details className="mt-2 text-[11px] text-muted-foreground">
                    <summary className="cursor-pointer">
                      上下文统计 {contextRows.length} 条
                    </summary>
                    <div className="mt-2 grid gap-1.5">
                      {contextRows.slice(0, 3).map((row) => (
                        <StrategyMemoryContextStatsRow key={row.id} row={row} />
                      ))}
                    </div>
                  </details>
                )}
                {s.id && (
                  <details className="mt-3 text-xs">
                    <summary className="cursor-pointer text-muted-foreground">
                      维护操作
                    </summary>
                    <div className="mt-2 flex flex-wrap items-center gap-2">
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        onClick={() => handleStatusAction(s.id, "disable")}
                        disabled={busy !== null || s.status !== "active"}
                      >
                        禁用
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        variant="ghost"
                        onClick={() => handleStatusAction(s.id, "archive")}
                        disabled={busy !== null || s.status === "archived"}
                      >
                        归档
                      </Button>
                      <span className="text-[11px] text-muted-foreground">
                        只影响全局策略资产状态。
                      </span>
                    </div>
                  </details>
                )}
              </li>
              );
            })}
            </ul>
          </section>
        )}

        <section className="space-y-2 border-t border-border/40 pt-4">
          <div>
            <p className="text-xs font-medium text-muted-foreground">
              最近策略使用归因
            </p>
            <p className="mt-0.5 text-[11px] text-muted-foreground">
              展示最近完成评分的出题轮次里，哪些策略记忆被注入并获得了评分/reward 归因。
            </p>
          </div>
          {usages.phase === "loading" && <LoadingList rows={2} />}
          {usages.phase === "error" && <ErrorBox message={usages.message} />}
          {usages.phase === "ready" && usageRows.length === 0 && (
            <p className="rounded-md border border-dashed bg-muted/10 px-3 py-2 text-xs text-muted-foreground">
              暂无策略使用归因，这不是错误。策略只有被注入出题链路并完成评分后才会出现。
            </p>
          )}
          {usages.phase === "ready" && usageRows.length > 0 && (
            <ul className="space-y-1.5">
              {usageRows.slice(0, 5).map((usage) => (
                <li
                  key={usage.id}
                  className="rounded-md border bg-card/30 p-2 text-[11px]"
                >
                  <div className="flex flex-wrap items-center gap-1.5">
                    <Badge variant="outline" className="font-mono text-[10px]">
                      第 {usage.turn_idx} 轮
                    </Badge>
                    <Badge variant="secondary" className="font-mono text-[10px]">
                      {usage.plan_template ?? "模板 -"}
                    </Badge>
                    {usage.session_id && (
                      <SessionIdTooltip
                        sessionId={usage.session_id}
                        side="top"
                        align="start"
                      />
                    )}
                    <span className="min-w-0 truncate font-mono text-muted-foreground">
                      {usage.strategy_id}
                    </span>
                  </div>
                  <div className="mt-1 flex flex-wrap gap-3 text-muted-foreground">
                    <span>context_key {usage.context_key ?? "—"}</span>
                    <span>action {usage.action_id ?? "—"}</span>
                    <span>评分 {formatMaybeNumber(usage.score)}</span>
                    <span>即时奖励 {formatMaybeNumber(usage.immediate_reward)}</span>
                    <span>延迟奖励 {formatMaybeNumber(usage.delayed_reward)}</span>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="space-y-2 border-t border-border/40 pt-4">
          <div>
            <p className="text-xs font-medium text-muted-foreground">
              晋升候选
            </p>
            <p className="mt-0.5 text-[11px] text-muted-foreground">
              按 group_key 聚合观察信号，达到跨 session 支持后才会晋升成策略记忆。
            </p>
          </div>
          {signals.phase === "loading" && <LoadingList rows={2} />}
          {signals.phase === "error" && <ErrorBox message={signals.message} />}
          {signals.phase === "ready" && promotionCandidateGroups.length === 0 && (
            <p className="rounded-md border border-dashed bg-muted/10 px-3 py-2 text-xs text-muted-foreground">
              暂无晋升候选，这不是错误。需要跨 session 积累足够信号后才会进入候选池。
            </p>
          )}
          {signals.phase === "ready" && promotionCandidateGroups.length > 0 && (
            <ul className="space-y-1.5">
              {promotionCandidateGroups.slice(0, 5).map((group) => (
                <li
                  key={group.group_key}
                  className="rounded-md border bg-card/30 p-2 text-[11px]"
                >
                  <div className="flex flex-wrap items-center gap-1.5">
                    <Badge variant="outline" className="font-mono text-[10px]">
                      {formatStrategySignalType(group.signal_type)}
                    </Badge>
                    <Badge variant="secondary" className="font-mono text-[10px]">
                      {group.dimension}
                    </Badge>
                    {group.job_level && (
                      <Badge variant="outline" className="font-mono text-[10px]">
                        {group.job_level}
                      </Badge>
                    )}
                    <Badge variant="outline" className="text-[10px]">
                      {formatStrategyReadiness(group.promotion_readiness)}
                    </Badge>
                    <span className="min-w-0 truncate font-mono text-muted-foreground">
                      {group.group_key}
                    </span>
                  </div>
                  <div className="mt-1 flex flex-wrap gap-3 text-muted-foreground">
                    <span>session {group.distinct_sessions}</span>
                    <span>信号 {group.signal_count}</span>
                    <span>距低置信晋升差 {group.support_gap} 场</span>
                    <span>平均分 {formatMaybeNumber(group.avg_score_after)}</span>
                    <span>平均奖励 {formatMaybeNumber(group.avg_immediate_reward)}</span>
                    <span>
                      Verifier 否决率{" "}
                      {group.overrule_rate === null ||
                      group.overrule_rate === undefined
                        ? "—"
                        : formatPercent(group.overrule_rate)}
                    </span>
                  </div>
                  {group.failure_categories && group.failure_categories.length > 0 && (
                    <div className="mt-1 flex flex-wrap gap-1">
                      <span className="text-muted-foreground">失败类型：</span>
                      {group.failure_categories.map((cat) => (
                        <Badge
                          key={cat}
                          variant="outline"
                          className="font-mono text-[10px] text-amber-500"
                        >
                          {cat}
                        </Badge>
                      ))}
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>

        <details className="rounded-lg border bg-muted/10 p-3 text-xs">
          <summary className="cursor-pointer font-medium text-muted-foreground">
            维护操作
          </summary>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={handleSeedImport}
              disabled={busy !== null}
            >
              {busy === "seed-import" && (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              )}
              导入种子策略
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={handleStatsRefresh}
              disabled={busy !== null}
            >
              {busy === "stats" && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              刷新统计
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={handlePromotionRun}
              disabled={busy !== null}
            >
              {busy === "promotion" && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              立即运行一次
            </Button>
            <span className="text-[11px] text-muted-foreground">
              手动刷新只用于立即同步最新 usage，不会运行晋升；自动晋升状态见上方 tile。
            </span>
          </div>
          {schedulerStatus?.last_result && (
            <div className="mt-3 rounded-md border bg-background/50 px-2.5 py-2 text-[11px] text-muted-foreground">
              <p className="font-medium text-foreground">
                上次{" "}
                {schedulerStatus.last_run_kind === "manual" ? "手动" : "自动"}{" "}
                晋升结果
                {schedulerStatus.last_run_at
                  ? ` · ${formatRelativeTime(schedulerStatus.last_run_at)}`
                  : ""}
              </p>
              <p className="mt-1 font-mono">
                晋升 {schedulerStatus.last_result.promoted ?? 0} ·
                未变 {schedulerStatus.last_result.unchanged ?? 0} ·
                跳过 {schedulerStatus.last_result.skipped ?? 0} ·
                禁用 {schedulerStatus.last_result.disabled ?? 0} ·
                稳定 {schedulerStatus.last_result.stabilized ?? 0}
              </p>
            </div>
          )}
          {schedulerStatus?.last_error && (
            <div className="mt-3 rounded-md border border-amber-500/40 bg-amber-500/10 px-2.5 py-2 text-[11px] text-amber-500">
              <p className="font-medium">
                上次失败
                {schedulerStatus.last_error_at
                  ? ` · ${formatRelativeTime(schedulerStatus.last_error_at)}`
                  : ""}
              </p>
              <p className="mt-1 font-mono break-all">
                {schedulerStatus.last_error}
              </p>
            </div>
          )}
        </details>
      </CardContent>
    </Card>
  );
});

function StrategyRewardReadinessPanel({
  state,
  busyKey,
  onRolloutChange,
}: {
  state: Loadable<StrategyRewardReadiness>;
  busyKey?: string | null;
  onRolloutChange?: (
    contextKey: string,
    mode: StrategyRewardRolloutMode,
  ) => void;
}) {
  return (
    <section className="space-y-3 border-t border-border/40 pt-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="text-xs font-medium text-muted-foreground">
            Reward 排序就绪度
          </p>
          <p className="mt-0.5 text-[11px] text-muted-foreground">
            reward_shadow 只诊断不改线上排序，用来判断哪些上下文适合灰度切到 reward。
          </p>
        </div>
        {state.phase === "ready" && (
          <Badge variant="outline" className="font-mono text-[10px]">
            {state.data.summary.total_contexts} contexts
          </Badge>
        )}
      </div>

      {state.phase === "loading" && <LoadingList rows={2} />}
      {state.phase === "error" && <ErrorBox message={state.message} />}
      {state.phase === "ready" && (
        <div className="space-y-3">
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            <StrategyMemoryInlineMetric
              label="可灰度"
              value={String(state.data.summary.ready_contexts)}
            />
            <StrategyMemoryInlineMetric
              label="仅观测"
              value={String(state.data.summary.shadow_only_contexts)}
            />
            <StrategyMemoryInlineMetric
              label="缺候选"
              value={String(state.data.summary.needs_candidate_contexts)}
            />
            <StrategyMemoryInlineMetric
              label="缺样本"
              value={String(state.data.summary.needs_sample_contexts)}
            />
            <StrategyMemoryInlineMetric
              label="被否决阻塞"
              value={String(state.data.summary.blocked_contexts)}
            />
            <StrategyMemoryInlineMetric
              label="已灰度"
              value={String(state.data.summary.reward_rollout_contexts ?? 0)}
            />
          </div>

          {state.data.contexts.length === 0 && (
            <p className="rounded-md border border-dashed bg-muted/10 px-3 py-2 text-xs text-muted-foreground">
              暂无上下文 reward 诊断；策略被注入并完成评分后才会形成样本。
            </p>
          )}

          {state.data.contexts.length > 0 && (
            <ul className="space-y-1.5">
              {state.data.contexts.slice(0, 8).map((context) => (
                <StrategyRewardReadinessRow
                  key={context.context_key}
                  context={context}
                  busyKey={busyKey}
                  onRolloutChange={onRolloutChange}
                />
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}

function StrategyRewardReadinessRow({
  context,
  busyKey,
  onRolloutChange,
}: {
  context: StrategyRewardReadiness["contexts"][number];
  busyKey?: string | null;
  onRolloutChange?: (
    contextKey: string,
    mode: StrategyRewardRolloutMode,
  ) => void;
}) {
  const parsed = parseStrategyContextKey(context.context_key);
  const overrule =
    context.overrule_rate === null || context.overrule_rate === undefined
      ? "—"
      : formatPercent(context.overrule_rate);
  const rolloutMode = normalizeStrategyRewardRolloutMode(context.rollout_mode);
  const rolloutBusy =
    busyKey === `rollout:${context.context_key}:reward` ||
    busyKey === `rollout:${context.context_key}:reward_shadow`;
  const rolloutDisabled =
    rolloutBusy ||
    !onRolloutChange ||
    (rolloutMode !== "reward" && context.readiness !== "ready");
  return (
    <li className="rounded-md border bg-card/30 p-2 text-[11px]">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-1.5">
            <Badge
              variant="outline"
              className={cn(
                "text-[10px]",
                strategyRewardReadinessTone(context.readiness),
              )}
            >
              {formatStrategyRewardReadiness(context.readiness)}
            </Badge>
            <Badge
              variant="outline"
              className={cn(
                "font-mono text-[10px]",
                strategyRewardRolloutTone(rolloutMode),
              )}
            >
              {formatStrategyRewardRolloutMode(rolloutMode)}
            </Badge>
            {parsed.direction && (
              <Badge variant="secondary" className="font-mono text-[10px]">
                {parsed.direction}
              </Badge>
            )}
            <Badge variant="secondary" className="font-mono text-[10px]">
              {parsed.jobLevel}
            </Badge>
            <Badge variant="outline" className="font-mono text-[10px]">
              {parsed.dimension}
            </Badge>
            <span className="min-w-0 truncate font-mono text-muted-foreground">
              {context.context_key}
            </span>
          </div>
          {context.rollout_reason && (
            <p className="mt-1 text-[11px] text-muted-foreground">
              灰度说明：{context.rollout_reason}
            </p>
          )}
        </div>
        {rolloutMode === "reward" ? (
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={rolloutDisabled}
            onClick={() => onRolloutChange?.(context.context_key, "reward_shadow")}
            className="h-7 shrink-0 text-[11px]"
          >
            {rolloutBusy ? "处理中" : "回退 shadow"}
          </Button>
        ) : (
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={rolloutDisabled}
            onClick={() => onRolloutChange?.(context.context_key, "reward")}
            className="h-7 shrink-0 border-emerald-500/40 text-[11px] text-emerald-600 hover:bg-emerald-500/10"
          >
            {rolloutBusy ? "处理中" : "开启 reward 灰度"}
          </Button>
        )}
      </div>
      <div className="mt-1 flex flex-wrap gap-3 text-muted-foreground">
        <span>候选 {context.candidate_count}</span>
        <span>usage {context.usage_count}</span>
        <span>reward 样本 {context.rewarded_usage_count}</span>
        <span>session {context.distinct_sessions}</span>
        <span>综合奖励 {formatMaybeNumber(context.avg_blended_reward)}</span>
        <span>Verifier 否决率 {overrule}</span>
        <span>{context.rank_changed ? "排序会变化" : "排序不变"}</span>
      </div>
      <details className="mt-2 rounded-md border border-dashed bg-background/40 p-2">
        <summary className="cursor-pointer text-muted-foreground">
          展开 reward readiness 诊断
        </summary>
        <div className="mt-2 grid gap-2 sm:grid-cols-2">
          <StrategyMemoryFact
            label="metadata_top_strategy_ids"
            value={context.metadata_top_strategy_ids.join(", ") || "—"}
            mono
          />
          <StrategyMemoryFact
            label="reward_top_strategy_ids"
            value={context.reward_top_strategy_ids.join(", ") || "—"}
            mono
          />
          <StrategyMemoryFact
            label="rollout_mode"
            value={formatStrategyRewardRolloutMode(rolloutMode)}
            mono
          />
          <StrategyMemoryFact
            label="rollout_source"
            value={context.rollout_source || "default"}
            mono
          />
        </div>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {context.reasons.map((reason) => (
            <Badge key={reason} variant="outline" className="text-[10px]">
              {formatStrategyRewardReason(reason)} · {reason}
            </Badge>
          ))}
        </div>
      </details>
    </li>
  );
}

function StrategyMemoryStatusTile({
  label,
  value,
  note,
  tone = "default",
}: {
  label: string;
  value: string;
  note: string;
  tone?: "default" | "warn";
}) {
  return (
    <div
      className={cn(
        "rounded-md border p-3",
        tone === "warn"
          ? "border-amber-500/40 bg-amber-500/5"
          : "bg-muted/10",
      )}
    >
      <p className="text-[11px] font-medium text-muted-foreground">{label}</p>
      <p
        className={cn(
          "mt-1 font-mono text-lg font-semibold tabular-nums",
          tone === "warn" ? "text-amber-500" : "text-foreground",
        )}
      >
        {value}
      </p>
      <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
        {note}
      </p>
    </div>
  );
}

function formatSchedulerTileValue(
  status: StrategyPromotionSchedulerStatus | null,
): string {
  if (!status) return "—";
  if (!status.enabled) return "已关闭";
  if (status.interval_minutes > 0) return `每 ${status.interval_minutes} 分钟`;
  return "已开启";
}

function formatSchedulerTileNote(
  status: StrategyPromotionSchedulerStatus | null,
): string {
  if (!status) {
    return "打开模块后会同步 scheduler 状态。";
  }
  if (!status.enabled) {
    return "在 settings 里打开 enable_strategy_promotion_scheduler 后生效。";
  }
  const parts: string[] = [];
  if (status.last_run_at) {
    const kind = status.last_run_kind === "manual" ? "手动" : "自动";
    parts.push(`上次${kind} ${formatRelativeTime(status.last_run_at)}`);
  } else {
    parts.push("尚未跑过");
  }
  if (status.next_run_at) {
    parts.push(`下次 ${formatNextRunIn(status.next_run_at)}`);
  }
  if (status.last_error) {
    parts.push(`上次失败：${status.last_error}`);
  }
  return parts.join(" · ");
}

function formatNextRunIn(iso: string): string {
  const time = Date.parse(iso);
  if (!Number.isFinite(time)) return "—";
  const diffMs = time - Date.now();
  if (diffMs <= 0) return "即将运行";
  const minute = 60_000;
  const hour = 60 * minute;
  const day = 24 * hour;
  if (diffMs < minute) return "1 分钟内";
  if (diffMs < hour) return `${Math.floor(diffMs / minute)} 分钟后`;
  if (diffMs < day) return `${Math.floor(diffMs / hour)} 小时后`;
  return `${Math.floor(diffMs / day)} 天后`;
}

function StrategyMemoryInlineMetric({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="rounded-md border bg-background/40 px-2.5 py-2">
      <p className="text-[10px] text-muted-foreground">{label}</p>
      <p
        className={cn(
          "mt-0.5 truncate text-xs font-medium text-foreground",
          mono && "font-mono",
        )}
      >
        {value}
      </p>
    </div>
  );
}

function StrategyMemoryScopeSummary({
  dimensions,
  jobLevels,
}: {
  dimensions: string[];
  jobLevels: string[];
}) {
  if (dimensions.length === 0 && jobLevels.length === 0) return null;
  return (
    <div className="mt-3 space-y-1.5 text-[11px] text-muted-foreground">
      <StrategyMemoryScopeRow label="维度" values={dimensions} variant="secondary" />
      <StrategyMemoryScopeRow label="级别" values={jobLevels} variant="outline" />
    </div>
  );
}

function StrategyMemoryScopeRow({
  label,
  values,
  variant,
}: {
  label: string;
  values: string[];
  variant: "secondary" | "outline";
}) {
  if (values.length === 0) return null;
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="w-8 shrink-0 text-muted-foreground">{label}</span>
      {values.map((value) => (
        <Badge
          key={`${label}-${value}`}
          variant={variant}
          className="font-mono text-[10px]"
        >
          {value}
        </Badge>
      ))}
    </div>
  );
}

function StrategyMemoryContextStatsRow({
  row,
}: {
  row: StrategyStats["stats"][number];
}) {
  const parsed = parseStrategyContextKey(row.context_key);
  return (
    <div className="rounded-md border bg-background/40 px-2 py-1.5">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        {parsed.direction && (
          <StrategyContextPart label="方向" value={parsed.direction} />
        )}
        <StrategyContextPart label="级别" value={parsed.jobLevel} />
        <StrategyContextPart label="维度" value={parsed.dimension} />
        <span className="font-mono text-[10px] text-muted-foreground">
          key {row.context_key}
        </span>
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-muted-foreground">
        <span>命中 {row.uses}</span>
        <span>综合奖励 {formatMaybeNumber(row.avg_blended_reward)}</span>
        <span>
          Verifier 否决率{" "}
          {row.overrule_rate === null || row.overrule_rate === undefined
            ? "—"
            : formatPercent(row.overrule_rate)}
        </span>
      </div>
    </div>
  );
}

function StrategyContextPart({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <span className="inline-flex items-center gap-1">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-mono text-foreground">{value}</span>
    </span>
  );
}

function parseStrategyContextKey(contextKey: string): {
  direction: string | null;
  jobLevel: string;
  dimension: string;
} {
  const parts = contextKey
    .split(":")
    .map((part) => part.trim())
    .filter(Boolean);
  if (parts.length >= 3) {
    return {
      direction: parts.slice(0, -2).join(":"),
      jobLevel: parts[parts.length - 2] ?? "—",
      dimension: parts[parts.length - 1] ?? "—",
    };
  }
  if (parts.length === 2) {
    return {
      direction: null,
      jobLevel: parts[0] ?? "—",
      dimension: parts[1] ?? "—",
    };
  }
  return {
    direction: null,
    jobLevel: "—",
    dimension: contextKey || "—",
  };
}

function StrategyMemoryDetailPanel({
  strategy,
  failureCategories,
  bodyMarkdown,
  contextCount,
  globalUses,
  avgReward,
  overruleRate,
}: {
  strategy: Strategies["strategies"][number];
  failureCategories: string[];
  bodyMarkdown: string;
  contextCount: number;
  globalUses: string;
  avgReward: string;
  overruleRate: string;
}) {
  const body = bodyMarkdown.trim();
  return (
    <details className="mt-3 rounded-md border border-dashed bg-muted/10 p-3 text-xs">
      <summary className="cursor-pointer font-medium text-muted-foreground">
        策略详情
      </summary>
      <div className="mt-3 grid gap-3 lg:grid-cols-2">
        <StrategyMemoryDetailBlock heading="适用范围">
          <div className="flex flex-wrap gap-1.5">
            {strategy.dimensions.map((dimension) => (
              <Badge
                key={`dimension-${dimension}`}
                variant="secondary"
                className="font-mono text-[10px]"
              >
                维度 {dimension}
              </Badge>
            ))}
            {strategy.job_levels.map((level) => (
              <Badge
                key={`level-${level}`}
                variant="outline"
                className="font-mono text-[10px]"
              >
                级别 {level}
              </Badge>
            ))}
            {failureCategories.map((category) => (
              <Badge
                key={`failure-${category}`}
                variant="outline"
                className="font-mono text-[10px] text-amber-500"
              >
                失败类型 {category}
              </Badge>
            ))}
            {strategy.dimensions.length === 0 &&
              strategy.job_levels.length === 0 &&
              failureCategories.length === 0 && (
                <span className="text-[11px] text-muted-foreground">
                  暂无适用范围标签
                </span>
              )}
          </div>
        </StrategyMemoryDetailBlock>

        <StrategyMemoryDetailBlock heading="推荐动作">
          <div className="grid gap-1.5">
            <StrategyMemoryFact
              label="action"
              value={strategy.recommended_action || "—"}
              mono
            />
            <StrategyMemoryFact
              label="plan_template"
              value={strategy.recommended_plan_template || "—"}
              mono
            />
            <StrategyMemoryFact
              label="probe_intent"
              value={strategy.recommended_probe_intent || "—"}
              mono
            />
          </div>
        </StrategyMemoryDetailBlock>

        <StrategyMemoryDetailBlock heading="证据">
          <div className="grid gap-1.5 sm:grid-cols-2">
            <StrategyMemoryFact
              label="支持样本"
              value={String(strategy.support_count ?? 0)}
            />
            <StrategyMemoryFact
              label="置信度"
              value={formatMaybeNumber(strategy.confidence)}
            />
            <StrategyMemoryFact label="全局命中" value={globalUses} />
            <StrategyMemoryFact label="综合奖励" value={avgReward} />
            <StrategyMemoryFact label="Verifier 否决率" value={overruleRate} />
            <StrategyMemoryFact label="上下文统计" value={`${contextCount} 条`} />
          </div>
        </StrategyMemoryDetailBlock>

        <StrategyMemoryDetailBlock heading="开发详情">
          <div className="grid gap-1.5">
            <StrategyMemoryFact
              label="memory_key"
              value={strategy.memory_key || "—"}
              mono
            />
            <StrategyMemoryFact
              label="strategy_id"
              value={strategy.id || strategy.path}
              mono
            />
          </div>
        </StrategyMemoryDetailBlock>
      </div>

      <div className="mt-3">
        <p className="text-[11px] font-medium text-muted-foreground">策略正文</p>
        {body ? (
          <pre className="mt-1 max-h-72 overflow-auto whitespace-pre-wrap break-words rounded-md border bg-background/40 p-2 text-[11px] leading-relaxed text-muted-foreground">
            {body}
          </pre>
        ) : (
          <p className="mt-1 rounded-md border border-dashed bg-background/40 px-2 py-1.5 text-[11px] text-muted-foreground">
            暂无策略正文。
          </p>
        )}
      </div>
    </details>
  );
}

function StrategyMemoryDetailBlock({
  heading,
  children,
}: {
  heading: string;
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-2">
      <p className="text-[11px] font-medium text-muted-foreground">{heading}</p>
      {children}
    </section>
  );
}

function StrategyMemoryFact({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="min-w-0 rounded-md border bg-background/40 px-2 py-1.5">
      <p className="text-[10px] text-muted-foreground">{label}</p>
      <p
        className={cn(
          "mt-0.5 truncate text-[11px] font-medium text-foreground",
          mono && "font-mono",
        )}
      >
        {value}
      </p>
    </div>
  );
}

function countRecentStrategyUsages(
  usages: Array<{ created_at?: string | null }>,
): number {
  const cutoff = Date.now() - 24 * 60 * 60 * 1000;
  return usages.filter((usage) => {
    if (!usage.created_at) return false;
    const time = Date.parse(usage.created_at);
    return Number.isFinite(time) && time >= cutoff;
  }).length;
}

function latestIso(values: Array<string | null | undefined>): string | null {
  let latest: string | null = null;
  let latestTime = Number.NEGATIVE_INFINITY;
  for (const value of values) {
    if (!value) continue;
    const time = Date.parse(value);
    if (!Number.isFinite(time) || time <= latestTime) continue;
    latest = value;
    latestTime = time;
  }
  return latest;
}

function formatStrategySource(value?: string | null): string {
  if (!value) return "未知";
  if (value === "seed") return "种子";
  if (value === "promoted") return "晋升";
  if (value === "promoted_signal") return "自动晋升";
  return value;
}

function formatStrategyStatus(value?: string | null): string {
  if (!value) return "未知";
  if (value === "active") return "启用";
  if (value === "disabled") return "禁用";
  if (value === "archived") return "归档";
  return value;
}

function formatPromotionStage(value?: string | null): string {
  if (!value) return "未知";
  if (value === "seed") return "种子";
  if (value === "starter") return "起步";
  if (value === "promotion_candidate") return "待晋升";
  if (value === "low_confidence") return "低置信晋升";
  if (value === "stable") return "稳定策略";
  if (value === "stabilized") return "稳定策略";
  return value;
}

function formatStrategyRankingMode(value?: string | null): string {
  if (value === "reward_shadow") return "reward_shadow";
  if (value === "reward") return "reward";
  if (value === "metadata") return "metadata";
  return value || "metadata";
}

function formatStrategySignalType(value?: string | null): string {
  if (value === "score_recovery") return "评分恢复";
  if (value === "hint_effective") return "提示有效";
  if (value === "high_reward_arm") return "高奖励动作";
  if (value === "score_decline") return "评分下降";
  if (value === "low_reward_arm") return "低奖励动作";
  return value || "未知信号";
}

function formatStrategyReadiness(value?: string | null): string {
  if (value === "needs_more_sessions") return "样本不足";
  if (value === "blocked_by_overrule") return "Verifier 阻断";
  if (value === "weak_evidence") return "证据偏弱";
  if (value === "ready_low_confidence") return "可低置信晋升";
  if (value === "ready_stable") return "可稳定晋升";
  if (value === "diagnostic_only") return "仅诊断";
  return value || "未知状态";
}

function formatStrategyRewardReadiness(value?: string | null): string {
  if (value === "ready") return "可灰度";
  if (value === "shadow_only") return "仅观测";
  if (value === "needs_candidates") return "缺候选";
  if (value === "needs_samples") return "缺样本";
  if (value === "blocked_by_overrule") return "Verifier 阻塞";
  return value || "未知状态";
}

function normalizeStrategyRewardRolloutMode(
  value?: string | null,
): StrategyRewardRolloutMode {
  if (value === "metadata" || value === "reward") return value;
  return "reward_shadow";
}

function formatStrategyRewardRolloutMode(
  value?: string | null,
): string {
  if (value === "reward") return "reward 灰度";
  if (value === "metadata") return "metadata 固定";
  return "reward_shadow";
}

function strategyRewardRolloutTone(value?: string | null): string {
  if (value === "reward") return "border-emerald-500/50 text-emerald-600";
  if (value === "metadata") return "border-slate-500/50 text-slate-600";
  return "border-sky-500/50 text-sky-600";
}

function strategyRewardReadinessTone(value?: string | null): string {
  if (value === "ready") return "border-emerald-500/50 text-emerald-600";
  if (value === "shadow_only") return "border-sky-500/50 text-sky-600";
  if (value === "blocked_by_overrule") return "border-red-500/50 text-red-600";
  if (value === "needs_candidates" || value === "needs_samples") {
    return "border-amber-500/50 text-amber-600";
  }
  return "text-muted-foreground";
}

function formatStrategyRewardReason(value?: string | null): string {
  if (value === "candidate_pool_below_min") return "候选池不足";
  if (value === "reward_samples_below_min") return "reward 样本不足";
  if (value === "session_coverage_below_min") return "session 覆盖不足";
  if (value === "overrule_rate_high") return "Verifier 否决率偏高";
  if (value === "reward_shadow_rank_changed") return "reward shadow 会改变排序";
  if (value === "reward_shadow_rank_same") return "reward shadow 排序一致";
  return value || "未知原因";
}

function formatSkillRewardRolloutMode(value?: string | null): string {
  if (value === "reward") return "reward 灰度";
  if (value === "metadata") return "metadata 固定";
  return "reward_shadow";
}

function skillRewardRolloutTone(value?: string | null): string {
  if (value === "reward") return "border-emerald-500/50 text-emerald-600";
  if (value === "metadata") return "border-slate-500/50 text-slate-600";
  return "border-sky-500/50 text-sky-600";
}

function formatSkillRewardReadiness(value?: string | null): string {
  if (value === "ready") return "可灰度";
  if (value === "needs_samples") return "样本不足";
  if (value === "needs_candidates") return "候选不足";
  if (value === "shadow_only") return "仅 shadow";
  if (value === "blocked_by_overrule") return "否决偏高";
  return value || "未知状态";
}

function skillRewardReadinessTone(value?: string | null): string {
  if (value === "ready") return "border-emerald-500/50 text-emerald-600";
  if (value === "shadow_only") return "border-sky-500/50 text-sky-600";
  if (value === "blocked_by_overrule") return "border-red-500/50 text-red-600";
  if (value === "needs_candidates" || value === "needs_samples") {
    return "border-amber-500/50 text-amber-600";
  }
  return "text-muted-foreground";
}

function formatSkillRewardReason(value?: string | null): string {
  if (value === "candidate_pool_below_min") return "候选池不足";
  if (value === "single_skill_no_rank_effect") return "单 Skill 无排序效果";
  if (value === "reward_samples_below_min") return "reward 样本不足";
  if (value === "overrule_rate_high") return "否决率偏高";
  if (value === "reward_shadow_rank_changed") return "模拟 reward 后排序会变化";
  if (value === "reward_shadow_rank_same") return "模拟 reward 后排序不变";
  if (value === "high_reward_low_sample") return "高 reward 但样本少";
  if (value === "missing_reward_stats") return "缺少 reward stats";
  return value || "未知原因";
}

function formatQuestionRewardReason(value?: string | null): string {
  if (value === "candidate_pool_below_min") return "候选池不足";
  if (value === "reward_samples_below_min") return "reward 样本不足";
  if (value === "high_reward_low_sample") return "高 reward 但样本少";
  if (value === "reward_shadow_rank_changed") return "模拟 reward 后 Top K 会变化";
  if (value === "reward_shadow_rank_same") return "模拟 reward 后 Top K 不变";
  return value || "未知原因";
}

// ---------------------------------------------------------------------------
// Shared primitives
// ---------------------------------------------------------------------------

function LoadingList({ rows }: { rows: number }) {
  return (
    <div className="space-y-2">
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className="h-5 w-full" />
      ))}
    </div>
  );
}

function ErrorBox({ message }: { message: string }) {
  return (
    <div className="flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/5 p-3 text-xs text-destructive">
      <Activity className="mt-0.5 h-3.5 w-3.5" />
      <span>{message}</span>
    </div>
  );
}

function MetaPill({ label, value }: { label: string; value: string }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-full border bg-card/50 px-2 py-0.5 text-xs">
      <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
        {label}
      </span>
      <span className="font-mono tabular-nums">{value}</span>
    </span>
  );
}

function TimeCell({ iso }: { iso: string }) {
  return (
    <span
      aria-label={`完整时间：${formatDateTime(iso)}`}
      className="inline-flex flex-col gap-0.5"
    >
      <span className="text-xs text-foreground/70">{formatRelativeTime(iso)}</span>
      <span className="font-mono text-[10px] text-muted-foreground/60">
        {formatDateTime(iso)}
      </span>
    </span>
  );
}

function StatBox({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border bg-card/50 p-3">
      <div className="font-mono text-[10px] tracking-wider text-muted-foreground">
        {label}
      </div>
      <div className="mt-1 font-mono text-lg tabular-nums">{value}</div>
    </div>
  );
}

function truncate(v: string): string {
  if (v.length <= 16) return v;
  return `${v.slice(0, 6)}…${v.slice(-6)}`;
}

async function copyToClipboard(value: string): Promise<void> {
  if (!value) return;
  try {
    await navigator.clipboard?.writeText(value);
    return;
  } catch {
    /* fall through to the legacy copy path */
  }

  const el = document.createElement("textarea");
  el.value = value;
  el.setAttribute("readonly", "");
  el.style.position = "fixed";
  el.style.left = "-9999px";
  document.body.appendChild(el);
  el.select();
  try {
    document.execCommand("copy");
  } finally {
    document.body.removeChild(el);
  }
}

function formatRelativeTime(iso: string): string {
  const time = Date.parse(iso);
  if (!Number.isFinite(time)) return "—";
  const diffMs = Date.now() - time;
  const absMs = Math.abs(diffMs);
  const minute = 60_000;
  const hour = 60 * minute;
  const day = 24 * hour;
  if (absMs < minute) return "刚刚";
  if (absMs < hour) return `${Math.floor(absMs / minute)} 分钟前`;
  if (absMs < day) return `${Math.floor(absMs / hour)} 小时前`;
  return `${Math.floor(absMs / day)} 天前`;
}

function formatDateTime(iso: string): string {
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "—";
    return `${d.toLocaleDateString()} ${d.toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
    })}`;
  } catch {
    return iso;
  }
}

function formatPercent(value: number): string {
  if (!Number.isFinite(value)) return "0%";
  return `${Math.round(value * 100)}%`;
}

function formatMaybeNumber(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return value.toFixed(2);
}

// ---------------------------------------------------------------------------
// RAG Evaluation Section
// ---------------------------------------------------------------------------

function RagEvalSection() {
  return (
    <section className="space-y-3">
      <div>
        <h2 className="text-sm font-semibold">RAG 观察</h2>
        <p className="mt-1 text-xs text-muted-foreground">
          知识库 RAG 与资料理解 RAG 分开观测，避免把两类检索质量混成一个指标。
        </p>
      </div>
      <div className="space-y-6">
        <RagEvalPanel />
        <CandidateAnchorRagCard />
      </div>
    </section>
  );
}
