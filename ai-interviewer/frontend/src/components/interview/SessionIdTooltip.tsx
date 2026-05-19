"use client";

import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

export function SessionIdTooltip({ sessionId }: { sessionId: string }) {
  return (
    <TooltipProvider delayDuration={150}>
      <Tooltip>
        <TooltipTrigger asChild>
          <span
            tabIndex={0}
            aria-label={`完整 Session ID：${sessionId}`}
            className="inline-flex max-w-full cursor-default rounded-sm font-mono outline-none ring-emerald-400/40 transition-colors hover:text-foreground focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-offset-background"
          >
            {shortSessionId(sessionId)}
          </span>
        </TooltipTrigger>
        <TooltipContent
          side="bottom"
          align="start"
          sideOffset={6}
          className="max-w-[28rem] border-border/80 bg-popover px-2.5 py-1.5 font-mono text-xs text-emerald-300 shadow-lg"
        >
          <span className="break-all">{sessionId}</span>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

export function shortSessionId(id: string): string {
  if (id.length <= 12) return id;
  return `${id.slice(0, 4)}...${id.slice(-4)}`;
}
