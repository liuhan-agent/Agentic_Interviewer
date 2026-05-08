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
  assert.match(source, /createdAt\.localeCompare/);
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

test("history list describes backend deletion result counts", () => {
  const source = fs.readFileSync(
    path.join(__dirname, "..", "src", "components", "interview", "HistoryList.tsx"),
    "utf8",
  );

  assert.match(source, /describeDeleteSessionResult/);
  assert.match(source, /sessions_deleted/);
  assert.match(source, /outcomes_deleted/);
  assert.match(source, /服务端没有找到可删除的数据/);
});
