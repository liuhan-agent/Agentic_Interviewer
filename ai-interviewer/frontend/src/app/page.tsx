"use client";

import { useRef } from "react";
import {
  ArrowRight,
  BarChart3,
  Brain,
  ChevronRight,
  Feather,
  GitBranch,
  RotateCcw,
  Sparkles,
  Zap,
} from "lucide-react";
import { motion, useInView } from "framer-motion";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { PendingNavigationLink } from "@/components/navigation/PendingNavigationLink";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { ResumeHero } from "@/components/landing/ResumeHero";

const stagger = {
  hidden: {},
  visible: { transition: { staggerChildren: 0.08 } },
};

const fadeUp = {
  hidden: { opacity: 0, y: 20 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.5, ease: "easeOut" } },
};

const scaleIn = {
  hidden: { opacity: 0, scale: 0.92 },
  visible: {
    opacity: 1,
    scale: 1,
    transition: { duration: 0.45, ease: "easeOut" },
  },
};

export default function LandingPage() {
  return (
    <>
      <HeroSection />
      <WorkflowSection />
      <ArchitectureSection />
      <CtaSection />
    </>
  );
}

function HeroSection() {
  return (
    <section className="relative isolate overflow-hidden border-b border-border/40">
      <div className="landing-hero-image absolute inset-0 bg-cover bg-no-repeat opacity-[0.64] dark:opacity-[0.72] md:opacity-[0.78] md:dark:opacity-[0.82]" />
      <div className="absolute inset-0 bg-gradient-to-r from-background via-background/90 to-background/60 dark:via-background/90 dark:to-background/50 md:via-background/82 md:to-background/18 md:dark:via-background/86 md:dark:to-background/24" />
      <div className="absolute inset-x-0 bottom-0 h-40 bg-gradient-to-b from-transparent to-background" />
      <div className="bg-grid absolute inset-0 opacity-[0.08] mask-fade-bottom" />
      <div className="absolute -top-36 left-1/3 h-[420px] w-[620px] rounded-full bg-emerald-500/[0.035] blur-[120px]" />

      <motion.div
        className="relative mx-auto grid w-full max-w-[1680px] gap-12 px-6 py-20 sm:px-8 md:min-h-[600px] md:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)] md:items-center md:px-14 md:py-24 lg:px-20 lg:py-28 xl:px-28 2xl:px-32"
        initial="hidden"
        animate="visible"
        variants={stagger}
      >
        <div className="flex max-w-[35rem] flex-col items-start gap-5">
          <motion.div variants={fadeUp}>
            <Badge
              variant="outline"
              className="rounded-full border-emerald-500/30 px-3.5 py-1.5 text-xs backdrop-blur-sm"
            >
              <Sparkles className="mr-1.5 h-3 w-3 text-emerald-400" />
              问镜 · AI 模拟面试与复盘训练
            </Badge>
          </motion.div>

          <motion.h1
            variants={fadeUp}
            className="max-w-[18rem] text-balance text-4xl font-semibold leading-[1.08] tracking-tight sm:max-w-none md:text-5xl lg:text-[56px]"
          >
            会追问、会评分、会<span className="gradient-text">复盘</span>的 AI 面试陪练
          </motion.h1>

          <motion.p
            variants={fadeUp}
            className="max-w-[32rem] text-balance text-base leading-8 text-slate-600 md:text-lg dark:text-muted-foreground"
          >
            问镜会根据岗位需求和你的背景生成问题，在作答后即时评估，
            并围绕薄弱点继续追问。面试结束后，生成报告和下一场训练建议。
          </motion.p>

          <motion.div
            variants={fadeUp}
            className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground"
            aria-label="覆盖岗位大类"
          >
            <span className="text-foreground/80">覆盖方向：</span>
            {["互联网技术", "产品 / 运营", "销售 / 市场", "职能 / 服务", "管理"].map((label) => (
              <Badge
                key={label}
                variant="secondary"
                className="rounded-full border border-border/60 bg-secondary/40 px-2.5 py-0.5 text-[11px] font-normal"
              >
                {label}
              </Badge>
            ))}
          </motion.div>

          <motion.p
            variants={fadeUp}
            className="max-w-[32rem] text-[11px] leading-relaxed text-muted-foreground/75"
          >
            互联网技术方向的题库密度更高；其他方向以通用面试探查为主，仍能拿到分维度反馈与训练计划。
          </motion.p>

          <motion.div variants={fadeUp} className="flex flex-wrap gap-3 pt-2">
            <Button asChild size="lg" className="group glow-emerald-sm bg-emerald-600 hover:bg-emerald-500 text-white">
              <PendingNavigationLink href="/interview/setup" pendingLabel="打开中…">
                开始面试
                <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
              </PendingNavigationLink>
            </Button>
            <Button asChild size="lg" variant="outline" className="group">
              <a href="#features">
                了解更多
                <ChevronRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
              </a>
            </Button>
          </motion.div>

          <motion.div variants={fadeUp}>
            <ResumeHero />
          </motion.div>
        </div>

        <div aria-hidden className="hidden md:block" />
      </motion.div>
    </section>
  );
}

