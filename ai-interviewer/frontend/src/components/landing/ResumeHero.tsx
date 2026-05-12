"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ArrowRight, History } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";

import { Button } from "@/components/ui/button";
import {
  getMostRecentRunning,
  getHistory,
  type InterviewHistoryEntry,
} from "@/lib/storage/interviewHistory";
import {
  getMostRecentSetupDraft,
  type SetupDraft,
} from "@/lib/storage/setupDrafts";

export function ResumeHero() {
  const [running, setRunning] = useState<InterviewHistoryEntry | null>(null);
  const [setupDraft, setSetupDraft] = useState<SetupDraft | null>(null);
  const [totalCount, setTotalCount] = useState(0);

  useEffect(() => {
    setRunning(getMostRecentRunning());
    setSetupDraft(getMostRecentSetupDraft());
    setTotalCount(getHistory().length);
  }, []);

  const showSetupDraft =
    setupDraft !== null &&
    (!running || setupDraft.updatedAt >= running.lastVisitedAt);
  const showResume = !showSetupDraft && running !== null;
  const showHistoryOnly = !showSetupDraft && !running && totalCount > 0;

  return (
    <AnimatePresence>
      {showSetupDraft && setupDraft && (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0 }}
          transition={{ delay: 0.5, duration: 0.3 }}
          className="mt-3 flex flex-wrap items-center gap-3 rounded-lg border border-emerald-500/15 bg-white/45 px-4 py-2.5 text-sm shadow-sm shadow-emerald-900/[0.03] backdrop-blur-sm dark:bg-card/30"
        >
          <History className="h-4 w-4 text-emerald-400" />
          <span className="text-muted-foreground">
            你有一份 <span className="text-foreground">“{setupDraft.filename}”</span> 准备中的面试信息。
          </span>
          <Button asChild variant="link" className="h-auto gap-1 px-0 text-emerald-400">
            <Link href={`/interview/setup?draft_id=${encodeURIComponent(setupDraft.draftId)}`}>
              继续完善
              <ArrowRight className="h-3 w-3" />
            </Link>
          </Button>
        </motion.div>
      )}
      {showResume && (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0 }}
          transition={{ delay: 0.5, duration: 0.3 }}
          className="mt-3 flex flex-wrap items-center gap-3 rounded-lg border border-emerald-500/15 bg-white/45 px-4 py-2.5 text-sm shadow-sm shadow-emerald-900/[0.03] backdrop-blur-sm dark:bg-card/30"
        >
          <History className="h-4 w-4 text-emerald-400" />
          <span className="text-muted-foreground">
            你有一场<span className="text-foreground">「{running.jdTitle}」</span>面试还没答完。
          </span>
          <Button asChild variant="link" className="h-auto gap-1 px-0 text-emerald-400">
            <Link href={`/interview/${running.sessionId}`}>
              接着练
              <ArrowRight className="h-3 w-3" />
            </Link>
          </Button>
          {totalCount > 1 && (
            <>
              <span className="mx-1 hidden text-muted-foreground/40 sm:inline">·</span>
              <Button
                asChild
                variant="link"
                className="h-auto gap-1 px-0 text-muted-foreground hover:text-foreground"
              >
                <Link href="/interview/history">
                  查看全部 {totalCount} 场
                </Link>
              </Button>
            </>
          )}
        </motion.div>
      )}
      {showHistoryOnly && (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0 }}
          transition={{ delay: 0.5, duration: 0.3 }}
          className="mt-3 flex items-center gap-3 rounded-lg border bg-white/45 px-4 py-2.5 text-sm shadow-sm shadow-emerald-900/[0.03] backdrop-blur-sm dark:bg-card/30"
        >
          <History className="h-4 w-4 text-muted-foreground" />
          <span className="text-muted-foreground">
            你已经练习过 {totalCount} 场面试。
          </span>
          <Button asChild variant="link" className="h-auto gap-1 px-0">
            <Link href="/interview/history">
              查看记录
              <ArrowRight className="h-3 w-3" />
            </Link>
          </Button>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
