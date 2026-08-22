export type VisionSource = 'vision' | 'rps';
export type VisionRuntimeState = 'idle' | 'loading' | 'running' | 'suspended' | 'stopping' | 'error' | 'permission-denied' | 'device-lost';
export type VisionErrorCode = 'VISION_BUSY' | 'INVALID_STATE' | 'CAMERA_UNAVAILABLE' | 'CAMERA_PERMISSION_DENIED' | 'CAMERA_DEVICE_LOST' | 'MODEL_LOAD_FAILED' | 'MODEL_NOT_READY' | 'WORKER_ERROR' | 'WORKER_INFERENCE_FAILED' | 'RESOURCE_MISSING';
export type Landmark = { x: number; y: number; z: number };
export type HandLandmark = { handedness: 'left' | 'right'; confidence: number; landmarks: Landmark[] };
export type VisionLandmarkResult = { source: VisionSource; hands: HandLandmark[]; monotonicTimeMs: number; frameSequence: number; fps: number | null; droppedFrames: number; inflight: 0 | 1 };
export type VisionWorkerRequest =
  | { type: 'init'; requestId: string; modelAssetUrl: string; wasmRootUrl: string; numHands: number; minHandDetectionConfidence: number; minHandPresenceConfidence: number; minTrackingConfidence: number }
  | { type: 'frame'; requestId: string; frameSequence: number; monotonicTimeMs: number; fps: number | null; droppedFrames: number; source: VisionSource; bitmap: ImageBitmap };
export type VisionWorkerResponse =
  | { type: 'ready'; requestId: string }
  | { type: 'result'; requestId: string; result: VisionLandmarkResult }
  | { type: 'error'; requestId: string; code: string; message: string };
export type VisionRuntimeSnapshot = { state: VisionRuntimeState; owner: VisionSource | null; cameraDeviceId: string | null; model: 'unloaded' | 'loading' | 'ready'; frameSequence: number; fps: number | null; droppedFrames: number; inflight: 0 | 1; lastError: { code: VisionErrorCode; message: string } | null };
export type VisionRuntimeOptions = { modelAssetUrl?: string; wasmRootUrl?: string; numHands?: number; minHandDetectionConfidence?: number; minHandPresenceConfidence?: number; minTrackingConfidence?: number };
