const API_BASE = "/api/v1/interview";

const DEFAULT_CANDIDATE = {
  name: "Alex Chen",
  email_hash: "sha256:demo",
  resume_parsed: {
    summary: "5y senior backend engineer; payments, messaging, schema registry.",
    skills: ["python", "go", "postgres", "kafka", "kubernetes", "redis"],
    highlights: [
      "Led migration of monolithic payments to event-driven microservices.",
      "Authored company-wide schema registry adopted by 12 teams.",
    ],
  },
};

const DEFAULT_JOB = {
  title: "Senior Backend Engineer",
  level: "senior",
  required_skills: ["python", "system_design", "databases"],
  rubric_dimensions: ["technical_depth", "system_design", "leadership"],
  rubric: {
    technical_depth: "Goes beyond APIs; concrete failure modes.",
    system_design: "Scope, decompose, trade-offs.",
    leadership: "Owns outcomes and grows teammates.",
  },
};

const $ = (id) => document.getElementById(id);
const setStatus = (s) => ($("status").textContent = s);

let sessionId = null;
let pollAbort = null;
let mediaRecorder = null;
let recordedChunks = [];
let ws = null;

document.addEventListener("DOMContentLoaded", () => {
  $("candidate").value = JSON.stringify(DEFAULT_CANDIDATE, null, 2);
  $("job_spec").value = JSON.stringify(DEFAULT_JOB, null, 2);

  $("start-btn").addEventListener("click", startSession);
  $("submit-btn").addEventListener("click", submitTextAnswer);
  $("record-btn").addEventListener("click", startRecording);
  $("stop-btn").addEventListener("click", stopRecordingAndSend);
});

async function startSession() {
  try {
    const candidate = JSON.parse($("candidate").value);
    const job_spec = JSON.parse($("job_spec").value);
    const body = {
      candidate,
      job_spec,
      max_turns: parseInt($("max_turns").value, 10),
      quality_threshold: parseFloat($("threshold").value),
      turn_budget: parseInt($("budget").value, 10),
    };
    const res = await fetch(`${API_BASE}/sessions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    sessionId = data.session_id;
    $("session_id").textContent = sessionId;
    setStatus("running");
    $("run").classList.remove("hidden");
    openVoiceSocket();
    pollLoop();
  } catch (e) {
    alert("Start failed: " + e.message);
  }
}

async function pollLoop() {
  while (sessionId) {
    try {
      const res = await fetch(`${API_BASE}/sessions/${sessionId}/question?timeout=30`);
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      $("turn_idx").textContent = data.turn_idx ?? "-";
      if (data.status === "completed") {
        setStatus("completed");
        showReport(data.final_report);
        return;
      }
      if (data.question) {
        setStatus(data.status);
        appendQuestion(data.turn_idx, data.question.question, data.question.dimension);
        return;
      }
    } catch (e) {
      console.error("poll failed", e);
      setStatus("error: " + e.message);
      return;
    }
  }
}

async function submitTextAnswer() {
  const answer = $("answer").value.trim();
  if (!answer) return;
  $("answer").value = "";
  appendAnswer($("turn_idx").textContent, answer);
  await postAnswer(answer);
  pollLoop();
}

async function postAnswer(answer) {
  const res = await fetch(`${API_BASE}/sessions/${sessionId}/answer`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ answer }),
  });
  if (!res.ok) {
    const text = await res.text();
    console.error("answer rejected", text);
    setStatus("error: " + text);
  }
}

function openVoiceSocket() {
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${scheme}://${location.host}/ws/voice/${sessionId}`);
  ws.binaryType = "arraybuffer";
  const audioEl = $("tts-player");
  const chunks = [];
  ws.addEventListener("message", (ev) => {
    if (typeof ev.data === "string") {
      try {
        const msg = JSON.parse(ev.data);
        if (msg.type === "question") {
          appendQuestion(msg.turn_idx, msg.content, msg.dimension);
        } else if (msg.type === "transcript") {
          appendSys("Transcript: " + msg.content);
        } else if (msg.type === "final_report") {
          showReport(msg.report);
        }
      } catch { /* ignore */ }
    } else {
      chunks.push(ev.data);
      const blob = new Blob(chunks);
      audioEl.src = URL.createObjectURL(blob);
    }
  });
  ws.addEventListener("close", () => appendSys("voice channel closed"));
}

async function startRecording() {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  recordedChunks = [];
  mediaRecorder = new MediaRecorder(stream);
  mediaRecorder.ondataavailable = (e) => {
    if (e.data.size > 0) recordedChunks.push(e.data);
  };
  mediaRecorder.start();
  $("record-btn").disabled = true;
  $("stop-btn").disabled = false;
}

async function stopRecordingAndSend() {
  return new Promise((resolve) => {
    mediaRecorder.onstop = async () => {
      const blob = new Blob(recordedChunks);
      const buffer = await blob.arrayBuffer();
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(buffer);
        ws.send(JSON.stringify({ type: "stop" }));
      } else {
        alert("WebSocket not open");
      }
      $("record-btn").disabled = false;
      $("stop-btn").disabled = true;
      resolve();
    };
    mediaRecorder.stop();
  });
}

function appendQuestion(turn, text, dim) {
  const el = document.createElement("div");
  el.className = "q";
  el.textContent = `[turn ${turn} | ${dim || "?"}] Q: ${text}`;
  $("qa-list").appendChild(el);
  $("qa-list").scrollTop = $("qa-list").scrollHeight;
}
function appendAnswer(turn, text) {
  const el = document.createElement("div");
  el.className = "a";
  el.textContent = `[turn ${turn}] A: ${text}`;
  $("qa-list").appendChild(el);
  $("qa-list").scrollTop = $("qa-list").scrollHeight;
}
function appendSys(text) {
  const el = document.createElement("div");
  el.className = "sys";
  el.textContent = text;
  $("qa-list").appendChild(el);
  $("qa-list").scrollTop = $("qa-list").scrollHeight;
}
function showReport(report) {
  $("report").classList.remove("hidden");
  $("report-pre").textContent = JSON.stringify(report, null, 2);
}
