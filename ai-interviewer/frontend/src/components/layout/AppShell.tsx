"use client";

import { usePathname } from "next/navigation";
import {
  Activity,
  ArrowLeft,
  Gauge,
  History,
  Home,
  Key,
  Menu,
  Moon,
  Plus,
  Sun,
  X,
} from "lucide-react";
import { useEffect, useState } from "react";
import { useTheme } from "next-themes";
import { AnimatePresence, motion } from "framer-motion";

import { cn } from "@/lib/utils";
import { PendingNavigationLink } from "@/components/navigation/PendingNavigationLink";
import { Button } from "@/components/ui/button";
import { LLMSettingsDialog } from "@/components/layout/LLMSettingsDialog";
import { LightScrollWheel } from "@/components/layout/LightScrollWheel";
import {
  getLLMConfigStatus,
  LLM_CONFIG_EVENT,
  loadLLMConfig,
  loadLLMTestStatus,
  type LLMConfigStatus,
} from "@/lib/llm-config";

function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  if (!mounted) return <div className="h-8 w-8" />;

  return (
    <Button
      variant="ghost"
      size="icon"
      className="h-8 w-8"
      onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}
      aria-label="切换主题"
    >
      {resolvedTheme === "dark" ? (
        <Sun className="h-4 w-4" />
      ) : (
        <Moon className="h-4 w-4" />
      )}
    </Button>
  );
}

function LLMStatusDot() {
  const [status, setStatus] = useState<LLMConfigStatus>("missing");

  useEffect(() => {
    function refresh() {
      setStatus(getLLMConfigStatus(loadLLMConfig(), loadLLMTestStatus()));
    }
    refresh();
    window.addEventListener(LLM_CONFIG_EVENT, refresh);
    window.addEventListener("storage", refresh);
    return () => {
      window.removeEventListener(LLM_CONFIG_EVENT, refresh);
      window.removeEventListener("storage", refresh);
    };
  }, []);

  const isFailure =
    status !== "missing" && status !== "untested" && status !== "success";
  const color =
    status === "success"
      ? "bg-emerald-400"
      : isFailure
        ? "bg-destructive"
        : status === "untested"
          ? "bg-amber-400"
          : "bg-muted-foreground/50";
  const label = llmStatusLabel(status);

  return (
    <span
      className={cn(
        "absolute -right-0.5 -top-0.5 h-2.5 w-2.5 rounded-full border border-background",
        color,
      )}
      aria-label={label}
    />
  );
}

function llmStatusLabel(status: LLMConfigStatus): string {
  switch (status) {
    case "success":
      return "API 已测试通过";
    case "auth_failed":
      return "保存的 API 密钥可能已失效";
    case "quota_exhausted":
      return "API 额度不足或余额耗尽";
    case "rate_limited":
      return "API 暂时被限流";
    case "transient":
      return "API 服务或网络暂时不稳定";
    case "misconfig":
      return "API 模型或 Base URL 配置有误";
    case "error":
      return "API 测试失败";
    case "untested":
      return "API 已配置，尚未测试";
    case "missing":
    default:
      return "未配置 API";
  }
}

function resolveParentHref(pathname: string | null): string | null {
  if (!pathname || pathname === "/") return null;
  const segments = pathname.split("/").filter(Boolean);
  if (segments.length === 0) return null;

  if (
    segments[0] === "interview" &&
    segments.length >= 3 &&
    segments[2] === "report"
  ) {
    return "/interview/history";
  }

  const parent = `/${segments.slice(0, -1).join("/")}`;
  if (!parent || parent === "/interview") return "/";
  return parent;
}

