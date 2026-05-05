import type { JobSpec } from "@/lib/api/types";

export interface JobLevelOption {
  value: JobSpec["level"];
  shortLabel: string;
  fullLabel: string;
}

export const JOB_LEVEL_OPTIONS: readonly JobLevelOption[] = [
  { value: "junior", shortLabel: "初级", fullLabel: "初级" },
  { value: "mid", shortLabel: "中级", fullLabel: "中级" },
  { value: "senior", shortLabel: "高级", fullLabel: "高级" },
  { value: "staff", shortLabel: "资深", fullLabel: "Staff / 技术专家" },
  { value: "principal", shortLabel: "首席", fullLabel: "Principal / 资深专家" },
] as const;

export function jobLevelShortLabel(level: string): string {
  return (
    JOB_LEVEL_OPTIONS.find((o) => o.value === level)?.shortLabel ?? level
  );
}

export function jobLevelFullLabel(level: string): string {
  return (
    JOB_LEVEL_OPTIONS.find((o) => o.value === level)?.fullLabel ?? level
  );
}
