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
  assert.match(tooltip, /side = "bottom"/);
  assert.match(tooltip, /side=\{side\}/);
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

test("history list splits logged-in account records from local anonymous records", () => {
  const source = readSource("src", "components", "interview", "HistoryList.tsx");

  assert.match(source, /getAccountInterviewSessions/);
  assert.match(source, /SplitHistoryResult/);
  assert.match(source, /splitAccountAndLocalHistory/);
  assert.match(source, /primaryEntries/);
  assert.match(source, /anonymousEntries/);
  assert.match(source, /本机匿名记录/);
  assert.match(source, /带有效凭证/);
  assert.match(source, /当前没有可同步凭证/);
  assert.match(source, /不能删除服务端数据/);
  assert.match(source, /anonymousOpen/);
  assert.match(source, /useState\(false\)/);
  assert.match(source, /hiddenOtherAccountCount/);
  assert.match(source, /ownerUserId/);
});

test("history list exposes explicit claim for local anonymous sessions", () => {
  const source = readSource("src", "components", "interview", "HistoryList.tsx");

  assert.match(source, /claimSession/);
  assert.match(source, /claimableAnonymousEntries/);
  assert.match(source, /anonymousEntries/);
  assert.match(source, /handleClaimAnonymousEntries/);
  assert.match(source, /Promise\.allSettled/);
  assert.match(source, /同步可认领记录/);
  assert.match(source, /匿名记录已同步/);
  assert.doesNotMatch(source, /一键保存到账号/);
  assert.doesNotMatch(source, /账号记录已同步/);
});

test("history split keeps anonymous entries primary only before login", () => {
  const source = readSource("src", "components", "interview", "HistoryList.tsx");

  assert.match(source, /currentUserId === null/);
  assert.match(source, /source: "local_anonymous"/);
  assert.match(source, /primaryEntries\.push/);
  assert.match(source, /anonymousEntries\.push/);
  assert.match(source, /localEntry\.ownerUserId !== currentUserId/);
});

test("account history records do not expose local-only removal", () => {
  const source = readSource("src", "components", "interview", "HistoryList.tsx");

  assert.match(source, /canRemoveLocal/);
  assert.match(source, /canDeleteData/);
  assert.match(source, /entry\.source === "local_anonymous"/);
  assert.match(source, /entry\.source === "account"/);
});