function NavigationShortcuts({ pathname }: { pathname: string | null }) {
  if (pathname === "/") return null;
  const parentHref = resolveParentHref(pathname);

  return (
    <div className="sticky top-16 z-20 border-b bg-background/90 backdrop-blur-xl supports-[backdrop-filter]:bg-background/75">
      <div className="container flex h-10 items-center gap-2 text-xs">
        {parentHref && parentHref !== "/" && (
          <Button asChild variant="ghost" size="sm" className="h-7 gap-1.5 px-2">
            <PendingNavigationLink href={parentHref} pendingLabel="返回中...">
              <ArrowLeft className="h-3.5 w-3.5" />
              返回上一级
            </PendingNavigationLink>
          </Button>
        )}
        <Button asChild variant="ghost" size="sm" className="h-7 gap-1.5 px-2">
          <PendingNavigationLink href="/" pendingLabel="返回中...">
            <Home className="h-3.5 w-3.5" />
            回到首页
          </PendingNavigationLink>
        </Button>
      </div>
    </div>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [mobileOpen, setMobileOpen] = useState(false);
  const showAdminNav = process.env.NEXT_PUBLIC_ADMIN_NAV_ENABLED === "true";

  return (
    <div className="flex min-h-dvh flex-col">
      <header className="sticky top-0 z-30 border-b bg-background/80 backdrop-blur-xl supports-[backdrop-filter]:bg-background/60">
        <div className="container flex h-16 items-center justify-between">
          <PendingNavigationLink href="/" className="flex items-center gap-2 font-semibold">
            <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-emerald-500/10">
              <Activity className="h-4 w-4 text-emerald-400" />
            </div>
            <span>AI 面试官</span>
            <span className="hidden rounded-full bg-emerald-500/10 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-emerald-400 sm:inline">
              预览版
            </span>
          </PendingNavigationLink>

          {/* Desktop nav */}
          <nav className="hidden items-center gap-4 sm:flex">
            <PendingNavigationLink
              href="/interview/history"
              pendingLabel="打开中..."
              className={cn(
                "flex items-center gap-2.5 rounded-xl px-5 py-2.5 text-[15px] font-medium transition-colors",
                pathname === "/interview/history"
                  ? "bg-secondary text-foreground"
                  : "text-muted-foreground hover:bg-accent hover:text-accent-foreground",
              )}
            >
              <History className="h-[18px] w-[18px]" />
              我的面试
            </PendingNavigationLink>
            <PendingNavigationLink
              href="/interview/setup"
              pendingLabel="打开中..."
              className="flex items-center gap-2.5 rounded-xl bg-emerald-600 px-6 py-2.5 text-[15px] font-semibold text-white shadow-sm transition-colors hover:bg-emerald-500"
            >
              <Plus className="h-[18px] w-[18px]" />
              新面试
            </PendingNavigationLink>
            <span className="mx-1 h-6 w-px bg-border" />
            <LLMSettingsDialog>
              <button
                type="button"
                className="flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
                aria-label="配置 AI 模型的 API 密钥"
              >
                <span className="relative">
                  <Key className="h-4 w-4" />
                  <LLMStatusDot />
                </span>
                <span className="hidden lg:inline">API 设置</span>
              </button>
            </LLMSettingsDialog>
            {showAdminNav && (
              <PendingNavigationLink
                href="/admin"
                pendingLabel="打开中..."
                className={cn(
                  "flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm transition-colors",
                  pathname === "/admin"
                    ? "bg-secondary text-foreground"
                    : "text-muted-foreground hover:bg-accent hover:text-accent-foreground",
                )}
                aria-label="后台观测面板"
              >
                <Gauge className="h-4 w-4" />
                后台
              </PendingNavigationLink>
            )}
            <ThemeToggle />
          </nav>

          {/* Mobile menu button */}
          <Button
            variant="ghost"
            size="icon"
            className="sm:hidden"
            onClick={() => setMobileOpen(!mobileOpen)}
          >
            {mobileOpen ? <X className="h-4 w-4" /> : <Menu className="h-4 w-4" />}
          </Button>
        </div>

        {/* Mobile nav */}
        <AnimatePresence>
          {mobileOpen && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.2 }}
              className="overflow-hidden border-t sm:hidden"
            >
              <nav className="container flex flex-col gap-2 py-4">
                <PendingNavigationLink
                  href="/interview/setup"
                  onClick={() => setMobileOpen(false)}
                  pendingLabel="打开中..."
                  className="flex items-center gap-2 rounded-lg bg-emerald-600 px-4 py-3 text-base font-medium text-white transition-colors hover:bg-emerald-500"
                >
                  <Plus className="h-5 w-5" />
                  新面试
                </PendingNavigationLink>
                <PendingNavigationLink
                  href="/interview/history"
                  onClick={() => setMobileOpen(false)}
                  pendingLabel="打开中..."
                  className={cn(
                    "flex items-center gap-2 rounded-lg px-4 py-3 text-base font-medium transition-colors",
                    pathname === "/interview/history"
                      ? "bg-secondary text-foreground"
                      : "text-muted-foreground hover:bg-accent hover:text-accent-foreground",
                  )}
                >
                  <History className="h-5 w-5" />
                  我的面试
                </PendingNavigationLink>
                {showAdminNav && (
                  <PendingNavigationLink
                    href="/admin"
                    onClick={() => setMobileOpen(false)}
                    pendingLabel="打开中..."
                    className={cn(
                      "flex items-center gap-2 rounded-lg px-4 py-2.5 text-sm transition-colors",
                      pathname === "/admin"
                        ? "bg-secondary text-foreground"
                        : "text-muted-foreground hover:bg-accent hover:text-accent-foreground",
                    )}
                  >
                    <Gauge className="h-4 w-4" />
                    后台观测
                  </PendingNavigationLink>
                )}
                <LLMSettingsDialog>
                  <button
                    type="button"
                    onClick={() => setMobileOpen(false)}
                    className="flex items-center gap-2 rounded-lg px-4 py-2.5 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
                  >
                    <span className="relative">
                      <Key className="h-4 w-4" />
                      <LLMStatusDot />
                    </span>
                    API 设置
                  </button>
                </LLMSettingsDialog>
              </nav>
            </motion.div>
          )}
        </AnimatePresence>
      </header>
      <NavigationShortcuts pathname={pathname} />
      {children}
      <LightScrollWheel />
    </div>
  );
}
