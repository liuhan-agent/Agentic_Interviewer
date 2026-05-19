const assert = require("node:assert/strict");
const test = require("node:test");

const {
  getMostRecentSetupDraft,
  getSetupDraft,
  getSetupDrafts,
  removeSetupDraft,
  upsertSetupDraft,
} = require("../src/lib/storage/setupDrafts.ts");

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
  const localStorage = makeStorage(initial);
  global.window = { localStorage };
  return localStorage;
}

test("setup draft storage keeps resume parse jobs separate from interview history", () => {
  const storage = installLocalStorage();

  upsertSetupDraft({
    draftId: "draft-1",
    jobId: "job-1",
    filename: "resume.pdf",
    status: "parsing",
    expiresAt: "2099-01-01T00:00:00.000Z",
    updatedAt: "2026-05-11T01:00:00.000Z",
  });

  assert.equal(storage.getItem("interviewHistory"), null);
  assert.equal(getSetupDraft("draft-1").jobId, "job-1");
  assert.equal(getSetupDrafts()[0].status, "parsing");
});

test("setup draft storage returns the most recently updated active draft", () => {
  installLocalStorage();

  upsertSetupDraft({
    draftId: "older",
    jobId: "job-older",
    filename: "old.pdf",
    status: "ready",
    expiresAt: "2099-01-01T00:00:00.000Z",
    updatedAt: "2026-05-11T01:00:00.000Z",
  });
  upsertSetupDraft({
    draftId: "newer",
    jobId: "job-newer",
    filename: "new.pdf",
    status: "parsing",
    expiresAt: "2099-01-01T00:00:00.000Z",
    updatedAt: "2026-05-11T02:00:00.000Z",
  });

  assert.equal(getMostRecentSetupDraft().draftId, "newer");
});

test("setup draft storage prunes expired drafts and supports removal", () => {
  installLocalStorage();

  upsertSetupDraft({
    draftId: "expired",
    jobId: "job-expired",
    filename: "expired.pdf",
    status: "parsing",
    expiresAt: "2000-01-01T00:00:00.000Z",
  });
  upsertSetupDraft({
    draftId: "active",
    jobId: "job-active",
    filename: "active.pdf",
    status: "ready",
    expiresAt: "2099-01-01T00:00:00.000Z",
  });

  assert.deepEqual(getSetupDrafts().map((draft) => draft.draftId), ["active"]);
  removeSetupDraft("active");
  assert.equal(getSetupDraft("active"), null);
});
