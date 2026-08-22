import { FilesetResolver, HandLandmarker } from '@mediapipe/tasks-vision';
import type { HandLandmark, VisionLandmarkResult, VisionWorkerRequest, VisionWorkerResponse } from '../../shared/vision-runtime';

type WorkerScope = { onmessage: ((event: MessageEvent<VisionWorkerRequest>) => void) | null; postMessage(message: VisionWorkerResponse): void };
const scope = self as unknown as WorkerScope;
let landmarker: HandLandmarker | undefined;

function errorResponse(requestId: string, code: string, message: string): VisionWorkerResponse { return { type: 'error', requestId, code, message }; }

async function initialise(request: Extract<VisionWorkerRequest, { type: 'init' }>) {
  const vision = await FilesetResolver.forVisionTasks(request.wasmRootUrl);
  landmarker = await HandLandmarker.createFromOptions(vision, {
    baseOptions: { modelAssetPath: request.modelAssetUrl },
    runningMode: 'VIDEO', numHands: request.numHands,
    minHandDetectionConfidence: request.minHandDetectionConfidence,
    minHandPresenceConfidence: request.minHandPresenceConfidence,
    minTrackingConfidence: request.minTrackingConfidence,
  });
}

function toLandmarks(result: { landmarks?: Array<Array<{ x: number; y: number; z: number }>>; handednesses?: Array<Array<{ categoryName?: string; score?: number }>> }): HandLandmark[] {
  return (result.landmarks ?? []).map((landmarks, index) => ({
    handedness: result.handednesses?.[index]?.[0]?.categoryName === 'Left' ? 'left' : 'right',
    confidence: result.handednesses?.[index]?.[0]?.score ?? 0,
    landmarks: landmarks.map(({ x, y, z }) => ({ x, y, z })),
  }));
}

scope.onmessage = async (event) => {
  const request = event.data;
  if (request.type === 'init') {
    try { await initialise(request); scope.postMessage({ type: 'ready', requestId: request.requestId }); }
    catch (error) { scope.postMessage(errorResponse(request.requestId, 'MODEL_LOAD_FAILED', error instanceof Error ? error.message : String(error))); }
    return;
  }
  if (request.type !== 'frame') return;
  if (!landmarker) {
    request.bitmap.close();
    scope.postMessage(errorResponse(request.requestId, 'MODEL_NOT_READY', 'HandLandmarker is not ready'));
    return;
  }
  try {
    // VIDEO mode passes a monotonic timestamp so MediaPipe can track between frames.
    const detected = landmarker.detectForVideo(request.bitmap, request.monotonicTimeMs);
    const result: VisionLandmarkResult = { source: request.source, frameSequence: request.frameSequence, monotonicTimeMs: request.monotonicTimeMs, fps: request.fps, droppedFrames: request.droppedFrames, inflight: 1, hands: toLandmarks(detected) };
    scope.postMessage({ type: 'result', requestId: request.requestId, result });
  } catch (error) { scope.postMessage(errorResponse(request.requestId, 'WORKER_INFERENCE_FAILED', error instanceof Error ? error.message : String(error))); }
  finally { request.bitmap.close(); }
};
