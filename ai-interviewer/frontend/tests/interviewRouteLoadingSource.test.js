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
  },
  {
    name: "report",
    path: path.join("app", "interview", "[sessionId]", "report", "loading.tsx"),
  },
  {
    name: "replay",
    path: path.join("app", "interview", "[sessionId]", "replay", "loading.tsx"),
  },
];

test("lightweight interview routes do not flash whole-page loading skeletons", () => {
  for (const route of loadingRoutes) {
    const absolutePath = path.join(root, route.path);
    assert.equal(
      fs.existsSync(absolutePath),
      false,
      `${route.name} should rely on source-button pending feedback instead`,
    );
  }
});

test("the heavier interview session route keeps its loading fallback", () => {
  const source = read(path.join("app", "interview", "[sessionId]", "loading.tsx"));

  assert.match(source, /aria-busy="true"/);
  assert.match(source, /正在打开面试页面/);
});
