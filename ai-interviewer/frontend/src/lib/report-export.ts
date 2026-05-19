import type { FinalReport, RubricScore } from "./api/types.ts";
import { formatDimensionName } from "./constants/interview.ts";

export interface ReportExportOptions {
  sessionId?: string;
}

type Diagnosis = {
  overall_readiness?: unknown;
  target_level_gap?: unknown;
  top_patterns?: unknown;
  evidence_refs?: unknown;
};

type PriorityWeakness = {
  dimension?: unknown;
  focus?: unknown;
  why_it_matters?: unknown;
  evidence?: unknown;
};

type PracticePlanItem = {
  task?: unknown;
  rationale?: unknown;
  estimated_hours?: unknown;
  steps?: unknown;
  success_criteria?: unknown;
};

const VERDICT_LABELS: Record<string, string> = {
  strong_pass: "表现优秀",
  pass: "达到目标水平",
  borderline: "接近达标",
  fail: "重点补齐",
  excellent: "表现优秀",
  target_met: "达到目标水平",
  near_target: "接近达标",
  needs_focus: "重点补齐",
  strong_hire: "表现优秀",
  hire: "达到目标水平",
  lean_hire: "接近达标",
  lean_no_hire: "重点补齐",
  no_hire: "重点补齐",
  cancelled: "已取消",
};

const FALLBACK_TRANSLATIONS: Record<string, string> = {
  "Evaluator LLM failed before returning a score. The interview continues with a conservative fallback rather than dropping the session.":
    "评估模型暂时不可用，已先使用保守评价保留本轮回答。",
  "Evaluator LLM unavailable; using conservative fallback.":
    "评估模型暂时不可用，已使用保守兜底评价。",
  "Evaluator LLM unavailable.": "评估模型暂时不可用。",
  "Addresses the most repeated evaluator weakness.":
    "针对本次面试中反复出现的待改进项。",
  "Demonstrate improvement via a mock re-interview.":
    "通过一次模拟复盘面试验证改进效果。",
  "Internalise learnings via a production-grade project.":
    "在一个接近真实生产场景的项目中巩固改进。",
  "Identify the most pressing weak dimension.":
    "先识别当前最需要补强的能力维度。",
};

export function formatReportSummary(
  report: FinalReport,
  options: ReportExportOptions = {},
): string {
  const lines: string[] = ["面试复盘摘要"];
  if (options.sessionId || report.session_id) {
    lines.push(`Session ID：${options.sessionId ?? report.session_id}`);
  }

  const verdict = reportVerdict(report);
  if (verdict) lines.push(`总评：${verdict}`);
  if (typeof report.overall_score === "number") {
    lines.push(`总分：${formatScore(report.overall_score)}/10`);
  }
  addLine(lines, "概览", report.summary);

  const diagnosis = getDiagnosis(report);
  addLine(lines, "能力诊断", diagnosis?.overall_readiness);
  addLine(lines, "目标差距", diagnosis?.target_level_gap);

  const weaknesses = getPriorityWeaknesses(report).slice(0, 3);
  if (weaknesses.length > 0) {
    lines.push("", "优先改进项：");
    weaknesses.forEach((item, index) => {
      const focus = text(item.focus);
      if (!focus) return;
      const why = text(item.why_it_matters);
      lines.push(`${index + 1}. ${translateReportText(focus)}${why ? `：${translateReportText(why)}` : ""}`);
    });
  }

  const practiceItems = getPracticePlan(report).slice(0, 3);
  if (practiceItems.length > 0) {
    lines.push("", "下一步训练建议：");
    practiceItems.forEach((item, index) => {
      const task = text(item.task);
      if (!task) return;
      const rationale = text(item.rationale);
      lines.push(`${index + 1}. ${translateReportText(task)}${rationale ? `：${translateReportText(rationale)}` : ""}`);
    });
  }

  return compactLines(lines).join("\n");
}

export function formatReportMarkdown(
  report: FinalReport,
  options: ReportExportOptions = {},
): string {
  const lines: string[] = ["# 面试复盘报告", ""];
  if (options.sessionId || report.session_id) {
    lines.push(`Session ID：\`${options.sessionId ?? report.session_id}\``, "");
  }

  lines.push("## 总评");
  const verdict = reportVerdict(report);
  if (verdict) lines.push(`- 总评：${verdict}`);
  if (typeof report.overall_score === "number") {
    lines.push(`- 总分：${formatScore(report.overall_score)}/10`);
  }
  addParagraph(lines, report.summary);

  addDimensionScores(lines, report);
  addDiagnosis(lines, report);
  addPriorityWeaknesses(lines, report);
  addPracticePlan(lines, report);
  addGoals(lines, report);

  return compactMarkdown(lines).join("\n");
}

