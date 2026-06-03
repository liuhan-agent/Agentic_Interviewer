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

test("admin navigation requires the logged-in account to be admin", () => {
  const source = read("src/components/layout/AppShell.tsx");
  const adminApi = read("src/lib/api/admin.ts");

  assert.match(adminApi, /export function hasAdminToken/);
  assert.match(adminApi, /ADMIN_TOKEN_EVENT/);
  assert.match(source, /!auth\.loading/);
  assert.match(source, /auth\.user\?\.role === "admin"/);
  assert.match(source, /showAdminNav =[\s\S]*NEXT_PUBLIC_ADMIN_NAV_ENABLED[\s\S]*auth\.user\?\.role === "admin"/);
  assert.doesNotMatch(source, /showAdminNav =[\s\S]*hasAdminToken/);
});

test("app shell shows account credit balance from user auth state", () => {
  const source = read("src/components/layout/AppShell.tsx");
  const accountApi = read("src/lib/api/account.ts");

  assert.match(accountApi, /getAccountCredits/);
  assert.match(source, /getAccountCredits/);
  assert.match(source, /creditBalance/);
  assert.match(source, /剩余 \{creditBalance\} 次/);
  assert.match(source, /登录领取免费次数/);
});

test("app shell credit pill has lightweight visual treatment", () => {
  const source = read("src/components/layout/AppShell.tsx");

  assert.match(source, /function CreditStatusPill/);
  assert.match(source, /Gift/);
  assert.match(source, /animate-ping/);
  assert.match(source, /shadow-\[0_0_24px_rgba\(16,185,129,0\.14\)\]/);
  assert.match(source, /hover:border-emerald-400\/40/);
  assert.match(source, /className="hidden xl:inline-flex"/);
  assert.match(source, /className="h-10 justify-center rounded-lg text-sm"/);
});

test("app shell waits for verified auth before loading account credits", () => {
  const source = read("src/components/layout/AppShell.tsx");

  assert.match(source, /auth\.loading/);
  assert.match(source, /if \(auth\.loading\) return/);
  assert.match(source, /\[auth\.authenticated, auth\.loading, auth\.user\?\.id\]/);
});
