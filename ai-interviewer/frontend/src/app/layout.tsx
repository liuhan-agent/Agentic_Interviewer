import type { Metadata } from "next";
import { ThemeProvider } from "next-themes";

import { AppShell } from "@/components/layout/AppShell";
import { Footer } from "@/components/layout/Footer";
import { Toaster } from "@/components/ui/toaster";
import { AuthProvider } from "@/lib/auth/useAuth";

import "./globals.css";

export const metadata: Metadata = {
  title: "问镜 | AI 模拟面试与复盘训练",
  description:
    "问镜是一套面向求职者的 AI 模拟面试与复盘训练系统，提供模拟问答、追问评分、能力评估和个性化提升建议。",
  icons: {
    icon: [{ url: "/favicon.svg", type: "image/svg+xml" }],
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <body className="min-h-dvh antialiased">
        <ThemeProvider
          attribute="class"
          defaultTheme="dark"
          enableSystem={false}
          disableTransitionOnChange
        >
          <AuthProvider>
            <AppShell>
              <main id="app-main-content" className="flex-1">{children}</main>
              <Footer />
            </AppShell>
          </AuthProvider>
          <Toaster />
        </ThemeProvider>
      </body>
    </html>
  );
}
