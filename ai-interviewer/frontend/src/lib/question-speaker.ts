const QUESTION_SPEECH_KEY = "interviewQuestionSpeechEnabled";

type StorageLike = Pick<Storage, "getItem" | "setItem" | "removeItem">;
type SpeechWindowLike = {
  speechSynthesis?: Pick<SpeechSynthesis, "cancel" | "pause" | "resume" | "speak">;
  SpeechSynthesisUtterance?: typeof SpeechSynthesisUtterance;
};
type SpeakQuestionOptions = {
  onEnd?: () => void;
  onError?: () => void;
};

function browserWindow(): SpeechWindowLike | null {
  if (typeof window === "undefined") return null;
  return window as SpeechWindowLike;
}

function browserStorage(): StorageLike | null {
  if (typeof window === "undefined") return null;
  return window.localStorage ?? null;
}

export function normalizeQuestionSpeechText(text: string): string {
  return text.replace(/\s+/g, " ").trim();
}

export function loadQuestionSpeechEnabled(storage = browserStorage()): boolean {
  if (!storage) return false;
  try {
    return storage.getItem(QUESTION_SPEECH_KEY) === "1";
  } catch {
    return false;
  }
}

export function storeQuestionSpeechEnabled(
  enabled: boolean,
  storage = browserStorage(),
): void {
  if (!storage) return;
  try {
    if (enabled) {
      storage.setItem(QUESTION_SPEECH_KEY, "1");
    } else {
      storage.removeItem(QUESTION_SPEECH_KEY);
    }
  } catch {
    /* ignore */
  }
}

export function canSpeakQuestions(win = browserWindow()): boolean {
  return Boolean(win?.speechSynthesis && win?.SpeechSynthesisUtterance);
}

export function speakQuestion(
  text: string,
  win = browserWindow(),
  options: SpeakQuestionOptions = {},
): boolean {
  const content = normalizeQuestionSpeechText(text);
  if (!content || !canSpeakQuestions(win)) return false;

  const synthesis = win!.speechSynthesis!;
  const Utterance = win!.SpeechSynthesisUtterance!;
  const utterance = new Utterance(content);
  utterance.lang = "zh-CN";
  utterance.rate = 0.95;
  utterance.pitch = 1;
  utterance.onend = () => options.onEnd?.();
  utterance.onerror = () => options.onError?.();

  try {
    synthesis.cancel();
    synthesis.speak(utterance);
    return true;
  } catch {
    return false;
  }
}

export function stopQuestionSpeech(win = browserWindow()): void {
  if (!win?.speechSynthesis) return;
  try {
    win.speechSynthesis.cancel();
  } catch {
    /* ignore */
  }
}

export function pauseQuestionSpeech(win = browserWindow()): boolean {
  if (!win?.speechSynthesis) return false;
  try {
    win.speechSynthesis.pause();
    return true;
  } catch {
    return false;
  }
}

export function resumeQuestionSpeech(win = browserWindow()): boolean {
  if (!win?.speechSynthesis) return false;
  try {
    win.speechSynthesis.resume();
    return true;
  } catch {
    return false;
  }
}
