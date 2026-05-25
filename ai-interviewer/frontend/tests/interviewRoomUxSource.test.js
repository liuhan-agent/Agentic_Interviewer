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
const layoutSource = fs.readFileSync(
  path.join(__dirname, "..", "src", "app", "layout.tsx"),
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
  assert.match(layoutSource, /<main id="app-main-content"/);
  assert.match(wheelSource, /aria-controls="app-main-content"/);
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
  assert.match(source, /answerExpanded \?/);
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
  assert.match(source, /<NextQuestionLoader\s+etaMs=\{state\.lastServerLatencyMs\}\s+isFinalTurn=\{finalTurnSubmitted\}\s+answerInsight=\{latestSubmittedAnswerInsight\}/);
});

test("interview room separates retry processing from status refresh copy", () => {
  assert.match(source, /onClick=\{handleRetryQuestionGeneration\}/);
  assert.match(source, /继续处理/);
  assert.match(source, /onClick=\{\(\) => router\.refresh\(\)\}/);
  assert.match(source, /刷新状态/);
  assert.doesNotMatch(source, /重试连接/);
});

test("interview room passes stable local answer insight while loading", () => {
  assert.match(source, /const latestSubmittedAnswerInsight =/);
  assert.match(source, /answerInsightFromHistory\(history\)/);
  assert.doesNotMatch(source, /answerInsightFromHistory\(history, finalTurnSubmitted\)/);
  assert.match(source, /function answerInsightFromHistory/);
  assert.doesNotMatch(source, /if \(finalTurnSubmitted\) return null/);
  assert.match(source, /const isOpeningTurn = entry\.questionType === "self_intro"/);
  assert.match(source, /const dimensionId = isOpeningTurn[\s\S]*\? null[\s\S]*: entry\.dimension/);
  assert.match(source, /const dimensionLabel = isOpeningTurn[\s\S]*\? null[\s\S]*: entry\.dimension/);
  assert.match(source, /formatDimensionName\(entry\.dimension\)/);
  assert.match(source, /dimensionId,/);
  assert.match(source, /isOpeningTurn,?/);
  assert.match(source, /answer === "已跳过本题"/);
  assert.doesNotMatch(source, /function extractAnswerKeywords/);
  assert.doesNotMatch(source, /ANSWER_KEYWORD_MAX_COUNT/);
  assert.doesNotMatch(source, /ANSWER_TECHNICAL_KEYWORD_RULES/);
  assert.doesNotMatch(source, /keywords,/);
  assert.match(source, /return null/);
});

test("interview room loads waiting tips once and tracks shown tips in memory", () => {
  assert.match(source, /import[\s\S]*listInterviewWaitingTips[\s\S]*from "@\/lib\/api\/interview"/);
  assert.match(source, /InterviewWaitingTipsResponse/);
  assert.match(source, /const \[waitingTipsResponse, setWaitingTipsResponse\] =\s*useState<InterviewWaitingTipsResponse \| null>\(null\)/);
  assert.match(source, /const displayedWaitingTipIdsRef = useRef<Set<string>>\(new Set\(\)\)/);
  assert.match(source, /listInterviewWaitingTips\(\)/);
  assert.match(source, /setWaitingTipsResponse/);
  assert.match(source, /function handleWaitingTipShown\(tipId: string\)/);
  assert.match(source, /displayedWaitingTipIdsRef\.current\.add\(tipId\)/);
  assert.match(source, /waitingTips=\{waitingTipsResponse\?\.tips \?\? null\}/);
  assert.match(source, /displayedTipIds=\{displayedWaitingTipIdsRef\.current\}/);
  assert.match(source, /onWaitingTipShown=\{handleWaitingTipShown\}/);
});

test("video interview is attached to the real answer path as a weak side channel", () => {
  assert.match(source, /useTurnVideoCapture/);
  assert.match(source, /state\.phase === "waiting_for_answer" \? state\.turnIdx : null/);
  assert.match(source, /const videoCapture = useTurnVideoCapture/);
  assert.match(source, /<VideoPreviewPanel[\s\S]*videoCapture\.cameraOn/);
  assert.match(source, /finishTurnCapture=\{videoCapture\.finishTurnCapture\}/);
  assert.match(source, /clearTurnCapture=\{videoCapture\.clearTurnCapture\}/);
  assert.doesNotMatch(source, /enableVideoAnalysis=\{state\.enableVideoAnalysis\}/);
  assert.doesNotMatch(source, /function AnswerBox[\s\S]*useTurnVideoCapture\(\{/);
  assert.match(source, /onSubmit: \(text: string, videoSignals\?: AggregatedVideoSignal \| null\) => Promise<boolean>/);
  assert.match(source, /submitAnswer\(sessionId, text, state\.turnIdx, videoSignals/);
  assert.match(source, /finishTurnCapture\(\)/);
  assert.match(source, /clearTurnCapture\(\)/);
  assert.match(source, /function VideoPreviewPanel/);
  assert.match(source, /fixed right-6 top-20/);
  assert.match(source, /hidden xl:block/);
  assert.match(source, /xl:hidden/);
  assert.match(source, /TooltipProvider delayDuration=\{150\}/);
  assert.match(source, /TooltipContent side="bottom"/);
  assert.doesNotMatch(source, /TooltipContent side="left"/);
  assert.match(source, /关闭摄像头会清空当前题已采集的视频信号/);
  assert.match(source, /开启摄像头后，本题会尝试采集本地视频信号/);
  assert.doesNotMatch(source, /title=\{/);
});
