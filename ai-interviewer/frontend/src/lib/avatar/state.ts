export type VoicePhase =
  | "connecting"
  | "awaiting_question"
  | "playing_question"
  | "ready_to_record"
  | "recording"
  | "uploading"
  | "reviewing_transcript"
  | "completed"
  | "error";

export type AvatarState =
  | "initializing"
  | "thinking"
  | "speaking"
  | "listening"
  | "listening_active"
  | "closing"
  | "error";

export type AvatarStateMeta = {
  label: string;
  description: string;
  tone: "neutral" | "active" | "calm" | "warning" | "complete";
};

export function mapVoicePhaseToAvatarState(phase: VoicePhase): AvatarState {
  switch (phase) {
    case "playing_question":
      return "speaking";
    case "ready_to_record":
      return "listening";
    case "recording":
      return "listening_active";
    case "uploading":
      return "thinking";
    case "reviewing_transcript":
      return "thinking";
    case "awaiting_question":
      return "thinking";
    case "completed":
      return "closing";
    case "error":
      return "error";
    case "connecting":
    default:
      return "initializing";
  }
}

export const avatarStateMeta: Record<AvatarState, AvatarStateMeta> = {
  initializing: {
    label: "正在建立连接",
    description: "准备面试官语音与会话状态",
    tone: "neutral",
  },
  thinking: {
    label: "正在思考",
    description: "分析当前轮次并准备下一步问题",
    tone: "calm",
  },
  speaking: {
    label: "正在提问",
    description: "请听完题目后再开始作答",
    tone: "active",
  },
  listening: {
    label: "等待作答",
    description: "准备好后开始录音，空格键也可以控制录制",
    tone: "neutral",
  },
  listening_active: {
    label: "正在聆听",
    description: "保持自然表达，系统会在本轮结束后分析回答",
    tone: "active",
  },
  closing: {
    label: "面试结束",
    description: "正在生成最终报告",
    tone: "complete",
  },
  error: {
    label: "需要处理连接",
    description: "语音通道遇到问题，可以重连或切回文本面试",
    tone: "warning",
  },
};
