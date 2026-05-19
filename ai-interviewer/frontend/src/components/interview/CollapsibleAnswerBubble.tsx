"use client";

import { useId, useState } from "react";
import { Maximize2, Minimize2 } from "lucide-react";
import { motion } from "framer-motion";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const ANSWER_COLLAPSE_CHAR_LIMIT = 900;
const ANSWER_COLLAPSE_LINE_LIMIT = 12;

type CollapsibleAnswerBubbleProps = {
  text: string;
  contentId?: string;
  className?: string;
  label?: string;
};

export function CollapsibleAnswerBubble({
  text,
  contentId,
  className,
  label = "你",
}: CollapsibleAnswerBubbleProps) {
  const generatedId = useId();
  const [answerExpanded, setAnswerExpanded] = useState(false);
  const answerLineCount = text.split(/\r?\n/).length;
  const shouldCollapseAnswer =
    text.length > ANSWER_COLLAPSE_CHAR_LIMIT ||
    answerLineCount > ANSWER_COLLAPSE_LINE_LIMIT;
  const resolvedContentId = contentId ?? `answer-content-${generatedId}`;

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className={cn(
        "rounded-lg border border-primary/10 bg-primary/[0.03] p-4 text-sm leading-relaxed",
        className,
      )}
    >
      <div className="mb-1.5 flex items-center gap-1.5">
        <span className="flex h-5 w-5 items-center justify-center rounded bg-primary/10 font-mono text-[10px] font-bold text-primary">
          A
        </span>
        <span className="font-mono text-[10px] text-muted-foreground">
          {label}
        </span>
      </div>
      <div
        id={resolvedContentId}
        className={cn(
          "whitespace-pre-wrap",
          shouldCollapseAnswer &&
            !answerExpanded &&
            "max-h-72 overflow-hidden [mask-image:linear-gradient(to_bottom,black_75%,transparent)]",
        )}
      >
        {text}
      </div>
      {shouldCollapseAnswer && (
        <div className="mt-3 flex justify-end border-t border-primary/5 pt-2">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            aria-controls={resolvedContentId}
            aria-expanded={answerExpanded}
            onClick={() => setAnswerExpanded((value) => !value)}
            className="h-6 gap-1 rounded-md bg-emerald-500/[0.03] px-1.5 text-[11px] font-normal text-emerald-300/60 transition-colors hover:bg-emerald-500/[0.06] hover:text-emerald-200/80"
          >
            {answerExpanded ? (
              <Minimize2 className="h-3 w-3 opacity-70" />
            ) : (
              <Maximize2 className="h-3 w-3 opacity-70" />
            )}
            {answerExpanded ? "收起" : "展开"}
          </Button>
        </div>
      )}
    </motion.div>
  );
}
