import type { Metadata } from "next";
import { ThemeProvider } from "next-themes";

import { AppShell } from "@/components/layout/AppShell";
import { Footer } from "@/components/layout/Footer";
import { Toaster } from "@/components/ui/toaster";

import "./globals.css";

export const metadata: Metadata = {
  title: "AI 面试官",
  description:
    "面向求职者的 AI 面试练习工具，提供模拟问答、能力评估和个性化提升建议。",
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
          <AppShell>
            <main className="flex-1">{children}</main>
            <Footer />
          </AppShell>
          <Toaster />
        </ThemeProvider>
      </body>
    </html>
  );
}
