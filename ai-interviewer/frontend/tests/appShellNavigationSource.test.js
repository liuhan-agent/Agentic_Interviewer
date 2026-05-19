const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.join(__dirname, "..");

function read(relPath) {
  return fs.readFileSync(path.join(root, relPath), "utf8");
}

test("app shell exposes parent and root navigation shortcuts", () => {
  const source = read("src/components/layout/AppShell.tsx");

  assert.match(source, /NavigationShortcuts/);
  assert.match(source, /resolveParentHref/);
  assert.match(source, /sticky top-16 z-20/);
  assert.match(source, /backdrop-blur-xl/);
  assert.match(source, /返回上一级/);
  assert.match(source, /回到首页/);
});

test("app shell maps interview section parent routes to valid pages", () => {
  const source = read("src/components/layout/AppShell.tsx");

  assert.ok(source.includes("parent === \"/interview\""));
  assert.ok(source.includes("return \"/\""));
  assert.ok(source.includes("pathname === \"/\""));
});

test("report pages return to interview history instead of completed session pages", () => {
  const source = read("src/components/layout/AppShell.tsx");

  assert.ok(source.includes("segments[0] === \"interview\""));
  assert.ok(source.includes("segments[2] === \"report\""));
  assert.ok(source.includes("return \"/interview/history\""));
});

test("admin navigation is hidden behind the public admin env guard", () => {
  const source = read("src/components/layout/AppShell.tsx");

  assert.match(source, /NEXT_PUBLIC_ADMIN_NAV_ENABLED/);
  assert.match(source, /showAdminNav/);
  assert.match(source, /showAdminNav\s*&&/);
});
