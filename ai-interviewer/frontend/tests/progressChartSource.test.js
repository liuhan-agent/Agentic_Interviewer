const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const progressChartPath = path.join(
  __dirname,
  "..",
  "src",
  "components",
  "interview",
  "ProgressChart.tsx",
);
const historyListPath = path.join(
  __dirname,
  "..",
  "src",
  "components",
  "interview",
  "HistoryList.tsx",
);

test("progress chart renders total and dimension trend modes", () => {
  const source = fs.readFileSync(progressChartPath, "utf8");

  assert.match(source, /ResponsiveContainer/);
  assert.match(source, /LineChart/);
  assert.match(source, /overallScore/);
  assert.match(source, /dimensionScores/);
  assert.match(source, /activeDimension/);
  assert.match(source, /currentMetricLabel/);
  assert.match(source, /tooltipLabel/);
  assert.match(source, /includesFullYear/);
  assert.doesNotMatch(source, /横轴为练习日期/);
  assert.doesNotMatch(source, /纵轴为 0-10 分/);
  assert.doesNotMatch(source, /黄色虚线/);
  assert.match(source, /分为达标线/);
  assert.match(source, /第\$\{occurrence\}场/);
  assert.match(source, /year: "numeric"/);
  assert.match(source, /payload\[0\]\?\.payload\?\.tooltipLabel/);
  assert.match(source, /ProgressTooltip/);
  assert.match(source, /content=\{<ProgressTooltip metricLabel=\{currentMetricLabel\}\s*\/>\}/);
  assert.match(source, /bg-zinc-950\/95/);
  assert.match(source, /text-muted-foreground\/70/);
  assert.match(source, /近 5 场变化/);
  assert.match(source, /针对薄弱点专项练习/);
});

test("history list mounts progress chart above entries", () => {
  const source = fs.readFileSync(historyListPath, "utf8");

  assert.match(source, /ProgressChart/);
  assert.match(source, /entries=\{entries\}/);
  assert.match(source, /dimensionScores/);
});
