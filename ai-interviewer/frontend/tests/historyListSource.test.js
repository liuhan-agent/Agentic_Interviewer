const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

test("history storage validates dates scores and array fields", () => {
  const source = fs.readFileSync(
    path.join(__dirname, "..", "src", "lib", "storage", "interviewHistory.ts"),
    "utf8",
  );

  assert.match(source, /isValidIsoDate/);
  assert.match(source, /isValidScore/);
  assert.match(source, /isStringList/);
  assert.match(source, /Date\.parse/);
  assert.match(source, /Number\.isFinite/);
});

test("history list keeps unscored entries behind scored entries", () => {
  const source = fs.readFileSync(
    path.join(__dirname, "..", "src", "components", "interview", "HistoryList.tsx"),
    "utf8",
  );

  assert.match(source, /compareScoreEntries/);
  assert.match(source, /hasAScore/);
  assert.match(source, /hasBScore/);
  assert.match(source, /lastVisitedAt\.localeCompare/);
});

test("history list splits sort field and direction controls", () => {
  const source = fs.readFileSync(
    path.join(__dirname, "..", "src", "components", "interview", "HistoryList.tsx"),
    "utf8",
  );
  const constants = fs.readFileSync(
    path.join(__dirname, "..", "src", "lib", "constants", "interview.ts"),
    "utf8",
  );

  assert.match(constants, /SORT_FIELD_OPTIONS/);
  assert.doesNotMatch(constants, /SORT_OPTIONS/);
  assert.match(source, /activeSortField/);
  assert.match(source, /activeSortDirection/);
  assert.match(constants, /最近访问/);
  assert.match(constants, /创建时间/);
  assert.match(constants, /面试分数/);
  assert.match(source, /ArrowDownAZ|ArrowUpAZ/);
});

test("history list backfills server metadata without touching visit time", () => {
  const source = fs.readFileSync(
    path.join(__dirname, "..", "src", "components", "interview", "HistoryList.tsx"),
    "utf8",
  );

  assert.match(source, /getSessionMetadata/);
  assert.match(source, /mergeServerEntryMetadata/);
  assert.match(source, /updatedAt/);
  assert.match(source, /最近访问/);
  assert.match(source, /最近继续/);
  assert.match(source, /创建于/);
  assert.match(source, /加入列表/);
});

test("history card exposes full session id in styled tooltip", () => {
  const source = fs.readFileSync(
    path.join(__dirname, "..", "src", "components", "interview", "HistoryList.tsx"),
    "utf8",
  );
  const tooltip = fs.readFileSync(
    path.join(
      __dirname,
      "..",
      "src",
      "components",
      "interview",
      "SessionIdTooltip.tsx",
    ),
    "utf8",
  );

  assert.match(source, /from "@\/components\/interview\/SessionIdTooltip"/);
  assert.match(source, /SessionIdTooltip/);
  assert.match(tooltip, /from "@\/components\/ui\/tooltip"/);
  assert.match(tooltip, /<TooltipTrigger asChild>/);
  assert.match(tooltip, /完整 Session ID/);
  assert.match(tooltip, /aria-label=\{`完整 Session ID/);
  assert.match(tooltip, /cursor-default/);
  assert.doesNotMatch(tooltip, /cursor-help/);
  assert.match(tooltip, /side="bottom"/);
  assert.match(tooltip, /text-emerald-300/);
  assert.match(tooltip, /<span className="break-all">\{sessionId\}<\/span>/);
  assert.match(tooltip, /shortSessionId\(sessionId\)/);
});

test("history list has a filtered empty state", () => {
  const source = fs.readFileSync(
    path.join(__dirname, "..", "src", "components", "interview", "HistoryList.tsx"),
    "utf8",
  );

  assert.match(source, /FilteredEmptyState/);
  assert.match(source, /当前筛选下没有面试记录/);
  assert.match(source, /查看全部/);
});

test("history export strips browser recovery credential", () => {
  const source = fs.readFileSync(
    path.join(__dirname, "..", "src", "components", "interview", "HistoryList.tsx"),
    "utf8",
  );

  assert.match(source, /delete safeEntry\.recoveryToken/);
  assert.match(source, /delete safeEntry\.recoveryTokenExpiresAt/);
});

test("history list does not expose a bulk local clear action", () => {
  const source = fs.readFileSync(
    path.join(__dirname, "..", "src", "components", "interview", "HistoryList.tsx"),
    "utf8",
  );

  assert.doesNotMatch(source, /window\.confirm/);
  assert.doesNotMatch(source, /ClearHistoryDialog/);
  assert.doesNotMatch(source, /handleClearAll/);
  assert.doesNotMatch(source, /clearAll\(/);
  assert.doesNotMatch(source, /清空本地列表/);
});
