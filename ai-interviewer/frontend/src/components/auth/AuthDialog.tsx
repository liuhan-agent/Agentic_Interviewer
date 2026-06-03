"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import {
  BadgeCheck,
  ChevronDown,
  Database,
  Eye,
  EyeOff,
  History,
  KeyRound,
  Loader2,
  LogOut,
  ReceiptText,
  UserRound,
  WalletCards,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  createAccountCreditRequest,
  getAccountCreditRequests,
  getAccountCredits,
  getAccountInterviewSessions,
} from "@/lib/api/account";
import type {
  AccountCreditLedgerEntry,
  AccountCreditRequest,
} from "@/lib/api/types";
import { useAuth } from "@/lib/auth/useAuth";
import { formatCreditLedgerEntry } from "@/lib/credits";
import { getHistory, getSessionToken } from "@/lib/storage/interviewHistory";

type AuthMode = "login" | "register";
const MIN_AUTH_PASSWORD_LENGTH = 8;
const MAX_AUTH_PASSWORD_LENGTH = 128;

interface AccountDialogSummary {
  balance: number | null;
  freeGrantTotal: number | null;
  recentEntries: AccountCreditLedgerEntry[];
  creditRequests: AccountCreditRequest[];
  accountSessionCount: number | null;
  localAnonymousCount: number;
  claimableAnonymousCount: number;
  otherAccountLocalCount: number;
}

const EMPTY_ACCOUNT_SUMMARY: AccountDialogSummary = {
  balance: null,
  freeGrantTotal: null,
  recentEntries: [],
  creditRequests: [],
  accountSessionCount: null,
  localAnonymousCount: 0,
  claimableAnonymousCount: 0,
  otherAccountLocalCount: 0,
};

function roleLabel(role: string): string {
  if (role === "admin") return "管理员";
  return role === "user" ? "普通用户" : role;
}

function readLocalAccountSummary(currentUserId: number): Pick<
  AccountDialogSummary,
  "localAnonymousCount" | "claimableAnonymousCount" | "otherAccountLocalCount"
> {
  const entries = getHistory();
  return entries.reduce(
    (summary, entry) => {
      if (!entry.ownerUserId) {
        summary.localAnonymousCount += 1;
        if (getSessionToken(entry.sessionId)) {
          summary.claimableAnonymousCount += 1;
        }
      } else if (entry.ownerUserId !== currentUserId) {
        summary.otherAccountLocalCount += 1;
      }
      return summary;
    },
    {
      localAnonymousCount: 0,
      claimableAnonymousCount: 0,
      otherAccountLocalCount: 0,
    },
  );
}

function countLabel(value: number | null, loading: boolean): string {
  if (value !== null) return String(value);
  return loading ? "读取中" : "-";
}

function creditRequestStatusLabel(status: AccountCreditRequest["status"]): string {
  if (status === "pending") return "待处理";
  if (status === "approved") return "已批准";
  if (status === "rejected") return "已拒绝";
  return status;
}

