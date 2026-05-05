const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.join(__dirname, "..");

function read(relPath) {
  return fs.readFileSync(path.join(root, relPath), "utf8");
}

test("project exposes a shared Radix tooltip wrapper", () => {
  const tooltip = read("src/components/ui/tooltip.tsx");

  assert.match(tooltip, /@radix-ui\/react-tooltip/);
  assert.match(tooltip, /TooltipProvider/);
  assert.match(tooltip, /TooltipTrigger/);
  assert.match(tooltip, /TooltipContent/);
});

test("TrainingPlanSourceBadge uses tooltip instead of native title", () => {
  const source = read("src/components/interview/TrainingPlanSourceBadge.tsx");

  assert.match(source, /from "@\/components\/ui\/tooltip"/);
  assert.match(source, /<TooltipProvider/);
  assert.match(source, /<TooltipTrigger asChild>/);
  assert.match(source, /<TooltipContent/);
  assert.doesNotMatch(source, /title=/);
  assert.match(source, /aria-label=/);
  assert.match(source, /tabIndex=\{0\}/);
});

test("ReportView cross-session widgets explain their signals with InfoTooltip", () => {
  const source = read("src/components/interview/ReportView.tsx");

  assert.match(source, /import \{ InfoTooltip \}/);
  assert.match(source, /vs 上一次练习[\s\S]*?<InfoTooltip/);
  assert.match(source, /跨场练习信号[\s\S]*?<InfoTooltip/);
  assert.match(source, /只基于当前浏览器保存的历史记录/);
});

test("high-touch UI surfaces do not rely on native title attributes", () => {
  const files = [
    "src/components/interview/ReportView.tsx",
    "src/components/interview/HistoryList.tsx",
    "src/components/interview/InterviewRoom.tsx",
    "src/components/layout/AppShell.tsx",
    "src/components/layout/LLMSettingsDialog.tsx",
    "src/components/admin/AdminPanel.tsx",
    "src/components/admin/TraceExplorer.tsx",
    "src/components/interview/TrainingPlanSourceBadge.tsx",
  ];

  for (const file of files) {
    assert.doesNotMatch(read(file), /\btitle=/, file);
  }
});
