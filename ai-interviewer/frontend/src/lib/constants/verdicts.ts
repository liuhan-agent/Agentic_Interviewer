export interface VerdictOption {
  value: string;
  shortLabel: string;
}

export const VERDICT_OPTIONS: readonly VerdictOption[] = [
  { value: "excellent", shortLabel: "表现优秀" },
  { value: "target_met", shortLabel: "达到目标水平" },
  { value: "near_target", shortLabel: "接近达标" },
  { value: "needs_focus", shortLabel: "重点补齐" },
] as const;

const LEGACY_VERDICT_LABELS: Record<string, string> = {
  strong_pass: "表现优秀",
  pass: "达到目标水平",
  borderline: "接近达标",
  fail: "重点补齐",
  strong_hire: "表现优秀",
  hire: "达到目标水平",
  lean_hire: "接近达标",
  lean_no_hire: "重点补齐",
  no_hire: "重点补齐",
  cancelled: "已取消",
};

export function verdictShortLabel(verdict: string): string {
  const key = verdict.toLowerCase();
  return (
    VERDICT_OPTIONS.find(
      (o) => o.value === key,
    )?.shortLabel ?? LEGACY_VERDICT_LABELS[key] ?? verdict.replace(/_/g, " ")
  );
}
