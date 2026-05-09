const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.join(__dirname, "..");

function read(relPath) {
  return fs.readFileSync(path.join(root, relPath), "utf8");
}

test("NextQuestionLoader exposes ARIA progressbar role with aria-valuenow", () => {
  const source = read("src/components/interview/NextQuestionLoader.tsx");

  // Screen readers must hear the progress percentage so blind users
  // know the AI is still working and how far along it is.
  assert.match(source, /role="progressbar"/);
  assert.match(source, /aria-valuemin=\{0\}/);
  assert.match(source, /aria-valuemax=\{100\}/);
  assert.match(source, /aria-valuenow=/);
});

test("NextQuestionLoader caps progress at 95% to avoid the false-completion trap", () => {
  const source = read("src/components/interview/NextQuestionLoader.tsx");

  // When the server runs longer than the prior segment, the bar must
  // stay short of 100% — finishing the bar before the next question
  // arrives looks broken. 0.95 is the agreed visual cap; either a
  // literal or a clearly-named constant counts.
  assert.match(source, /0\.95/);
  assert.match(source, /Math\.min\(/);
});

test("NextQuestionLoader cleans up its interval on unmount", () => {
  const source = read("src/components/interview/NextQuestionLoader.tsx");

  // Without an explicit clearInterval, the timer keeps firing after the
  // user navigates away (memory leak + repeated setState on a stale
  // component). Source-scan asserts both the timer and the cleanup.
  assert.match(source, /setInterval\(/);
  assert.match(source, /clearInterval\(/);
});

test("NextQuestionLoader uses a 7000ms fallback when etaMs is missing", () => {
  const source = read("src/components/interview/NextQuestionLoader.tsx");

  // The first turn has no prior latency on the handle; falling back to
  // a sane default lets the bar still animate. 7s mirrors the legacy
  // hard-coded "通常 5-10 秒" hint roughly.
  assert.match(source, /7000/);
});

test("InterviewRoom delegates loading state to NextQuestionLoader with etaMs", () => {
  const source = read("src/components/interview/InterviewRoom.tsx");

  assert.match(
    source,
    /import \{ NextQuestionLoader \} from "@\/components\/interview\/NextQuestionLoader"/,
  );
  assert.match(source, /<NextQuestionLoader\s+etaMs=\{state\.lastServerLatencyMs\}/);
});

test("NextQuestionLoader has final-turn copy that does not promise another question", () => {
  const source = read("src/components/interview/NextQuestionLoader.tsx");

  assert.match(source, /isFinalTurn/);
  assert.match(source, /正在整理本场面试总结/);
  assert.match(source, /最后一题已提交/);
});
