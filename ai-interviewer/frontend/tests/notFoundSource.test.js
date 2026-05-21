const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.join(__dirname, "..");

function read(relPath) {
  return fs.readFileSync(path.join(root, relPath), "utf8");
}

test("not found page uses a plain home anchor for reliable recovery", () => {
  const source = read("src/app/not-found.tsx");

  assert.match(source, /返回首页/);
  assert.match(source, /<a href="\/">/);
  assert.doesNotMatch(source, /PendingNavigationLink/);
});
