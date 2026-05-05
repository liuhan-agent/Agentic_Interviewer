const assert = require("node:assert/strict");
const test = require("node:test");

const {
  clearAll,
  getCompletedBefore,
  getEntry,
  getHistory,
  getSessionToken,
  SESSION_TOKEN_TTL_DAYS,
  upsertEntry,
} = require("../src/lib/storage/interviewHistory.ts");

function makeStorage(initial = {}) {
  const data = new Map(Object.entries(initial));
  const storage = {
    getItem(key) {
      return data.has(key) ? data.get(key) : null;
    },
    setItem(key, value) {
      data.set(key, String(value));
    },
    removeItem(key) {
      data.delete(key);
    },
    clear() {
      data.clear();
    },
    key(index) {
      return Array.from(data.keys())[index] ?? null;
    },
    get length() {
      return data.size;
    },
  };
  storage._data = data;
  return storage;
}

function installLocalStorage(initial = {}) {
  const localStorage = makeStorage(initial.localStorage ?? initial);
  const sessionStorage = makeStorage(initial.sessionStorage ?? {});

  global.window = { localStorage, sessionStorage };
  return localStorage;
}

test("upsertEntry creates a running history entry and last-session pointer", () => {
  const storage = installLocalStorage();

  const entry = upsertEntry({
    sessionId: "session-1",
    jdTitle: "Java 后端开发",
    candidateName: "刘韩",
    jobLevel: "junior",
    rubricDimensions: ["technical_depth", "project_experience"],
    status: "running",
  });

  assert.equal(entry.sessionId, "session-1");
  assert.equal(entry.sessionToken, undefined);
  assert.equal(entry.jdTitle, "Java 后端开发");
  assert.equal(entry.candidateName, "刘韩");
  assert.equal(entry.jobLevel, "junior");
  assert.deepEqual(entry.rubricDimensions, [
    "technical_depth",
    "project_experience",
  ]);
  assert.equal(entry.status, "running");
  assert.equal(storage.getItem("lastSessionId"), "session-1");
  assert.equal(getHistory().length, 1);
});

test("upsertEntry keeps session token out of persistent history", () => {
  const storage = installLocalStorage();

  upsertEntry({
    sessionId: "session-token",
    sessionToken: "secret-token",
    jdTitle: "Backend",
    status: "running",
  });

  assert.doesNotMatch(storage.getItem("interviewHistory"), /secret-token/);
  assert.equal(getEntry("session-token").sessionToken, undefined);
  assert.equal(getSessionToken("session-token"), "secret-token");
  const rawSessionToken = window.sessionStorage.getItem(
    "interviewSessionToken:session-token",
  );
  assert.match(rawSessionToken, /secret-token/);
  const expiresAt = new Date(JSON.parse(rawSessionToken).expiresAt);
  const createdAt = new Date(getEntry("session-token").createdAt);
  const ttlMs = expiresAt.getTime() - createdAt.getTime();
  assert.ok(ttlMs >= (SESSION_TOKEN_TTL_DAYS * 24 * 60 * 60 * 1000) - 1000);
});

test("expired session token is removed while history remains", () => {
  const expired = new Date(Date.now() - 1000).toISOString();
  installLocalStorage({
    interviewHistory: JSON.stringify({
      version: 1,
      entries: [
        {
          sessionId: "expired-token",
          sessionToken: "secret-token",
          sessionTokenExpiresAt: expired,
          jdTitle: "Backend",
          createdAt: new Date().toISOString(),
          lastVisitedAt: new Date().toISOString(),
          status: "running",
        },
      ],
    }),
  });

  assert.equal(getSessionToken("expired-token"), undefined);
  const entry = getEntry("expired-token");
  assert.equal(entry.sessionId, "expired-token");
  assert.equal(entry.sessionToken, undefined);
  assert.equal(entry.sessionTokenExpiresAt, undefined);
});

test("legacy localStorage session token is migrated to sessionStorage", () => {
  installLocalStorage({
    interviewHistory: JSON.stringify({
      version: 1,
      entries: [
        {
          sessionId: "legacy-token",
          sessionToken: "legacy-secret",
          sessionTokenExpiresAt: new Date(Date.now() + 60_000).toISOString(),
          jdTitle: "Backend",
          createdAt: new Date().toISOString(),
          lastVisitedAt: new Date().toISOString(),
          status: "running",
        },
      ],
    }),
  });

  assert.equal(getSessionToken("legacy-token"), "legacy-secret");
  assert.equal(getEntry("legacy-token").sessionToken, undefined);
  assert.doesNotMatch(
    window.localStorage.getItem("interviewHistory"),
    /legacy-secret/,
  );
});

