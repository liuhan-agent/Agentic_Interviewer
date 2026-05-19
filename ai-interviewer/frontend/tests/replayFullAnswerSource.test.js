const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const replaySource = fs.readFileSync(
  path.join(__dirname, "..", "src", "components", "interview", "ReplayView.tsx"),
  "utf8",
);

test("ReplayView renders answers with the shared collapsible answer bubble", () => {
  assert.match(replaySource, /import \{ CollapsibleAnswerBubble \}/);
  assert.match(
    replaySource,
    /<CollapsibleAnswerBubble\s+text=\{turn\.answer\}\s+label="你"/,
  );
  assert.doesNotMatch(replaySource, /你（转录）|语音转写|转写文本/);
});
