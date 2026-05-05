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
  assert.match(source, /近 5 场变化/);
  assert.match(source, /针对薄弱点专项练习/);
});

test("history list mounts progress chart above entries", () => {
  const source = fs.readFileSync(historyListPath, "utf8");

  assert.match(source, /ProgressChart/);
  assert.match(source, /entries=\{entries\}/);
  assert.match(source, /dimensionScores/);
});