function formatLedgerTime(value?: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function AuthDialog({
  children,
  onSettled,
}: {
  children: React.ReactNode;
  onSettled?: () => void;
}) {
  const auth = useAuth();
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<AuthMode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);
  const [creditRequestAmount, setCreditRequestAmount] = useState("5");
  const [creditRequestReason, setCreditRequestReason] = useState("");
  const [showCreditRequestForm, setShowCreditRequestForm] = useState(false);
  const [creditRequestPending, setCreditRequestPending] = useState(false);
  const [accountSummary, setAccountSummary] = useState<AccountDialogSummary>(
    EMPTY_ACCOUNT_SUMMARY,
  );
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [summaryError, setSummaryError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    if (!open) {
      setAccountSummary(EMPTY_ACCOUNT_SUMMARY);
      setSummaryLoading(false);
      setSummaryError(null);
      return;
    }
    if (auth.loading) return;
    if (!auth.authenticated || !auth.user) {
      setAccountSummary(EMPTY_ACCOUNT_SUMMARY);
      setSummaryLoading(false);
      setSummaryError(null);
      return;
    }

    const localSummary = readLocalAccountSummary(auth.user.id);
    setAccountSummary((current) => ({ ...current, ...localSummary }));
    setSummaryLoading(true);
    setSummaryError(null);

    void Promise.all([
      getAccountCredits(),
      getAccountInterviewSessions({ limit: 1 }),
      getAccountCreditRequests({ limit: 5 }),
    ])
      .then(([credits, sessions, creditRequests]) => {
        if (cancelled) return;
        setAccountSummary({
          ...localSummary,
          balance: credits.balance,
          freeGrantTotal: credits.free_grant_total,
          recentEntries: credits.recent_entries ?? [],
          creditRequests: creditRequests.requests ?? [],
          accountSessionCount: sessions.total_count,
        });
      })
      .catch((err) => {
        if (cancelled) return;
        setAccountSummary({
          ...EMPTY_ACCOUNT_SUMMARY,
          ...localSummary,
        });
        setSummaryError(err instanceof Error ? err.message : "账号信息读取失败");
      })
      .finally(() => {
        if (!cancelled) setSummaryLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [open, auth.authenticated, auth.loading, auth.user]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLocalError(null);
    if (password.length < MIN_AUTH_PASSWORD_LENGTH) {
      setLocalError(`密码至少 ${MIN_AUTH_PASSWORD_LENGTH} 位`);
      return;
    }
    if (password.length > MAX_AUTH_PASSWORD_LENGTH) {
      setLocalError(`密码最多 ${MAX_AUTH_PASSWORD_LENGTH} 位`);
      return;
    }
    try {
      if (mode === "login") {
        await auth.login(email, password);
      } else {
        if (password !== confirmPassword) {
          setLocalError("两次输入的密码不一致");
          return;
        }
        await auth.register(email, password);
      }
    } catch (err) {
      setLocalError(err instanceof Error ? err.message : "请求失败");
      return;
    }
    setPassword("");
    setConfirmPassword("");
    setOpen(false);
    onSettled?.();
  }

  async function handleCreditRequestSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLocalError(null);
    const requestedAmount = Number.parseInt(creditRequestAmount, 10);
    if (!Number.isFinite(requestedAmount) || requestedAmount < 1 || requestedAmount > 20) {
      setLocalError("申请次数需在 1 到 20 次之间");
      return;
    }
    const reason = creditRequestReason.trim();
    if (!reason) {
      setLocalError("请填写申请用途");
      return;
    }
    setCreditRequestPending(true);
    try {
      const created = await createAccountCreditRequest({
        requested_amount: requestedAmount,
        reason,
      });
      setAccountSummary((current) => ({
        ...current,
        creditRequests: [created.request, ...current.creditRequests],
      }));
      setCreditRequestReason("");
      setShowCreditRequestForm(false);
    } catch (err) {
      setLocalError(err instanceof Error ? err.message : "申请提交失败");
    } finally {
      setCreditRequestPending(false);
    }
  }

  async function handleLogout() {
    setLocalError(null);
    try {
      await auth.logout();
      setOpen(false);
      onSettled?.();
    } catch (err) {
      setLocalError(err instanceof Error ? err.message : "退出登录失败");
    }
  }

  function handleNavigateAway() {
    setOpen(false);
    onSettled?.();
  }

  function handleOpenChange(nextOpen: boolean) {
    setOpen(nextOpen);
    if (!nextOpen) {
      setLocalError(null);
      setPassword("");
      setConfirmPassword("");
      setShowPassword(false);
      setShowConfirmPassword(false);
      setShowCreditRequestForm(false);
    }
  }

  function handleModeSwitch() {
    setMode(mode === "login" ? "register" : "login");
    setLocalError(null);
    setConfirmPassword("");
    setShowConfirmPassword(false);
  }

  const latestCreditEntry = accountSummary.recentEntries[0]
    ? formatCreditLedgerEntry(accountSummary.recentEntries[0])
    : null;
  const pendingCreditRequest =
    accountSummary.creditRequests.find((request) => request.status === "pending") ?? null;
  const latestCreditRequest = accountSummary.creditRequests[0] ?? null;

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>{children}</DialogTrigger>
      <DialogContent className="grid max-h-[calc(100dvh-2rem)] grid-rows-[auto_minmax(0,1fr)_auto] gap-0 overflow-hidden p-0 sm:max-w-[520px]">
        <DialogHeader className="border-b px-6 pb-3 pt-6 pr-12">
          <DialogTitle className="flex items-center gap-2">
            <UserRound className="h-4 w-4 text-emerald-400" />
            {auth.authenticated ? "账号与额度" : mode === "login" ? "登录" : "注册"}
          </DialogTitle>
          <DialogDescription>
            {auth.authenticated
              ? "查看账号记录归属、平台额度和高级 API 模式。"
              : "登录后，新的面试会保存到你的账号；不登录也可以继续游客体验。"}
          </DialogDescription>
        </DialogHeader>

        {auth.authenticated && auth.user ? (
          <>
            <div className="min-h-0 overflow-y-auto px-6 py-4">
              <div className="space-y-3">
                <section className="rounded-lg border bg-secondary/35 p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="text-sm text-muted-foreground">当前账号</div>
                      <div className="mt-1 truncate text-base font-semibold text-foreground">
                        {auth.user.email}
                      </div>
                    </div>
                    <span className="inline-flex shrink-0 items-center gap-1.5 rounded-full border bg-background px-2.5 py-1 text-xs text-muted-foreground">
                      <BadgeCheck className="h-3.5 w-3.5 text-emerald-400" />
                      {auth.user.role === "user" ? "普通用户" : roleLabel(auth.user.role)}
                    </span>
                  </div>
                  <div className="mt-4 grid grid-cols-2 gap-3">
                    <div className="rounded-md border bg-background/70 px-3 py-2">
                      <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                        <WalletCards className="h-3.5 w-3.5 text-emerald-400" />
                        剩余次数
                      </div>
                      <div className="mt-1 flex items-end gap-1.5">
                        <span className="text-2xl font-semibold leading-none">
                          {countLabel(accountSummary.balance, summaryLoading)}
                        </span>
                        <span className="text-xs text-muted-foreground">次</span>
                      </div>
                    </div>
                    <div className="rounded-md border bg-background/70 px-3 py-2">
                      <div className="text-xs text-muted-foreground">免费赠送</div>
                      <div className="mt-1 flex items-end gap-1.5">
                        <span className="text-2xl font-semibold leading-none">
                          {countLabel(accountSummary.freeGrantTotal, summaryLoading)}
                        </span>
                        <span className="text-xs text-muted-foreground">次</span>
                      </div>
                    </div>
                  </div>
                  <p className="mt-3 text-xs leading-relaxed text-muted-foreground">
                    平台托管模式每开始一场面试扣 1 次；个人 Key 不扣平台次数。
                  </p>
                </section>

                <section className="rounded-lg border bg-background p-3">
                  <div className="flex items-start gap-3">
                    <WalletCards className="mt-0.5 h-4 w-4 text-emerald-400" />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center justify-between gap-3">
                        <h3 className="text-sm font-semibold">申请补充次数</h3>
                        {latestCreditRequest && (
                          <span className="shrink-0 rounded-full border bg-secondary/40 px-2 py-0.5 text-xs text-muted-foreground">
                            {creditRequestStatusLabel(latestCreditRequest.status)}
                          </span>
                        )}
                      </div>
                      <p className="mt-1 text-xs text-muted-foreground">
                        每个账号同时只能有 1 个待处理申请；管理员通过后会直接补充到平台次数。
                      </p>
                      {pendingCreditRequest || showCreditRequestForm ? (
                        pendingCreditRequest ? (
                        <div className="mt-3 rounded-md border bg-secondary/25 px-3 py-2 text-xs">
                          <div className="font-medium text-foreground">待处理申请</div>
                          <div className="mt-1 text-muted-foreground">
                            申请 {pendingCreditRequest.requested_amount} 次 ·{" "}
                            {pendingCreditRequest.reason}
                          </div>
                        </div>
                        ) : (
                        <form
                          className="mt-3 space-y-2"
                          onSubmit={handleCreditRequestSubmit}
                        >
                          <div className="grid gap-2 sm:grid-cols-[6.5rem_minmax(0,1fr)]">
                            <div className="space-y-1">
                              <Label htmlFor="credit-request-amount">次数</Label>
                              <Input
                                id="credit-request-amount"
                                inputMode="numeric"
                                value={creditRequestAmount}
                                onChange={(event) =>
                                  setCreditRequestAmount(event.target.value)
                                }
                              />
                            </div>
                            <div className="space-y-1">
                              <Label htmlFor="credit-request-reason">用途说明</Label>
                              <Input
                                id="credit-request-reason"
                                value={creditRequestReason}
                                maxLength={500}
                                onChange={(event) =>
                                  setCreditRequestReason(event.target.value)
                                }
                                placeholder="例如：准备校招/转岗/公益模拟面试"
                              />
                            </div>
                          </div>
                          <Button
                            type="submit"
                            size="sm"
                            className="w-full gap-2"
                            disabled={creditRequestPending}
                          >
                            {creditRequestPending && (
                              <Loader2 className="h-4 w-4 animate-spin" />
                            )}
                            提交申请
                          </Button>
                        </form>
                        )
                      ) : (
                        <div className="mt-3 space-y-2 rounded-md border bg-secondary/20 px-3 py-2 text-xs">
                          <div className="font-medium text-foreground">
                            {latestCreditRequest
                              ? `最近申请结果：${creditRequestStatusLabel(latestCreditRequest.status)}`
                              : "当前没有待处理申请"}
                          </div>
                          {latestCreditRequest ? (
                            <div className="mt-1 text-muted-foreground">
                              申请 {latestCreditRequest.requested_amount} 次
                              {latestCreditRequest.decision_reason
                                ? ` · ${latestCreditRequest.decision_reason}`
                                : ""}
                            </div>
                          ) : (
                            <div className="mt-1 text-muted-foreground">
                              需要更多平台面试次数时，可以提交一条申请。
                            </div>
                          )}
                          <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            className="w-full"
                            onClick={() => setShowCreditRequestForm(true)}
                          >
                            再次申请补充次数
                          </Button>
                        </div>
                      )}
                      {accountSummary.creditRequests.length > 0 && (
                        <details className="group mt-3 rounded-md border bg-secondary/10 px-3 py-2">
                          <summary className="flex cursor-pointer list-none items-center justify-between gap-2 text-xs">
                            <span className="font-medium text-foreground">
                              最近申请记录
                            </span>
                            <span className="flex items-center gap-1 text-muted-foreground">
                              {accountSummary.creditRequests.length} 条
                              <ChevronDown className="h-3.5 w-3.5 transition-transform group-open:rotate-180" />
                            </span>
                          </summary>
                          <div className="mt-2 space-y-2">
                            {accountSummary.creditRequests.slice(0, 5).map((request) => (
                              <div
                                key={request.id}
                                className="rounded-md border bg-background/60 px-2 py-2 text-xs"
                              >
                                <div className="flex items-center justify-between gap-2">
                                  <span className="font-medium text-foreground">
                                    {creditRequestStatusLabel(request.status)}
                                  </span>
                                  <span className="text-muted-foreground">
                                    {request.requested_amount} 次
                                  </span>
                                </div>
                                <div className="mt-1 line-clamp-2 text-muted-foreground">
                                  {request.reason}
                                </div>
                                {(request.decision_reason || request.created_at) && (
                                  <div className="mt-1 text-muted-foreground">
                                    {request.decision_reason || "等待管理员处理"}
                                    {request.created_at
                                      ? ` · ${formatLedgerTime(request.created_at)}`
                                      : ""}
                                  </div>
                                )}
                              </div>
                            ))}
                          </div>
                        </details>
                      )}
                    </div>
                  </div>
                </section>

                <section className="rounded-lg border bg-background p-3">
                  <div className="flex items-center gap-2">
                    <History className="h-4 w-4 text-emerald-400" />
                    <h3 className="text-sm font-semibold">我的面试记录</h3>
                  </div>
                  <div className="mt-3 grid grid-cols-2 gap-3">
                    <div className="rounded-md bg-secondary/30 px-3 py-2">
                      <div className="text-xs text-muted-foreground">账号记录</div>
                      <div className="mt-1 text-xl font-semibold">
                        {countLabel(accountSummary.accountSessionCount, summaryLoading)}
                      </div>
                    </div>
                    <div className="rounded-md bg-secondary/30 px-3 py-2">
                      <div className="text-xs text-muted-foreground">本机匿名记录</div>
                      <div className="mt-1 text-xl font-semibold">
                        {accountSummary.localAnonymousCount}
                      </div>
                    </div>
                  </div>
                  {accountSummary.localAnonymousCount > 0 && (
                    <div className="mt-3 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                      <p className="text-xs text-muted-foreground">
                        {accountSummary.claimableAnonymousCount > 0
                          ? `有 ${accountSummary.claimableAnonymousCount} 场可同步到账号。`
                          : "当前没有可同步凭证，只能本机查看，不能删除服务端数据。"}
                      </p>
                      <Button asChild size="sm" variant="outline" className="shrink-0">
                        <Link href="/interview/history" onClick={handleNavigateAway}>
                          <Database className="h-3.5 w-3.5" />
                          {accountSummary.claimableAnonymousCount > 0
                            ? "去同步可认领记录"
                            : "查看本机匿名记录"}
                        </Link>
                      </Button>
                    </div>
                  )}
                  {accountSummary.otherAccountLocalCount > 0 && (
                    <p className="mt-2 text-xs text-muted-foreground">
                      本机还有 {accountSummary.otherAccountLocalCount} 场属于其他账号的记录。
                    </p>
                  )}
                </section>

                <details className="group rounded-lg border bg-background p-3">
                  <summary className="flex cursor-pointer list-none items-center justify-between gap-3">
                    <span className="flex min-w-0 items-center gap-2">
                      <ReceiptText className="h-4 w-4 shrink-0 text-emerald-400" />
                      <span className="text-sm font-semibold">最近额度流水</span>
                    </span>
                    <span className="flex min-w-0 items-center gap-2 text-xs text-muted-foreground">
                      <span className="truncate">
                        {latestCreditEntry
                          ? `最近一条：${latestCreditEntry.title} ${latestCreditEntry.deltaLabel}`
                          : summaryLoading
                            ? "正在读取"
                            : "暂无流水"}
                      </span>
                      <ChevronDown className="h-3.5 w-3.5 shrink-0 transition-transform group-open:rotate-180" />
                    </span>
                  </summary>
                  <div className="mt-3 space-y-2">
                    {summaryLoading && accountSummary.recentEntries.length === 0 ? (
                      <p className="text-sm text-muted-foreground">正在读取额度流水</p>
                    ) : accountSummary.recentEntries.length === 0 ? (
                      <p className="text-sm text-muted-foreground">
                        暂无额度流水。开始平台托管面试后，这里会显示扣减记录。
                      </p>
                    ) : (
                      accountSummary.recentEntries.slice(0, 5).map((entry) => {
                        const formatted = formatCreditLedgerEntry(entry);
                        return (
                          <div
                            key={entry.id}
                            className="flex items-start justify-between gap-3 rounded-md border bg-secondary/20 px-3 py-2 text-xs"
                          >
                            <div className="min-w-0">
                              <div className="font-medium text-foreground">
                                {formatted.title}
                              </div>
                              <div className="mt-0.5 truncate text-muted-foreground">
                                {formatted.description}
                              </div>
                            </div>
                            <div className="shrink-0 text-right">
                              <div
                                className={
                                  formatted.tone === "negative"
                                    ? "font-semibold text-amber-500"
                                    : formatted.tone === "positive"
                                      ? "font-semibold text-emerald-500"
                                      : "font-semibold text-muted-foreground"
                                }
                              >
                                {formatted.deltaLabel}
                              </div>
                              <div className="text-muted-foreground">
                                {formatted.balanceLabel}
                              </div>
                              {entry.created_at && (
                                <div className="text-muted-foreground">
                                  {formatLedgerTime(entry.created_at)}
                                </div>
                              )}
                            </div>
                          </div>
                        );
                      })
                    )}
                  </div>
                </details>

                <section className="rounded-lg border bg-background p-3">
                  <div className="flex items-start gap-3">
                    <KeyRound className="mt-0.5 h-4 w-4 text-emerald-400" />
                    <div>
                      <h3 className="text-sm font-semibold">个人 API Key / BYOK</h3>
                      <p className="mt-1 text-sm text-muted-foreground">
                        使用个人 Key 时不扣平台次数，但会消耗你自己的模型服务额度；入口仍保留在顶部 API 设置。
                      </p>
                    </div>
                  </div>
                </section>

                {(summaryError || localError || auth.error) && (
                  <p className="text-sm text-destructive">
                    {summaryError ?? localError ?? auth.error}
                  </p>
                )}
              </div>
            </div>
            <div className="border-t bg-background/95 px-6 py-4">
              <Button
                type="button"
                variant="outline"
                className="w-full gap-2"
                onClick={handleLogout}
                disabled={auth.pending}
              >
                {auth.pending ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <LogOut className="h-4 w-4" />
                )}
                退出登录
              </Button>
            </div>
          </>
        ) : (
          <form className="min-h-0 space-y-4 overflow-y-auto px-6 py-4" onSubmit={handleSubmit}>
            <div className="space-y-2">
              <Label htmlFor="auth-email">邮箱</Label>
              <Input
                id="auth-email"
                type="email"
                autoComplete="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="auth-password">密码</Label>
              <div className="relative">
                <Input
                  id="auth-password"
                  type={showPassword ? "text" : "password"}
                  autoComplete={mode === "login" ? "current-password" : "new-password"}
                  minLength={MIN_AUTH_PASSWORD_LENGTH}
                  maxLength={MAX_AUTH_PASSWORD_LENGTH}
                  value={password}
                  onChange={(event) => {
                    setPassword(event.target.value);
                    setLocalError(null);
                  }}
                  className="pr-10"
                  required
                />
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="absolute right-1 top-1/2 h-7 w-7 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                  onClick={() => setShowPassword((visible) => !visible)}
                  aria-label={showPassword ? "隐藏密码" : "显示密码"}
                >
                  {showPassword ? (
                    <EyeOff className="h-4 w-4" />
                  ) : (
                    <Eye className="h-4 w-4" />
                  )}
                </Button>
              </div>
            </div>
            {mode === "register" && (
              <div className="space-y-2">
                <Label htmlFor="auth-confirm-password">确认密码</Label>
                <div className="relative">
                  <Input
                    id="auth-confirm-password"
                    type={showConfirmPassword ? "text" : "password"}
                    autoComplete="new-password"
                    minLength={MIN_AUTH_PASSWORD_LENGTH}
                    maxLength={MAX_AUTH_PASSWORD_LENGTH}
                    value={confirmPassword}
                    onChange={(event) => {
                      setConfirmPassword(event.target.value);
                      setLocalError(null);
                    }}
                    className="pr-10"
                    required
                  />
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="absolute right-1 top-1/2 h-7 w-7 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                    onClick={() =>
                      setShowConfirmPassword((visible) => !visible)
                    }
                    aria-label={
                      showConfirmPassword ? "隐藏确认密码" : "显示确认密码"
                    }
                  >
                    {showConfirmPassword ? (
                      <EyeOff className="h-4 w-4" />
                    ) : (
                      <Eye className="h-4 w-4" />
                    )}
                  </Button>
                </div>
              </div>
            )}
            {(localError || auth.error) && (
              <p className="text-sm text-destructive">{localError ?? auth.error}</p>
            )}
            <Button type="submit" className="w-full gap-2" disabled={auth.pending}>
              {auth.pending && <Loader2 className="h-4 w-4 animate-spin" />}
              {mode === "login" ? "登录" : "注册"}
            </Button>
            <Button
              type="button"
              variant="ghost"
              className="w-full"
              onClick={handleModeSwitch}
            >
              {mode === "login" ? "还没有账号？注册" : "已有账号？登录"}
            </Button>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}