function addDimensionScores(lines: string[], report: FinalReport) {
  const rows = Object.entries(report.dimension_scores ?? {})
    .map(([dimension, score]) => dimensionScoreRow(dimension, score))
    .filter((row): row is { dimension: string; score: string; rationale: string } => row !== null);

  if (rows.length === 0) return;
  lines.push("", "## 维度评分", "", "| 维度 | 得分 | 说明 |", "| --- | --- | --- |");
  for (const row of rows) {
    lines.push(
      `| ${escapeTableCell(row.dimension)} | ${escapeTableCell(row.score)} | ${escapeTableCell(row.rationale)} |`,
    );
  }
}

function addDiagnosis(lines: string[], report: FinalReport) {
  const diagnosis = getDiagnosis(report);
  if (!diagnosis) return;
  const readiness = text(diagnosis.overall_readiness);
  const gap = text(diagnosis.target_level_gap);
  const patterns = textList(diagnosis.top_patterns);
  const evidence = textList(diagnosis.evidence_refs);
  if (!readiness && !gap && patterns.length === 0 && evidence.length === 0) return;

  lines.push("", "## 能力诊断");
  addBullet(lines, "当前水平", readiness);
  addBullet(lines, "目标差距", gap);
  if (patterns.length > 0) {
    lines.push(`- 能力特征：${patterns.map(translateReportText).join("；")}`);
  }
  for (const item of evidence) {
    lines.push(`- 回答证据：${translateReportText(item)}`);
  }
}

function addPriorityWeaknesses(lines: string[], report: FinalReport) {
  const weaknesses = getPriorityWeaknesses(report);
  if (weaknesses.length === 0) return;
  lines.push("", "## 优先改进项");
  weaknesses.forEach((item, index) => {
    const focus = text(item.focus);
    if (!focus) return;
    lines.push("", `### ${index + 1}. ${translateReportText(focus)}`);
    addBullet(lines, "维度", formatDimensionName(text(item.dimension) ?? ""));
    addBullet(lines, "不足分析", item.why_it_matters);
    addBullet(lines, "回答证据", item.evidence);
  });
}

function addPracticePlan(lines: string[], report: FinalReport) {
  const practiceItems = getPracticePlan(report);
  if (practiceItems.length === 0) return;
  lines.push("", "## 练习计划");
  practiceItems.forEach((item, index) => {
    const task = text(item.task);
    if (!task) return;
    lines.push("", `### ${index + 1}. ${translateReportText(task)}`);
    addBullet(lines, "训练原因", item.rationale);
    if (typeof item.estimated_hours === "number") {
      lines.push(`- 预计时长：${formatScore(item.estimated_hours)} 小时`);
    }
    const steps = textList(item.steps);
    if (steps.length > 0) {
      lines.push("- 步骤：");
      for (const step of steps) lines.push(`  - ${translateReportText(step)}`);
    }
    const successCriteria = textList(item.success_criteria);
    if (successCriteria.length > 0) {
      lines.push(`- 验收标准：${successCriteria.map(translateReportText).join("；")}`);
    }
  });
}

function addGoals(lines: string[], report: FinalReport) {
  const goals = report.training_plan?.goals_30_60_90;
  if (!goals) return;
  const sections: Array<[string, string[]]> = [
    ["30 天", textList(goals["30_days"])],
    ["60 天", textList(goals["60_days"])],
    ["90 天", textList(goals["90_days"])],
  ];
  if (!sections.some(([, items]) => items.length > 0)) return;

  lines.push("", "## 30/60/90 天训练目标");
  for (const [label, items] of sections) {
    if (items.length === 0) continue;
    lines.push("", `### ${label}`);
    for (const item of items) lines.push(`- ${translateReportText(item)}`);
  }
}

function dimensionScoreRow(
  dimension: string,
  score: RubricScore | undefined,
): { dimension: string; score: string; rationale: string } | null {
  if (!score || typeof score.score !== "number") return null;
  return {
    dimension: formatDimensionName(dimension),
    score: `${score.score.toFixed(1)}/10`,
    rationale: translateReportText(text(score.rationale) ?? ""),
  };
}

