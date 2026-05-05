const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.join(__dirname, "..");

function read(relPath) {
  return fs.readFileSync(path.join(root, relPath), "utf8");
}

test("admin routes redirect home unless the public admin flag is enabled", () => {
  const source = read("src/middleware.ts");

  assert.match(source, /NEXT_PUBLIC_ADMIN_NAV_ENABLED/);
  assert.match(source, /pathname\.startsWith\("\/admin"\)/);
  assert.match(source, /NextResponse\.redirect/);
  assert.match(source, /new URL\("\/"/);
});
