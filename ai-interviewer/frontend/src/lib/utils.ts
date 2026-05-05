import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatTurn(turnIdx: number | null | undefined): string {
  if (turnIdx === null || turnIdx === undefined) return "-";
  return `T${turnIdx + 1}`;
}

export function truncate(text: string, max = 120): string {
  if (text.length <= max) return text;
  return text.slice(0, max - 1) + "…";
}

export function truncateId(value: string, threshold = 16): string {
  if (value.length <= threshold) return value;
  const prefix = Math.ceil(threshold / 3);
  const suffix = Math.floor(threshold / 3);
  return `${value.slice(0, prefix)}…${value.slice(-suffix)}`;
}

export function formatTimestamp(iso?: string | null): string {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "—";
    return d.toLocaleString("zh-CN", {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return iso;
  }
}
