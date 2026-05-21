const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.join(__dirname, "..", "src");

function read(relPath) {
  return fs.readFileSync(path.join(root, relPath), "utf8");
}

test("PendingNavigationLink gives clicked route buttons immediate local feedback", () => {
  const source = read("components/navigation/PendingNavigationLink.tsx");

  assert.match(source, /"use client"/);
  assert.match(source, /usePathname/);
  assert.match(source, /useEffect/);
  assert.match(source, /Loader2/);
  assert.match(source, /aria-busy=\{isPending/);
  assert.match(source, /data-pending/);
  assert.match(source, /pendingLabel/);
  assert.match(source, /event\.metaKey/);
  assert.match(source, /event\.ctrlKey/);
  assert.match(source, /event\.defaultPrevented/);
  assert.match(source, /setIsPending\(true\)/);
  assert.match(source, /setIsPending\(false\)/);
});

test("router-pushed navigation buttons also show local feedback", () => {
  const source = read("components/interview/VoiceRoom.tsx");

  assert.match(source, /switchingToText/);
  assert.match(source, /setSwitchingToText\(true\)/);
  assert.match(source, /router\.push\(`\/interview\/\$\{sessionId\}`\)/);
  assert.match(source, /Loader2[\s\S]{0,80}animate-spin/);
});

test("high-traffic navigation surfaces use pending route links", () => {
  const files = [
    "app/page.tsx",
    "components/layout/AppShell.tsx",
    "components/landing/ResumeHero.tsx",
    "components/interview/HistoryList.tsx",
    "components/interview/InterviewRoom.tsx",
    "components/interview/ReportView.tsx",
    "components/interview/ReplayView.tsx",
  ];

  for (const file of files) {
    const source = read(file);
    assert.match(
      source,
      /PendingNavigationLink/,
      `${file} should use button-level pending navigation feedback`,
    );
  }
});
