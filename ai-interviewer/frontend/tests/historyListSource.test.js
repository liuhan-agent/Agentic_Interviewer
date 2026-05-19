const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

function readSource(...parts) {
  return fs.readFileSync(path.join(__dirname, "..", ...parts), "utf8");
}

test("history storage validates dates scores and array fields", () => {
  const source = readSource("src", "lib", "storage", "interviewHistory.ts");

  assert.match(source, /isValidIsoDate/);
  assert.match(source, /isValidScore/);
  assert.match(source, /isStringList/);
  assert.match(source, /Date\.parse/);
  assert.match(source, /Number\.isFinite/);
});

test("history list keeps unscored entries behind scored entries", () => {
  const source = readSource("src", "components", "interview", "HistoryList.tsx");

  assert.match(source, /compareScoreEntries/);
  assert.match(source, /hasAScore/);
  assert.match(source, /hasBScore/);
  assert.match(source, /lastVisitedAt\.localeCompare/);
});

test("history list splits sort field and direction controls", () => {
  const source = readSource("src", "components", "interview", "HistoryList.tsx");
  const constants = readSource("src", "lib", "constants", "interview.ts");

  assert.match(constants, /SORT_FIELD_OPTIONS/);
  assert.doesNotMatch(constants, /SORT_OPTIONS/);
  assert.match(source, /activeSortField/);
  assert.match(source, /activeSortDirection/);
  assert.match(source, /ArrowDownAZ|ArrowUpAZ/);
});

test("history list backfills server metadata without touching visit time", () => {
  const source = readSource("src", "components", "interview", "HistoryList.tsx");

  assert.match(source, /getSessionMetadata/);
  assert.match(source, /mergeServerEntryMetadata/);
  assert.match(source, /updatedAt/);
});

test("history card exposes full session id in styled tooltip", () => {
  const source = readSource("src", "components", "interview", "HistoryList.tsx");
  const tooltip = readSource(
    "src",
    "components",
    "interview",
    "SessionIdTooltip.tsx",
  );

  assert.match(source, /from "@\/components\/interview\/SessionIdTooltip"/);
  assert.match(source, /SessionIdTooltip/);
  assert.match(tooltip, /from "@\/components\/ui\/tooltip"/);
  assert.match(tooltip, /<TooltipTrigger asChild>/);
  assert.match(tooltip, /aria-label=\{`/);
  assert.match(tooltip, /cursor-default/);
  assert.doesNotMatch(tooltip, /cursor-help/);
  assert.match(tooltip, /side="bottom"/);
  assert.match(tooltip, /text-emerald-300/);
  assert.match(tooltip, /<span className="break-all">\{sessionId\}<\/span>/);
  assert.match(tooltip, /shortSessionId\(sessionId\)/);
});

test("history list has a filtered empty state", () => {
  const source = readSource("src", "components", "interview", "HistoryList.tsx");

  assert.match(source, /FilteredEmptyState/);
});

test("history list describes backend deletion result counts", () => {
  const source = readSource("src", "components", "interview", "HistoryList.tsx");

  assert.match(source, /describeDeleteSessionResult/);
  assert.match(source, /sessions_deleted/);
  assert.match(source, /outcomes_deleted/);
  assert.match(source, /服务端没有找到可删除的数据/);
});

test("history page exposes setup drafts separately from interview records", () => {
  const source = readSource("src", "components", "interview", "HistoryList.tsx");

  assert.match(source, /getSetupDrafts/);
  assert.match(source, /SetupDraftCard/);
});

test("history export strips browser recovery credential", () => {
  const source = readSource("src", "components", "interview", "HistoryList.tsx");

  assert.match(source, /delete safeEntry\.recoveryToken/);
  assert.match(source, /delete safeEntry\.recoveryTokenExpiresAt/);
});

test("history list does not expose a bulk local clear action", () => {
  const source = readSource("src", "components", "interview", "HistoryList.tsx");

  assert.doesNotMatch(source, /window\.confirm/);
  assert.doesNotMatch(source, /ClearHistoryDialog/);
  assert.doesNotMatch(source, /handleClearAll/);
  assert.doesNotMatch(source, /clearAll\(/);
});
