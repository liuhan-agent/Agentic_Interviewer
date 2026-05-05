const assert = require("node:assert/strict");
const test = require("node:test");

const {
  clearVoiceReportCache,
  readVoiceReportCache,
  storeVoiceReportCache,
  voiceReportCacheKey,
} = require("../src/lib/storage/voiceReportCache.ts");

function makeStorage(initial = {}) {
  const data = new Map(Object.entries(initial));
  return {
    getItem(key) {
      return data.has(key) ? data.get(key) : null;
    },
    setItem(key, value) {
      data.set(key, String(value));
    },
    removeItem(key) {
      data.delete(key);
    },
  };
}

test("reads the cached voice report for the matching session", () => {
  const report = {
    session_id: "voice-1",
    overall_score: 8.4,
    summary: "cached report",
  };
  const storage = makeStorage({
    [voiceReportCacheKey("voice-1")]: JSON.stringify(report),
  });

  assert.deepEqual(readVoiceReportCache("voice-1", storage), report);
  assert.equal(
    storage.getItem(voiceReportCacheKey("voice-1")),
    JSON.stringify(report),
  );
});

test("removes malformed cached reports before returning null", () => {
  const storage = makeStorage({
    [voiceReportCacheKey("voice-2")]: "{bad-json",
  });

  assert.equal(readVoiceReportCache("voice-2", storage), null);
  assert.equal(storage.getItem(voiceReportCacheKey("voice-2")), null);
});

test("stores and clears a cached voice report", () => {
  const storage = makeStorage();
  const report = { session_id: "voice-3", overall_verdict: "hire" };

  storeVoiceReportCache("voice-3", report, storage);
  assert.deepEqual(readVoiceReportCache("voice-3", storage), report);

  clearVoiceReportCache("voice-3", storage);
  assert.equal(readVoiceReportCache("voice-3", storage), null);
});