function getDiagnosis(report: FinalReport): Diagnosis | null {
  const diagnosis = (report.training_plan as { diagnosis?: Diagnosis } | undefined)?.diagnosis;
  return diagnosis && typeof diagnosis === "object" ? diagnosis : null;
}

function getPriorityWeaknesses(report: FinalReport): PriorityWeakness[] {
  const items = report.training_plan?.priority_weaknesses as unknown;
  if (!Array.isArray(items)) return [];
  return items
    .filter((item) => Boolean(item && typeof item === "object"))
    .map((item) => item as PriorityWeakness);
}

function getPracticePlan(report: FinalReport): PracticePlanItem[] {
  const items = report.training_plan?.practice_plan as unknown;
  if (!Array.isArray(items)) return [];
  return items
    .filter((item) => Boolean(item && typeof item === "object"))
    .map((item) => item as PracticePlanItem);
}

function reportVerdict(report: FinalReport): string | null {
  const value = text(report.growth_signal ?? report.overall_verdict ?? report.verdict);
  return value ? formatVerdict(value) : null;
}

function addLine(lines: string[], label: string, value: unknown) {
  const valueText = text(value);
  if (valueText) lines.push(`${label}：${translateReportText(valueText)}`);
}

function addParagraph(lines: string[], value: unknown) {
  const valueText = text(value);
  if (valueText) lines.push("", translateReportText(valueText));
}

function addBullet(lines: string[], label: string, value: unknown) {
  const valueText = text(value);
  if (valueText) lines.push(`- ${label}：${translateReportText(valueText)}`);
}

function text(value: unknown): string | null {
  if (typeof value === "string") {
    const trimmed = value.trim();
    return trimmed ? trimmed : null;
  }
  if (typeof value === "number" && Number.isFinite(value)) {
    return String(value);
  }
  if (typeof value === "boolean") {
    return value ? "是" : "否";
  }
  return null;
}

function textList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => text(item))
    .filter((item): item is string => Boolean(item));
}

function compactLines(lines: string[]): string[] {
  const out: string[] = [];
  for (const line of lines) {
    if (!line && out[out.length - 1] === "") continue;
    out.push(line);
  }
  return out.filter((line, index, arr) => line || (index > 0 && index < arr.length - 1));
}

function compactMarkdown(lines: string[]): string[] {
  const out = compactLines(lines);
  while (out[out.length - 1] === "") out.pop();
  return out;
}

function formatScore(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

function formatVerdict(value: string): string {
  return VERDICT_LABELS[value.toLowerCase()] ?? value.replace(/_/g, " ");
}

function translateReportText(value: string): string {
  if (!value) return value;
  if (FALLBACK_TRANSLATIONS[value]) return FALLBACK_TRANSLATIONS[value];

  const flagged = value.match(/^Evaluator flagged this in (\d+) turn\(s\) for (.+)\.$/);
  if (flagged) {
    return `评估器在 ${flagged[1]} 轮「${formatDimensionName(flagged[2])}」中都标记了这个问题。`;
  }

  const drill = value.match(/^Run a targeted drill on '(.+)' in (.+)\.$/);
  if (drill) {
    return `围绕「${translateReportText(drill[1])}」做一次${formatDimensionName(drill[2])}专项练习。`;
  }

  const closeWeakness = value.match(/^Close the top-1 weakness in (.+)$/);
  if (closeWeakness) {
    return `完成「${formatDimensionName(closeWeakness[1])}」中最优先待改进项的补强。`;
  }

  const overall = value.match(/^Overall verdict: ([^@.]+)(?: @ ([^.\s]+))?\.?(?: Focus next on (.+)\.)?$/);
  if (overall) {
    const verdict = formatVerdict(overall[1].trim());
    const scoreValue = overall[2] ? Number(overall[2]) : null;
    const score =
      scoreValue !== null && Number.isFinite(scoreValue)
        ? `，总分 ${scoreValue.toFixed(2)}`
        : "";
    const focus = overall[3]
      ? `。下一阶段优先提升「${formatDimensionName(overall[3])}」。`
      : "。";
    return `综合结论：${verdict}${score}${focus}`;
  }

  return value;
}

function escapeTableCell(value: string): string {
  return value.replace(/\|/g, "\\|").replace(/\n+/g, " ");
}
