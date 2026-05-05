import { Badge } from "@/components/ui/badge";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

/**
 * Shared badge that surfaces whether the training plan came from the
 * AI review path or from the deterministic fallback aggregator.
 *
 * Mounted in two places:
 * - Report page's `TrainingPlanCard` (full review plan + diagnosis)
 * - Replay page's `TrainingPlanCard` (compact "后续训练建议")
 *
 * Returns ``null`` when the source is unknown so the call site can
 * keep the same JSX shape regardless of whether the backend supplied
 * the field — important for older `final_report` rows that pre-date
 * `training_plan_attached`.
 *
 * **A11y note:** the explanation is exposed through the shared Radix
 * Tooltip wrapper rather than native ``title`` so keyboard and screen
 * reader users get the same affordance as mouse users.
 */
const LLM_SOURCE_DESCRIPTION =
  "由 AI 复盘链路从你的回答中提炼";
const FALLBACK_SOURCE_DESCRIPTION =
  "AI 复盘链路暂不可用，已根据评分聚合生成";

export function TrainingPlanSourceBadge({
  source,
}: {
  source: string | undefined;
}) {
  if (source === "llm") {
    return (
      <SourceTooltipBadge
        label="AI 复盘"
        description={LLM_SOURCE_DESCRIPTION}
        className="ml-1 border-emerald-500/40 bg-emerald-500/10 text-[10px] text-emerald-300"
      />
    );
  }
  if (source === "fallback") {
    return (
      <SourceTooltipBadge
        label="系统聚合"
        description={FALLBACK_SOURCE_DESCRIPTION}
        className="ml-1 border-amber-500/40 bg-amber-500/10 text-[10px] text-amber-200"
      />
    );
  }
  return null;
}

function SourceTooltipBadge({
  label,
  description,
  className,
}: {
  label: string;
  description: string;
  className: string;
}) {
  return (
    <TooltipProvider delayDuration={150}>
      <Tooltip>
        <TooltipTrigger asChild>
          <Badge
            variant="outline"
            className={className}
            aria-label={`${label} · ${description}`}
            tabIndex={0}
          >
            {label}
          </Badge>
        </TooltipTrigger>
        <TooltipContent>
          <p>{description}</p>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