test("clearAll removes orphan sessionStorage tokens", () => {
  installLocalStorage({
    sessionStorage: {
      "interviewSessionToken:orphan": JSON.stringify({
        token: "orphan-secret",
        expiresAt: new Date(Date.now() + 60_000).toISOString(),
      }),
    },
  });

  clearAll();

  assert.equal(
    window.sessionStorage.getItem("interviewSessionToken:orphan"),
    null,
  );
});

test("upsertEntry refreshes existing entries without clearing omitted fields", () => {
  installLocalStorage();

  upsertEntry({
    sessionId: "session-2",
    jdTitle: "前端开发",
    candidateName: "候选人",
    jobLevel: "mid",
    rubricDimensions: ["code_quality"],
    status: "running",
  });

  const refreshed = upsertEntry({
    sessionId: "session-2",
    status: "running",
  });

  assert.equal(refreshed.jdTitle, "前端开发");
  assert.equal(refreshed.candidateName, "候选人");
  assert.equal(refreshed.jobLevel, "mid");
  assert.deepEqual(refreshed.rubricDimensions, ["code_quality"]);
  assert.equal(refreshed.status, "running");
  assert.deepEqual(getEntry("session-2"), refreshed);
  assert.equal(getHistory().length, 1);
});

test("upsertEntry persists progress chart fields", () => {
  installLocalStorage();

  const entry = upsertEntry({
    sessionId: "session-progress",
    jdTitle: "后端开发",
    status: "done",
    overallScore: 7.6,
    dimensionScores: {
      system_design: 6.8,
      coding_quality: 8.1,
    },
    maxTurns: 8,
  });

  assert.deepEqual(entry.dimensionScores, {
    system_design: 6.8,
    coding_quality: 8.1,
  });
  assert.equal(entry.maxTurns, 8);
  assert.deepEqual(getEntry("session-progress").dimensionScores, {
    system_design: 6.8,
    coding_quality: 8.1,
  });
});

test("getCompletedBefore returns null when there is no other completed session", () => {
  installLocalStorage();
  upsertEntry({
    sessionId: "only",
    jdTitle: "Backend",
    status: "done",
    overallScore: 7.0,
  });
  assert.equal(getCompletedBefore("only"), null);
});

test("getCompletedBefore picks the most recent done entry strictly older than the target", () => {
  installLocalStorage();
  // Insert an older done entry first so its createdAt is genuinely earlier;
  // upsertEntry stamps createdAt at insert time.
  upsertEntry({
    sessionId: "earlier",
    jdTitle: "Frontend",
    status: "done",
    overallScore: 6.0,
  });
  // Sleep-equivalent: bump the clock by mutating storage so the second
  // entry has a later createdAt without relying on real time.
  const raw = JSON.parse(window.localStorage.getItem("interviewHistory"));
  const earlier = raw.entries.find((e) => e.sessionId === "earlier");
  earlier.createdAt = new Date(Date.now() - 60_000).toISOString();
  earlier.lastVisitedAt = earlier.createdAt;
  window.localStorage.setItem("interviewHistory", JSON.stringify(raw));

  upsertEntry({
    sessionId: "current",
    jdTitle: "Frontend",
    status: "done",
    overallScore: 7.5,
  });

  const previous = getCompletedBefore("current");
  assert.ok(previous);
  assert.equal(previous.sessionId, "earlier");
  assert.equal(previous.overallScore, 6.0);
});

test("getCompletedBefore returns null when target session is unknown", () => {
  installLocalStorage();
  upsertEntry({
    sessionId: "old",
    jdTitle: "Frontend",
    status: "done",
    overallScore: 7.0,
  });
  // The target sessionId doesn't exist locally; we refuse to lie about
  // chronology and return null instead of picking an arbitrary done entry.
  assert.equal(getCompletedBefore("ghost-session"), null);
});

test("getCompletedBefore skips non-done entries even if older", () => {
  installLocalStorage();
  upsertEntry({
    sessionId: "running-old",
    jdTitle: "Backend",
    status: "running",
  });
  const raw = JSON.parse(window.localStorage.getItem("interviewHistory"));
  raw.entries[0].createdAt = new Date(Date.now() - 60_000).toISOString();
  window.localStorage.setItem("interviewHistory", JSON.stringify(raw));

  upsertEntry({
    sessionId: "current",
    jdTitle: "Backend",
    status: "done",
    overallScore: 7.0,
  });
  assert.equal(getCompletedBefore("current"), null);
});
