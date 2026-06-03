import type { AccountCreditLedgerEntry, StartSessionResponse } from "@/lib/api/types";

export interface CreditPolicyForGate {
  enforced: boolean;
  free_grant?: number;
  requires_login_for_platform_hosted?: boolean;
}

export interface CreditAuthForGate {
  authenticated: boolean;
  loading?: boolean;
}

export interface CreditStartGateState {
  usesPlatformCredits: boolean;
  disabled: boolean;
  notice: string | null;
  ctaLabel: string | null;
}

export interface FormattedCreditLedgerEntry {
  title: string;
  description: string;
  deltaLabel: string;
  balanceLabel: string;
  tone: "positive" | "negative" | "neutral";
}

export function formatBillingMode(
  mode: StartSessionResponse["billing_mode"],
): string {
  if (mode === "platform_credits") return "平台次数";
  if (mode === "byok") return "个人 Key";
  return "开发免计费";
}

export function formatCreditLedgerEntry(
  entry: AccountCreditLedgerEntry,
): FormattedCreditLedgerEntry {
  const delta = Number.isFinite(entry.delta) ? entry.delta : 0;
  const deltaLabel = `${delta > 0 ? "+" : ""}${delta} 次`;
  const balanceLabel = `扣后余额 ${entry.balance_after} 次`;
  const reason = entry.reason?.trim();

  if (entry.kind === "free_grant") {
    return {
      title: "免费赠送",
      description: reason || "账号初始化赠送额度",
      deltaLabel,
      balanceLabel,
      tone: "positive",
    };
  }

  if (entry.kind === "session_debit") {
    return {
      title: "开始平台托管面试",
      description: entry.session_id
        ? `面试 ${entry.session_id.slice(0, 8)} 已扣减`
        : reason || "平台托管模式开始面试",
      deltaLabel,
      balanceLabel,
      tone: "negative",
    };
  }

  if (entry.kind === "session_refund") {
    return {
      title: "面试扣减退回",
      description: reason || "面试开始前失败，已退回平台次数",
      deltaLabel,
      balanceLabel,
      tone: "positive",
    };
  }

  if (entry.kind === "admin_adjustment") {
    return {
      title: "管理员调整",
      description: reason || entry.admin_note || "管理员手动调整额度",
      deltaLabel,
      balanceLabel,
      tone: delta >= 0 ? "positive" : "negative",
    };
  }

  return {
    title: "额度变动",
    description: reason || entry.kind,
    deltaLabel,
    balanceLabel,
    tone: delta > 0 ? "positive" : delta < 0 ? "negative" : "neutral",
  };
}

export function getCreditStartGateState({
  policy,
  auth,
  creditBalance,
  isByok,
}: {
  policy: CreditPolicyForGate | null;
  auth: CreditAuthForGate;
  creditBalance: number | null;
  isByok: boolean;
}): CreditStartGateState {
  if (isByok) {
    return {
      usesPlatformCredits: false,
      disabled: false,
      notice: "使用个人 API Key：不扣平台次数，但会消耗你自己的模型服务额度。",
      ctaLabel: "个人 Key 模式",
    };
  }

  if (!policy?.enforced) {
    return {
      usesPlatformCredits: false,
      disabled: false,
      notice: null,
      ctaLabel: null,
    };
  }

  if (auth.loading) {
    return {
      usesPlatformCredits: true,
      disabled: true,
      notice: "正在确认登录状态，请稍后再开始平台托管面试。",
      ctaLabel: "正在确认账号",
    };
  }

  if (!auth.authenticated) {
    return {
      usesPlatformCredits: true,
      disabled: true,
      notice: "登录领取免费次数后即可使用平台托管模型；也可以在 API 设置里使用个人 Key。",
      ctaLabel: "登录领取免费次数",
    };
  }

  if (creditBalance === null) {
    return {
      usesPlatformCredits: true,
      disabled: true,
      notice: "正在同步账号额度，请稍后再开始平台托管面试。",
      ctaLabel: "正在同步账号额度",
    };
  }

  if (creditBalance <= 0) {
    return {
      usesPlatformCredits: true,
      disabled: true,
      notice: "次数不足：可以使用个人 API Key，或联系管理员补充次数。",
      ctaLabel: "次数不足",
    };
  }

  return {
    usesPlatformCredits: true,
    disabled: false,
    notice: `本次将消耗 1 次平台面试次数。当前剩余 ${creditBalance} 次，开始后剩余 ${creditBalance - 1} 次。`,
    ctaLabel: "本次消耗 1 次",
  };
}
