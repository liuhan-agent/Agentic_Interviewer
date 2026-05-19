const assert = require("node:assert/strict");
const test = require("node:test");

const {
  loadQuestionSpeechEnabled,
  normalizeQuestionSpeechText,
  pauseQuestionSpeech,
  resumeQuestionSpeech,
  speakQuestion,
  stopQuestionSpeech,
  storeQuestionSpeechEnabled,
} = require("../src/lib/question-speaker.ts");

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

function makeSpeechWindow() {
  const spoken = [];
  let cancelCount = 0;
  let pauseCount = 0;
  let resumeCount = 0;
  class FakeUtterance {
    constructor(text) {
      this.text = text;
      this.lang = "";
      this.rate = 0;
      this.pitch = 0;
    }
  }
  return {
    SpeechSynthesisUtterance: FakeUtterance,
    speechSynthesis: {
      speak(utterance) {
        spoken.push(utterance);
      },
      cancel() {
        cancelCount += 1;
      },
      pause() {
        pauseCount += 1;
      },
      resume() {
        resumeCount += 1;
      },
    },
    get spoken() {
      return spoken;
    },
    get cancelCount() {
      return cancelCount;
    },
    get pauseCount() {
      return pauseCount;
    },
    get resumeCount() {
      return resumeCount;
    },
  };
}

test("normalizes question text before speaking", () => {
  assert.equal(
    normalizeQuestionSpeechText("  请介绍一下\n\n你做过的  项目。 "),
    "请介绍一下 你做过的 项目。",
  );
});

test("stores and reads the question speech preference", () => {
  const storage = makeStorage();

  assert.equal(loadQuestionSpeechEnabled(storage), false);
  storeQuestionSpeechEnabled(true, storage);
  assert.equal(loadQuestionSpeechEnabled(storage), true);
  storeQuestionSpeechEnabled(false, storage);
  assert.equal(loadQuestionSpeechEnabled(storage), false);
});

test("speakQuestion cancels previous speech and uses Chinese voice settings", () => {
  const win = makeSpeechWindow();

  assert.equal(speakQuestion(" 请读这道题 ", win), true);
  assert.equal(win.cancelCount, 1);
  assert.equal(win.spoken.length, 1);
  assert.equal(win.spoken[0].text, "请读这道题");
  assert.equal(win.spoken[0].lang, "zh-CN");
  assert.equal(win.spoken[0].rate, 0.95);
  assert.equal(win.spoken[0].pitch, 1);
});

test("speakQuestion notifies when browser speech ends", () => {
  const win = makeSpeechWindow();
  let ended = false;

  assert.equal(
    speakQuestion("请读这道题", win, {
      onEnd: () => {
        ended = true;
      },
    }),
    true,
  );
  win.spoken[0].onend();

  assert.equal(ended, true);
});

test("speakQuestion fails quietly without browser speech support", () => {
  assert.equal(speakQuestion("请读这道题", {}), false);
  assert.equal(speakQuestion("   ", makeSpeechWindow()), false);
});

test("stopQuestionSpeech cancels current browser speech", () => {
  const win = makeSpeechWindow();

  stopQuestionSpeech(win);

  assert.equal(win.cancelCount, 1);
});

test("pause and resume question speech use browser controls", () => {
  const win = makeSpeechWindow();

  pauseQuestionSpeech(win);
  resumeQuestionSpeech(win);

  assert.equal(win.pauseCount, 1);
  assert.equal(win.resumeCount, 1);
});
