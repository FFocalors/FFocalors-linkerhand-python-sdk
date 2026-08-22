import type { VisionErrorCode } from './types';
export class VisionRuntimeError extends Error {
  readonly code: VisionErrorCode;
  readonly retryable: boolean;
  constructor(code: VisionErrorCode, message: string, retryable = true) { super(message); this.name = 'VisionRuntimeError'; this.code = code; this.retryable = retryable; }
}
export function normalizeVisionError(error: unknown): VisionRuntimeError {
  if (error instanceof VisionRuntimeError) return error;
  if (error instanceof DOMException && (error.name === 'NotAllowedError' || error.name === 'PermissionDeniedError')) return new VisionRuntimeError('CAMERA_PERMISSION_DENIED', '摄像头权限被拒绝', false);
  if (error instanceof DOMException && (error.name === 'NotFoundError' || error.name === 'DevicesNotFoundError')) return new VisionRuntimeError('CAMERA_UNAVAILABLE', '没有可用的摄像头设备', false);
  return new VisionRuntimeError('WORKER_ERROR', error instanceof Error ? error.message : String(error));
}
