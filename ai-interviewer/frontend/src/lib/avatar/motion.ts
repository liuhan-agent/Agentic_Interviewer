import type { AvatarState } from "@/lib/avatar/state";

export type AvatarMotionProfile = {
  blinkIntervalMs: number;
  nodAmplitude: number;
  gazeShift: number;
  breathingScale: number;
};

export function getAvatarMotionProfile(state: AvatarState): AvatarMotionProfile {
  switch (state) {
    case "speaking":
      return {
        blinkIntervalMs: 3600,
        nodAmplitude: 1.5,
        gazeShift: 2,
        breathingScale: 1.01,
      };
    case "listening_active":
      return {
        blinkIntervalMs: 4200,
        nodAmplitude: 3,
        gazeShift: -2,
        breathingScale: 1.025,
      };
    case "thinking":
      return {
        blinkIntervalMs: 5000,
        nodAmplitude: 0,
        gazeShift: 4,
        breathingScale: 1.015,
      };
    case "error":
      return {
        blinkIntervalMs: 0,
        nodAmplitude: 0,
        gazeShift: 0,
        breathingScale: 1,
      };
    default:
      return {
        blinkIntervalMs: 4600,
        nodAmplitude: 0.8,
        gazeShift: 0,
        breathingScale: 1.01,
      };
  }
}
