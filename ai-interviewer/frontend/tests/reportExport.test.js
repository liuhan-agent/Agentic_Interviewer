const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const {
  formatReportMarkdown,
  formatReportSummary,
} = require("../src/lib/report-export.ts");

const root = path.join(__dirname, "..");

function read(relPath) {
  return fs.readFileSync(path.join(root, relPath), "utf8");
}

function sampleReport() {
  return {
    session_id: "sess_123456789",
    overall_score: 7.6,
    growth_signal: "near_target",
    summary: "整体接近目标岗位，工程闭环还需要补强。",
    dimension_scores: {
      technical_depth: {
        score: 8,
        score_status: "scored",
        excluded_from_overall: false,
        exclusion_reason: null,
        coverage_status: "passed",
        rationale: "技术表达清楚",
        weaknesses: [],
      },
      system_design: {
        score: 6.2,
        score_status: "scored",
        excluded_from_overall: false,
        exclusion_reason: null,
        coverage_status: "below_threshold",
        rationale: "一致性方案不完整",
        weaknesses: ["补偿机制缺少边界处理"],
      },
    },
    training_plan: {
      diagnosis: {
        overall_readiness: "候选人接近初级 Java 后端目标岗位。",
        target_level_gap: "差距主要在分布式补偿机制和故障排查闭环。",
        top_patterns: ["表达结构化", "边界预案不足"],
        evidence_refs: ["“我配了重试两次，每次间隔三十秒...”"],
      },
      priority_weaknesses: [
        {
          dimension: "system_design",
          focus: "分布式补偿机制的最终一致性保障",
          why_it_matters: "需要补足数据一致性和线上排障方法论。",
          evidence: "回答提到重试，但没有覆盖异常链路。",
        },
        {
          dimension: "technical_depth",
          focus: "慢 SQL 分析",
          why_it_matters: "需要用指标和实验验证优化效果。",
        },
        {
          dimension: "communication",
          focus: "结论先行",
          why_it_matters: "需要降低沟通成本。",
        },
        {
          dimension: "project_experience",
          focus: "项目复盘",
          why_it_matters: "需要讲清楚取舍。",
        },
      ],
      practice_plan: [
        {
          task: "重构 XXL-Job 补偿机制并补齐一致性单测",
          rationale: "针对本次暴露的补偿链路薄弱点。",
          estimated_hours: 3,
          steps: ["画出失败链路", "补齐幂等校验"],
          success_criteria: ["覆盖重复执行和数据丢失场景"],
        },
        {
          task: "输出慢 SQL 分析文档",
          rationale: "强化性能定位能力。",
          estimated_hours: 2,
        },
        {
          task: "做一次 3 分钟结构化复述",
          rationale: "训练结论先行。",
          estimated_hours: 1,
        },
        {
          task: "整理项目复盘材料",
          rationale: "沉淀可复用案例。",
          estimated_hours: 1,
        },
      ],
      goals_30_60_90: {
        "30_days": ["完成补偿机制重构"],
        "60_days": ["通过代码 Review 验证方案"],
        "90_days": ["独立负责微服务模块值守"],
      },
    },
  };
}

