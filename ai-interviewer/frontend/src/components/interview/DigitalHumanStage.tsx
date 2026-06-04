"use client";

import { AlertTriangle, Brain, CheckCircle2, Mic, Volume2 } from "lucide-react";
import { motion } from "framer-motion";
import { type RefObject } from "react";

import { getAvatarMotionProfile } from "@/lib/avatar/motion";
import {
  avatarStateMeta,
  mapVoicePhaseToAvatarState,
  type AvatarState,
  type VoicePhase,
} from "@/lib/avatar/state";
import { useLipSync } from "@/lib/avatar/useLipSync";

type DigitalHumanStageProps = {
  phase: VoicePhase;
  question: string | null;
  cameraOn: boolean;
  recordSecs: number;
  audioElementRef?: RefObject<HTMLAudioElement | null>;
  compact?: boolean;
};

const toneClass: Record<AvatarState, string> = {
  initializing: "border-slate-300/70 bg-slate-50 text-slate-700",
  thinking: "border-sky-300/70 bg-sky-50 text-sky-800",
  speaking: "border-emerald-300/70 bg-emerald-50 text-emerald-800",
  listening: "border-zinc-300/70 bg-zinc-50 text-zinc-800",
  listening_active: "border-amber-300/70 bg-amber-50 text-amber-900",
  closing: "border-teal-300/70 bg-teal-50 text-teal-800",
  error: "border-red-300/70 bg-red-50 text-red-800",
};

function StateIcon({ state }: { state: AvatarState }) {
  if (state === "speaking") return <Volume2 className="h-4 w-4" />;
  if (state === "listening" || state === "listening_active") {
    return <Mic className="h-4 w-4" />;
  }
  if (state === "closing") return <CheckCircle2 className="h-4 w-4" />;
  if (state === "error") return <AlertTriangle className="h-4 w-4" />;
  return <Brain className="h-4 w-4" />;
}

function VoiceEnergyBars({
  active,
  level,
}: {
  active: boolean;
  level: number;
}) {
  return (
    <div className="flex items-end gap-1" aria-label="语音能量">
      {[0, 1, 2, 3].map((idx) => (
        <motion.span
          key={idx}
          className="block w-1.5 rounded-full bg-current"
          initial={false}
          animate={{
            height: active ? 8 + Math.max(0.15, level) * (18 - idx * 2) : 8,
            opacity: active ? [0.45, 1, 0.6] : 0.35,
          }}
          transition={{
            duration: 0.9,
            repeat: active ? Infinity : 0,
            delay: idx * 0.08,
            ease: "easeOut",
          }}
        />
      ))}
    </div>
  );
}

export function DigitalHumanStage({
  phase,
  question,
  cameraOn,
  recordSecs,
  audioElementRef,
  compact = false,
}: DigitalHumanStageProps) {
  const avatarState = mapVoicePhaseToAvatarState(phase);
  const meta = avatarStateMeta[avatarState];
  const speaking = avatarState === "speaking";
  const listening = avatarState === "listening_active";
  const { mouthOpen, available: lipSyncAvailable } = useLipSync(
    audioElementRef,
    speaking,
  );
  const motionProfile = getAvatarMotionProfile(avatarState);
  const mouthWidth = speaking ? 18 + mouthOpen * 30 : listening ? 28 : 20;
  const mouthHeight = speaking ? 2 + mouthOpen * 6 : 2;
  const blinkScale = motionProfile.blinkIntervalMs > 0
    ? [1, 1, 0.12, 1, 1]
    : 1;
  const gazeShift = motionProfile.gazeShift;

  return (
    <section
      data-avatar-state={avatarState}
      className={[
        "relative overflow-hidden rounded-2xl border",
        toneClass[avatarState],
        compact ? "h-full p-4" : "p-5 md:p-6",
      ].join(" ")}
    >
      <div className="pointer-events-none absolute inset-0 opacity-70">
        <div className="absolute right-6 top-4 h-28 w-28 rounded-full bg-current/10 blur-3xl" />
        <div className="absolute bottom-0 left-8 h-20 w-40 rounded-full bg-current/5 blur-2xl" />
      </div>

      <div className={compact ? "flex h-full flex-col justify-between" : "grid gap-5 md:grid-cols-[220px_1fr]"}>
        <div className="relative flex items-center justify-center">
          <motion.div
            className="relative flex h-36 w-36 items-center justify-center rounded-[2rem] border border-current/15 bg-white/65 shadow-[0_20px_45px_-25px_rgba(15,23,42,0.45)]"
            animate={{
              y: speaking || listening ? [0, -4, 0] : 0,
              rotate: motionProfile.nodAmplitude
                ? [0, motionProfile.nodAmplitude, 0]
                : 0,
              scale: listening ? [1, motionProfile.breathingScale, 1] : 1,
            }}
            transition={{
              duration: listening ? 1.4 : 2.2,
              repeat: speaking || listening ? Infinity : 0,
              ease: "easeOut",
            }}
          >
            <div className="flex h-24 w-24 flex-col items-center justify-center rounded-full border border-current/10 bg-white/80">
              <motion.div
                className="mb-2 flex gap-3"
                aria-label="视线动作"
                animate={{ x: gazeShift }}
                transition={{ duration: 1.8, repeat: Infinity, repeatType: "mirror" }}
              >
                {[0, 1].map((eye) => (
                  <motion.span
                    key={eye}
                    className="h-2.5 w-2.5 rounded-full bg-current"
                    animate={{ scaleY: blinkScale }}
                    transition={{
                      duration: 0.18,
                      repeat: Infinity,
                      repeatDelay: Math.max(
                        1.8,
                        motionProfile.blinkIntervalMs / 1000,
                      ),
                    }}
                    style={{ transformOrigin: "center" }}
                  />
                ))}
              </motion.div>
              <motion.span
                className="h-2 rounded-full bg-current"
                animate={{ width: mouthWidth, height: mouthHeight }}
                transition={{ duration: 0.16, ease: "easeOut" }}
              />
            </div>
          </motion.div>
        </div>

        <div className="relative flex min-w-0 flex-col justify-between gap-4">
          <div className="space-y-3">
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="text-xs font-medium uppercase tracking-[0.24em] text-current/60">
                  问镜
                </p>
                <h2 className="mt-1 text-xl font-semibold tracking-tight">
                  {meta.label}
                </h2>
              </div>
              <div className="flex items-center gap-2 rounded-full border border-current/15 bg-white/55 px-3 py-1.5 text-xs font-medium">
                <StateIcon state={avatarState} />
                {cameraOn ? "视频信号已开启" : "语音模式"}
              </div>
            </div>
            <p className="max-w-[62ch] text-sm leading-6 text-current/70">
              {meta.description}
            </p>
            {!compact && question && (
              <p className="line-clamp-2 rounded-xl border border-current/10 bg-white/50 px-3 py-2 text-sm text-current/75">
                {question}
              </p>
            )}
          </div>

          <div className="flex items-center justify-between gap-4 text-xs text-current/65">
            <VoiceEnergyBars active={speaking} level={mouthOpen} />
            <span>
              {listening
                ? `录音 ${recordSecs}s`
                : lipSyncAvailable
                  ? "WebAudio 口型同步"
                  : "低延迟数字人状态机"}
            </span>
          </div>
        </div>
      </div>
    </section>
  );
}
