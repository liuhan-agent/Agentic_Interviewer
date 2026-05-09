const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const source = fs.readFileSync(
  path.join(__dirname, "..", "src", "components", "interview", "InterviewRoom.tsx"),
  "utf8",
);
const voiceSource = fs.readFileSync(
  path.join(__dirname, "..", "src", "components", "interview", "VoiceRoom.tsx"),
  "utf8",
);
const shellSource = fs.readFileSync(
  path.join(__dirname, "..", "src", "components", "layout", "AppShell.tsx"),
  "utf8",
);
const wheelSource = fs.readFileSync(
  path.join(__dirname, "..", "src", "components", "layout", "LightScrollWheel.tsx"),
  "utf8",
);
const answerBubbleSource = fs.readFileSync(
  path.join(
    __dirname,
    "..",
    "src",
    "components",
    "interview",
    "CollapsibleAnswerBubble.tsx",
  ),
  "utf8",
);

test("app shell mounts a global lightweight scroll wheel", () => {
  assert.match(shellSource, /import \{ LightScrollWheel \}/);
  assert.match(shellSource, /<LightScrollWheel \/>/);
  assert.match(wheelSource, /ScrollBehavior = "smooth"/);
  assert.match(wheelSource, /opacity-40/);
  assert.match(wheelSource, /hover:opacity-100/);
  assert.match(wheelSource, /h-14 w-4 rounded-full/);
  assert.match(wheelSource, /role="scrollbar"/);
  assert.match(wheelSource, /aria-valuenow=\{Math\.round\(progress \* 100\)\}/);
  assert.match(wheelSource, /const draggingRef = useRef\(false\)/);
  assert.match(wheelSource, /const thumbRef = useRef<HTMLSpanElement>\(null\)/);
  assert.match(wheelSource, /function syncThumbPosition/);
  assert.match(wheelSource, /translate3d\(-50%, \$\{thumbTop\}px, 0\)/);
  assert.match(wheelSource, /rect\.height - THUMB_SIZE_PX/);
  assert.match(wheelSource, /clientY - rect\.top - THUMB_SIZE_PX \/ 2/);
  assert.doesNotMatch(wheelSource, /progress \* THUMB_SIZE_PX/);
  assert.match(wheelSource, /draggingRef\.current = true/);
  assert.match(wheelSource, /draggingRef\.current = false/);
  assert.match(wheelSource, /touch-none select-none/);
  assert.match(wheelSource, /top-10 .* bottom-8/);
  assert.match(wheelSource, /h-full w-8 cursor-grab/);
  assert.match(wheelSource, /event\.preventDefault\(\)/);
  assert.doesNotMatch(wheelSource, /transition-\[top,transform\]/);
  assert.match(wheelSource, /onPointerDown/);
  assert.match(wheelSource, /onPointerMove/);
  assert.match(wheelSource, /onPointerUp/);
  assert.doesNotMatch(wheelSource, /ArrowUpToLine/);
  assert.doesNotMatch(wheelSource, /ArrowDownToLine/);
  assert.doesNotMatch(wheelSource, /ArrowUp className/);
  assert.doesNotMatch(wheelSource, /ArrowDown className/);
  assert.doesNotMatch(source, /function InterviewScrollWheel/);
});

test("answer box can expand and collapse long answers", () => {
  assert.match(source, /const \[answerExpanded, setAnswerExpanded\] = useState\(false\)/);
  assert.match(source, /aria-expanded=\{answerExpanded\}/);
  assert.match(source, /maxRows=\{answerExpanded \? 24 : 8\}/);
  assert.match(source, /answerExpanded \? "收起" : "展开"/);
});

test("submitted long answer bubbles use a shared expand/collapse component", () => {
  assert.match(source, /import \{ CollapsibleAnswerBubble \}/);
  assert.match(voiceSource, /import \{ CollapsibleAnswerBubble \}/);
  assert.match(source, /<CollapsibleAnswerBubble\s+text=\{entry\.answer\}/);
  assert.match(voiceSource, /<CollapsibleAnswerBubble\s+text=\{entry\.answer\}/);
  assert.match(answerBubbleSource, /ANSWER_COLLAPSE_CHAR_LIMIT/);
  assert.match(answerBubbleSource, /ANSWER_COLLAPSE_LINE_LIMIT/);
  assert.match(answerBubbleSource, /const shouldCollapseAnswer =/);
  assert.match(answerBubbleSource, /shouldCollapseAnswer\s*&&\s*!answerExpanded/);
  assert.match(answerBubbleSource, /max-h-72 overflow-hidden/);
  assert.match(answerBubbleSource, /\[mask-image:linear-gradient\(to_bottom,black_75%,transparent\)\]/);
  assert.match(answerBubbleSource, /mt-3 flex justify-end border-t/);
  assert.match(answerBubbleSource, /border-primary\/5/);
  assert.match(answerBubbleSource, /text-emerald-300\/60/);
  assert.match(answerBubbleSource, /bg-emerald-500\/\[0\.03\]/);
  assert.match(answerBubbleSource, /text-\[11px\] font-normal/);
  assert.doesNotMatch(answerBubbleSource, /className="ml-auto h-7/);
  assert.doesNotMatch(answerBubbleSource, /text-xs text-primary hover:text-primary/);
});

test("interview room detects final submitted turn for final-report loading copy", () => {
  assert.match(source, /const \[finalTurnSubmitted, setFinalTurnSubmitted\] = useState\(false\)/);
  assert.match(source, /isFinalFormalTurn\(/);
  assert.match(source, /<NextQuestionLoader\s+etaMs=\{state\.lastServerLatencyMs\}\s+isFinalTurn=\{finalTurnSubmitted\}/);
});
