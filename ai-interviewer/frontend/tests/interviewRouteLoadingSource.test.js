const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.join(__dirname, "..", "src");

function read(relPath) {
  return fs.readFileSync(path.join(root, relPath), "utf8");
}

const loadingRoutes = [
  {
    name: "history",
    path: path.join("app", "interview", "history", "loading.tsx"),
    title: "正在打开面试历史",
  },
  {
    name: "report",
    path: path.join("app", "interview", "[sessionId]", "report", "loading.tsx"),
    title: "正在打开面试报告",
  },
  {
    name: "replay",
    path: path.join("app", "interview", "[sessionId]", "replay", "loading.tsx"),
    title: "正在打开复盘页面",
  },
];

test("high-frequency interview routes expose static loading skeletons", () => {
  for (const route of loadingRoutes) {
    const absolutePath = path.join(root, route.path);

    assert.equal(fs.existsSync(absolutePath), true, `${route.name} loading route missing`);
    const source = read(route.path);

    assert.match(source, /aria-busy="true"/);
    assert.match(source, new RegExp(route.title));
    assert.match(source, /rounded-lg border bg-card/);
    assert.doesNotMatch(source, /"use client"/);
    assert.doesNotMatch(source, /getReport|getReplay|resumeSession|fetch\(/);
  }
});
