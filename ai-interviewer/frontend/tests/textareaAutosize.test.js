const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const source = fs.readFileSync(
  path.join(__dirname, "../src/components/ui/textarea.tsx"),
  "utf8",
);

test("shared Textarea auto-resizes by default with a bounded max height", () => {
  assert.match(source, /autoResize\s*=\s*true/);
  assert.match(source, /maxAutoResizeHeight\s*=\s*360/);
  assert.match(source, /scrollHeight/);
  assert.match(source, /overflowY/);
});

test("shared Textarea exposes autoResize escape hatch", () => {
  assert.match(source, /autoResize\?:\s*boolean/);
  assert.match(source, /if \(!autoResize\) return/);
});
