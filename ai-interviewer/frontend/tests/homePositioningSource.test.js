const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.join(__dirname, "..");

function read(relPath) {
  return fs.readFileSync(path.join(root, relPath), "utf8");
}

test("home page centers AI interviewer workflow before training output", () => {
  const source = read("src/app/page.tsx");

  assert.match(source, /面试主链路/);
  assert.match(source, /追问评分复盘/);
  assert.match(source, /下一场训练/);
  assert.doesNotMatch(source, /title: "成长规划"/);
  assert.doesNotMatch(source, /个性化成长计划/);
  assert.doesNotMatch(source, /AI 教练/);
});