test("report page replaces JSON export with copy summary and Markdown export", () => {
  const source = read("src/components/interview/ReportView.tsx");

  assert.doesNotMatch(source, /application\/json/);
  assert.doesNotMatch(source, /interview-report-\$\{sessionId\.slice\(0,\s*8\)\}\.json/);
  assert.doesNotMatch(source, /导出报告为 JSON/);
  assert.match(source, /复制报告摘要/);
  assert.match(source, /导出 Markdown/);
  assert.match(source, /navigator\.clipboard\.writeText/);
  assert.match(source, /TooltipProvider/);
  assert.match(source, /TooltipTrigger asChild/);
  assert.match(source, /aria-label="复制报告摘要"/);
  assert.match(source, /aria-label="导出 Markdown"/);
  assert.match(source, /size="icon"[\s\S]*<Copy className="h-4 w-4" \/>[\s\S]*<\/Button>/);
  assert.match(source, /size="icon"[\s\S]*<FileText className="h-4 w-4" \/>[\s\S]*<\/Button>/);
  assert.doesNotMatch(source, /<Copy className="h-4 w-4" \/>[\s\S]{0,80}复制报告摘要[\s\S]{0,20}<\/Button>/);
  assert.doesNotMatch(source, /<FileText className="h-4 w-4" \/>[\s\S]{0,80}导出 Markdown[\s\S]{0,20}<\/Button>/);
  assert.match(source, /text\/markdown;charset=utf-8/);
  assert.match(source, /interview-report-\$\{sessionId\.slice\(0,\s*8\)\}\.md/);
  assert.match(source, /useToast/);
  assert.match(source, /已复制报告摘要/);
  assert.match(source, /复制失败，可以改用 Markdown 导出/);
});

test("report actions group review views next steps and tools", () => {
  const source = read("src/components/interview/ReportView.tsx");

  assert.match(source, /aria-label="复盘视图"/);
  assert.match(source, /aria-current="page"/);
  assert.match(source, /aria-label="下一步"/);
  assert.match(source, /aria-label="报告工具"/);
  assert.match(source, /href=\{`\/interview\/\$\{sessionId\}\/replay`\}/);
  assert.match(source, /href=\{`\/interview\/\$\{sessionId\}\/trace`\}/);
  assert.match(source, /weakPracticeHref[\s\S]{0,240}bg-emerald-600/);
  assert.match(source, /weakPracticeHref \? "outline" : "default"/);
});

test("formatReportSummary outputs short user-facing text", () => {
  const summary = formatReportSummary(sampleReport(), { sessionId: "sess_123456789" });

  assert.match(summary, /总评：接近达标/);
  assert.match(summary, /总分：7\.6\/10/);
  assert.match(summary, /能力诊断：候选人接近初级 Java 后端目标岗位。/);
  assert.match(summary, /目标差距：差距主要在分布式补偿机制和故障排查闭环。/);
  assert.match(summary, /1\. 分布式补偿机制的最终一致性保障/);
  assert.match(summary, /下一步训练建议/);
  assert.match(summary, /重构 XXL-Job 补偿机制并补齐一致性单测/);
  assert.doesNotMatch(summary, /\[object Object\]/);
  assert.doesNotMatch(summary, /项目复盘/);
});

test("formatReportMarkdown outputs complete Markdown report", () => {
  const markdown = formatReportMarkdown(sampleReport(), { sessionId: "sess_123456789" });

  assert.match(markdown, /^# 面试复盘报告/m);
  assert.match(markdown, /Session ID：`sess_123456789`/);
  assert.match(markdown, /## 维度评分/);
  assert.match(markdown, /\| 技术深度 \| 8\.0\/10 \| 技术表达清楚 \|/);
  assert.match(markdown, /## 能力诊断/);
  assert.match(markdown, /## 优先改进项/);
  assert.match(markdown, /回答证据：回答提到重试，但没有覆盖异常链路。/);
  assert.match(markdown, /## 练习计划/);
  assert.match(markdown, /验收标准：覆盖重复执行和数据丢失场景/);
  assert.match(markdown, /## 30\/60\/90 天训练目标/);
  assert.match(markdown, /### 90 天/);
  assert.match(markdown, /独立负责微服务模块值守/);
  assert.doesNotMatch(markdown, /\[object Object\]/);
});

test("report formatters tolerate empty reports", () => {
  assert.doesNotThrow(() => formatReportSummary({}, {}));
  assert.doesNotThrow(() => formatReportMarkdown({}, {}));
  assert.doesNotMatch(formatReportSummary({}, {}), /\[object Object\]/);
  assert.doesNotMatch(formatReportMarkdown({}, {}), /\[object Object\]/);
});
