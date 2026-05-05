import type { VideoSignal } from "./types";

type FaceMeshResults = {
  multiFaceLandmarks?: Array<Array<{ x: number; y: number; z: number }>>;
};

let faceMeshInstance: any = null;
let loadPromise: Promise<any> | null = null;

async function loadFaceMesh(): Promise<any> {
  if (faceMeshInstance) return faceMeshInstance;
  if (loadPromise) return loadPromise;

  loadPromise = (async () => {
    try {
      const { FaceMesh } = await import("@mediapipe/face_mesh");
      const fm = new FaceMesh({
        locateFile: (file: string) =>
          `https://cdn.jsdelivr.net/npm/@mediapipe/face_mesh/${file}`,
      });
      fm.setOptions({
        maxNumFaces: 1,
        refineLandmarks: true,
        minDetectionConfidence: 0.5,
        minTrackingConfidence: 0.5,
      });
      faceMeshInstance = fm;
      return fm;
    } catch {
      loadPromise = null;
      return null;
    }
  })();

  return loadPromise;
}

function deriveSignal(
  landmarks: Array<{ x: number; y: number; z: number }>,
): VideoSignal {
  const noseTip = landmarks[1];
  const leftEye = landmarks[33];
  const rightEye = landmarks[263];
  const mouthLeft = landmarks[61];
  const mouthRight = landmarks[291];
  const leftBrow = landmarks[70];
  const rightBrow = landmarks[300];
  const leftEyeTop = landmarks[159];
  const leftEyeBottom = landmarks[145];

  const eyeCenter = {
    x: (leftEye.x + rightEye.x) / 2,
    y: (leftEye.y + rightEye.y) / 2,
  };
  const gazeDeviation = Math.abs(noseTip.x - 0.5) + Math.abs(noseTip.y - 0.5);
  const engagement = Math.max(0, Math.min(1, 1 - gazeDeviation * 2));

  const headTilt = Math.abs(leftEye.y - rightEye.y);
  const browRaise =
    (Math.abs(leftBrow.y - leftEye.y) + Math.abs(rightBrow.y - rightEye.y)) / 2;
  const headStability = 1 - Math.min(1, headTilt * 10);
  const confidence = Math.max(0, Math.min(1, headStability * 0.6 + (1 - gazeDeviation) * 0.4));

  const mouthWidth = Math.abs(mouthRight.x - mouthLeft.x);
  const mouthOpenness = Math.abs(landmarks[13].y - landmarks[14].y);
  const eyeOpenness = Math.abs(leftEyeTop.y - leftEyeBottom.y);

  let emotion: VideoSignal["emotion"] = "neutral";
  if (mouthWidth > 0.06 && mouthOpenness > 0.01) {
    emotion = "positive";
  } else if (browRaise < 0.02 && eyeOpenness < 0.015) {
    emotion = "nervous";
  } else if (browRaise > 0.04) {
    emotion = "confused";
  }

  return {
    confidence: Math.round(confidence * 100) / 100,
    engagement: Math.round(engagement * 100) / 100,
    emotion,
    timestamp: Date.now(),
  };
}

export type AnalyzeResult =
  | { ok: true; signal: VideoSignal }
  | { ok: false };

export async function analyzeFrame(
  video: HTMLVideoElement,
): Promise<AnalyzeResult> {
  const fm = await loadFaceMesh();
  if (!fm) return { ok: false };

  return new Promise<AnalyzeResult>((resolve) => {
    let resolved = false;
    const timeout = setTimeout(() => {
      if (!resolved) {
        resolved = true;
        resolve({ ok: false });
      }
    }, 3000);

    fm.onResults((results: FaceMeshResults) => {
      if (resolved) return;
      resolved = true;
      clearTimeout(timeout);

      if (!results.multiFaceLandmarks?.length) {
        resolve({ ok: false });
        return;
      }
      const signal = deriveSignal(results.multiFaceLandmarks[0]);
      resolve({ ok: true, signal });
    });

    fm.send({ image: video }).catch(() => {
      if (!resolved) {
        resolved = true;
        clearTimeout(timeout);
        resolve({ ok: false });
      }
    });
  });
}

export function isMediaPipeAvailable(): boolean {
  return typeof window !== "undefined" && !!window.WebAssembly;
}

export async function preloadFaceMesh(): Promise<boolean> {
  const fm = await loadFaceMesh();
  return fm !== null;
}
