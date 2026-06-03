"use client";

import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { KeyRound, Loader2, ShieldCheck } from "lucide-react";

import { AdminPanel } from "@/components/admin/AdminPanel";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { loadAdminToken, saveAdminToken, validateAdminAccess } from "@/lib/api/admin";
import { useAuth } from "@/lib/auth/useAuth";

export function AdminAccessGate({ children }: { children?: ReactNode }) {
  const auth = useAuth();
  const [tokenUnlocked, setTokenUnlocked] = useState(false);
  const [tokenInput, setTokenInput] = useState("");
  const [validatingToken, setValidatingToken] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const token = loadAdminToken();
    setTokenInput(token);
  }, []);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const token = tokenInput.trim();
    if (!token) {
      setError("请输入后台认证令牌");
      return;
    }
    setValidatingToken(true);
    try {
      await validateAdminAccess(token);
      saveAdminToken(token);
      setError(null);
      setTokenUnlocked(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "后台认证令牌验证失败");
    } finally {
      setValidatingToken(false);
    }
  }

  const protectedContent = children ?? <AdminPanel />;

  if (!auth.loading && auth.user?.role === "admin") {
    return <>{protectedContent}</>;
  }

  if (tokenUnlocked) {
    return <>{protectedContent}</>;
  }

  return (
    <Card className="border-emerald-500/20 bg-emerald-500/[0.03]">
      <CardContent className="space-y-5 p-5">
        <div className="flex items-start gap-3">
          <div className="rounded-lg border border-emerald-500/20 bg-emerald-500/10 p-2 text-emerald-300">
            <ShieldCheck className="h-5 w-5" />
          </div>
          <div className="space-y-1">
            <h2 className="text-base font-semibold">管理员权限</h2>
            <p className="text-sm leading-6 text-muted-foreground">
              后台观测台需要 admin 账号登录。普通账号不会自动获得后台权限；
              如需 bootstrap 或本地开发调试，也可以输入 API_TOKEN 解锁。
            </p>
            {!auth.loading && auth.authenticated && auth.user?.role !== "admin" && (
              <p className="text-xs text-amber-300">
                当前账号不是管理员，请切换到 admin 账号或使用运维 token。
              </p>
            )}
            {!auth.loading && !auth.authenticated && (
              <p className="text-xs text-muted-foreground">
                未登录时只能使用 API_TOKEN fallback；产品化入口请先登录管理员账号。
              </p>
            )}
          </div>
        </div>

        <form className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto]" onSubmit={handleSubmit}>
          <label className="grid gap-2">
            <span className="text-xs font-medium text-muted-foreground">
              管理员认证令牌
            </span>
            <Input
              type="password"
              value={tokenInput}
              onChange={(event) => {
                setTokenInput(event.target.value);
                setError(null);
              }}
              placeholder="输入 API_TOKEN 或本地 dev 标记"
              autoComplete="off"
            />
          </label>
          <Button
            type="submit"
            className="gap-1.5 bg-emerald-600 text-white hover:bg-emerald-500 sm:self-end"
            disabled={validatingToken}
          >
            {validatingToken ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <KeyRound className="h-4 w-4" />
            )}
            {validatingToken ? "验证中" : "解锁"}
          </Button>
        </form>

        {error && <p className="text-sm text-destructive">{error}</p>}
      </CardContent>
    </Card>
  );
}