function WorkflowSection() {
  const ref = useRef(null);
  const inView = useInView(ref, { once: true, margin: "-80px" });

  const steps = [
    { icon: <Zap className="h-4 w-4" />, label: "建档定位", color: "text-blue-400" },
    { icon: <Brain className="h-4 w-4" />, label: "规划出题", color: "text-purple-400" },
    { icon: <Sparkles className="h-4 w-4" />, label: "作答采样", color: "text-emerald-400" },
    { icon: <BarChart3 className="h-4 w-4" />, label: "评分验证", color: "text-amber-400" },
    { icon: <GitBranch className="h-4 w-4" />, label: "路由追问", color: "text-rose-400" },
    { icon: <Feather className="h-4 w-4" />, label: "报告复盘", color: "text-cyan-400" },
  ];

  return (
    <section className="border-y border-border/50 bg-secondary/30">
      <div ref={ref} className="container py-16">
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={inView ? { opacity: 1, y: 0 } : {}}
          transition={{ duration: 0.4 }}
          className="mb-8 text-center"
        >
          <p className="mb-2 font-mono text-xs uppercase tracking-widest text-emerald-400">
            一场练习是怎么走的
          </p>
          <h2 className="text-xl font-semibold tracking-tight md:text-2xl">
            从目标岗位到复盘报告，一条主链路跑到底
          </h2>
          <p className="mx-auto mt-3 max-w-2xl text-sm leading-relaxed text-muted-foreground">
            每一步都对应后端面试主链路 workflow 节点：生成问题、评估回答、验证结果、决定追问或收束，最后沉淀成可回放的训练记录。
          </p>
        </motion.div>

        <div className="flex flex-wrap items-center justify-center gap-2 md:gap-0">
          {steps.map((step, i) => (
            <motion.div
              key={step.label}
              initial={{ opacity: 0, scale: 0.85 }}
              animate={inView ? { opacity: 1, scale: 1 } : {}}
              transition={{ delay: i * 0.08, duration: 0.35 }}
              className="flex items-center"
            >
              <div className="flex items-center gap-2 rounded-full border bg-card px-4 py-2 text-sm">
                <span className={step.color}>{step.icon}</span>
                <span className="font-medium">{step.label}</span>
              </div>
              {i < steps.length - 1 && (
                <ChevronRight className="mx-1 hidden h-4 w-4 text-muted-foreground/50 md:block" />
              )}
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  );
}

function ArchitectureSection() {
  const ref = useRef(null);
  const inView = useInView(ref, { once: true, margin: "-60px" });

  const features = [
    {
      icon: <Brain className="h-5 w-5" />,
      title: "简历/JD 驱动出题",
      desc: "结合目标岗位、背景材料和题库策略，生成贴近真实面试的首问与后续问题。",
    },
    {
      icon: <BarChart3 className="h-5 w-5" />,
      title: "每轮即时评分",
      desc: "作答后按维度记录评分、强项、短板和本轮反馈，报告结果可追溯。",
    },
    {
      icon: <GitBranch className="h-5 w-5" />,
      title: "薄弱点触发追问",
      desc: "路由节点会根据评分和验证结果，决定继续追问、切换维度或收束本轮。",
    },
    {
      icon: <RotateCcw className="h-5 w-5" />,
      title: "训练回放与恢复",
      desc: "会话进度、历史记录和报告可继续访问，断点恢复不打断练习链路。",
    },
    {
      icon: <Feather className="h-5 w-5" />,
      title: "结构化复盘报告",
      desc: "结束后汇总总体评分、维度表现、改进建议和下一场训练计划。",
    },
    {
      icon: <Sparkles className="h-5 w-5" />,
      title: "Trace 观测 workflow",
      desc: "后台可查看节点耗时、路由决策和证据来源，便于调试 agentic 链路。",
    },
  ];

  return (
    <section id="features" className="container scroll-mt-24 py-24" ref={ref}>
      <motion.div
        initial="hidden"
        animate={inView ? "visible" : "hidden"}
        variants={stagger}
      >
        <motion.div variants={fadeUp} className="mb-12">
          <p className="mb-2 font-mono text-xs uppercase tracking-widest text-emerald-400">
            Agentic workflow
          </p>
          <h2 className="mb-3 text-2xl font-semibold tracking-tight md:text-3xl">
            把一次模拟面试拆成可观测、可恢复的主链路
          </h2>
          <p className="max-w-2xl text-sm leading-relaxed text-muted-foreground">
            问镜不是单轮聊天工具，而是把出题、作答、评分、验证、追问和复盘拆成可追踪节点，
            围绕追问评分复盘持续校准训练方向，
            让用户拿到训练反馈，也让开发者能看清 agentic 链路如何运转。
          </p>
        </motion.div>

        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {features.map((f) => (
            <motion.div key={f.title} variants={scaleIn}>
              <Card className="card-hover h-full">
                <CardHeader>
                  <div className="flex items-center gap-2.5 text-emerald-400">
                    <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-500/10">
                      {f.icon}
                    </div>
                    <CardTitle className="text-base">{f.title}</CardTitle>
                  </div>
                  <CardDescription className="pt-1 leading-relaxed">
                    {f.desc}
                  </CardDescription>
                </CardHeader>
                <CardContent />
              </Card>
            </motion.div>
          ))}
        </div>
      </motion.div>
    </section>
  );
}

function CtaSection() {
  const ref = useRef(null);
  const inView = useInView(ref, { once: true, margin: "-60px" });

  return (
    <section ref={ref} className="border-t">
      <motion.div
        className="container flex flex-col items-center gap-6 py-24 text-center"
        initial={{ opacity: 0, y: 20 }}
        animate={inView ? { opacity: 1, y: 0 } : {}}
        transition={{ duration: 0.5 }}
      >
        <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-emerald-500/10 text-emerald-400">
          <Sparkles className="h-6 w-6" />
        </div>
        <h2 className="max-w-lg text-2xl font-semibold tracking-tight md:text-3xl">
          来场练习吧
        </h2>
        <p className="max-w-md text-sm text-muted-foreground">
          告诉问镜你的背景和目标岗位，几分钟之后就能开始作答。
          按你的节奏来，没有任何压力。
        </p>
        <Button asChild size="lg" className="group glow-emerald-sm bg-emerald-600 hover:bg-emerald-500 text-white">
          <PendingNavigationLink href="/interview/setup" pendingLabel="打开中…">
            立即开始
            <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
          </PendingNavigationLink>
        </Button>
      </motion.div>
    </section>
  );
}
