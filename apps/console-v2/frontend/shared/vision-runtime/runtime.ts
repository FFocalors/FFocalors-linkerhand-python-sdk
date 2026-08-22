import { SingleFrameGate } from './backpressure';
import { normalizeVisionAssetRootUrl, visionAssetUrl } from './asset-paths';
import { normalizeVisionError, VisionRuntimeError } from './errors';
import type { VisionErrorCode, VisionLandmarkResult, VisionRuntimeOptions, VisionRuntimeSnapshot, VisionRuntimeState, VisionSource, VisionWorkerRequest, VisionWorkerResponse } from './types';

type WorkerLike = { onmessage: ((event: MessageEvent<VisionWorkerResponse>) => void) | null; onerror: ((event: ErrorEvent) => void) | null; postMessage(message: VisionWorkerRequest, transfer?: Transferable[]): void; terminate(): void };
type MediaDevicesLike = Pick<MediaDevices, 'getUserMedia'>;
type VideoWithFrameCallback = HTMLVideoElement & { requestVideoFrameCallback?: (callback: (now: number) => void) => number; cancelVideoFrameCallback?: (handle: number) => void };
type RuntimeListener = (snapshot: VisionRuntimeSnapshot) => void;
type ResultListener = (result: VisionLandmarkResult) => void;

const defaultOptions: Required<VisionRuntimeOptions> = { modelAssetUrl: visionAssetUrl('vision/hand_landmarker.task'), wasmRootUrl: normalizeVisionAssetRootUrl(visionAssetUrl('vision/wasm')), numHands: 2, minHandDetectionConfidence: .5, minHandPresenceConfidence: .5, minTrackingConfidence: .5 };

export class VisionRuntime {
  private readonly options: Required<VisionRuntimeOptions>;
  private readonly mediaDevices: MediaDevicesLike;
  private readonly workerFactory: () => WorkerLike;
  private readonly now: () => number;
  private worker: WorkerLike | null = null;
  private video: VideoWithFrameCallback | null = null;
  private stream: MediaStream | null = null;
  private owner: VisionSource | null = null;
  private frameHandle: number | null = null;
  private frameSequence = 0;
  private fps: number | null = null;
  private lastFrameTime: number | null = null;
  private state: VisionRuntimeState = 'idle';
  private model: VisionRuntimeSnapshot['model'] = 'unloaded';
  private lastError: VisionRuntimeSnapshot['lastError'] = null;
  private startPromise: Promise<void> | null = null;
  private generation = 0;
  private disposed = false;
  private pendingWorkerInit: { generation: number; reject: (error: unknown) => void; cancel: () => void } | null = null;
  private startPromiseGeneration: number | null = null;
  private readonly gate = new SingleFrameGate();
  private readonly listeners = new Set<RuntimeListener>();
  private readonly resultListeners = new Set<ResultListener>();

  constructor(options: VisionRuntimeOptions = {}, dependencies: { mediaDevices?: MediaDevicesLike; workerFactory: () => WorkerLike; now?: () => number }) {
    this.options = { ...defaultOptions, ...options, wasmRootUrl: normalizeVisionAssetRootUrl(options.wasmRootUrl ?? defaultOptions.wasmRootUrl) };
    this.mediaDevices = dependencies.mediaDevices ?? navigator.mediaDevices;
    // The bundled worker is intentionally classic: MediaPipe's official
    // Emscripten loader uses importScripts and exposes ModuleFactory globally.
    this.workerFactory = dependencies.workerFactory;
    this.now = dependencies.now ?? (() => performance.now());
    if (typeof document !== 'undefined') document.addEventListener('visibilitychange', this.handleVisibilityChange);
  }

  subscribe(listener: RuntimeListener): () => void { this.listeners.add(listener); listener(this.snapshot()); return () => this.listeners.delete(listener); }
  onResult(listener: ResultListener): () => void { this.resultListeners.add(listener); return () => this.resultListeners.delete(listener); }
  snapshot(): VisionRuntimeSnapshot { return { state: this.state, owner: this.owner, cameraDeviceId: this.stream?.getVideoTracks()[0]?.getSettings().deviceId ?? null, model: this.model, frameSequence: this.frameSequence, fps: this.fps, droppedFrames: this.gate.droppedFrames, inflight: this.gate.inFlight, lastError: this.lastError }; }

  start(video: HTMLVideoElement, source: VisionSource, deviceId?: string): Promise<void> {
    if (this.disposed) return Promise.reject(new VisionRuntimeError('INVALID_STATE', '视觉 Runtime 已释放', false));
    if (this.owner && this.owner !== source) return Promise.reject(new VisionRuntimeError('VISION_BUSY', `视觉输入当前由 ${this.owner} 占用`, true));
    // A running session owns the video element as well as the camera. Silently
    // replacing this.video would leave the stream attached to the old element
    // while stop/cancel would target the new one, so same-owner starts are only
    // idempotent for the exact same element.
    if (this.owner === source && this.video && this.video !== video) return Promise.reject(new VisionRuntimeError('INVALID_STATE', '当前视觉会话已绑定另一个视频元素', true));
    if (this.startPromise) return this.startPromise;
    if (this.state === 'running' || this.state === 'suspended') return Promise.resolve();
    this.owner = source;
    this.video = video as VideoWithFrameCallback;
    const generation = ++this.generation;
    const promise = this.startInternal(deviceId, generation);
    this.startPromise = promise;
    this.startPromiseGeneration = generation;
    void promise.then(() => { if (this.startPromise === promise) { this.startPromise = null; this.startPromiseGeneration = null; } }, () => { if (this.startPromise === promise) { this.startPromise = null; this.startPromiseGeneration = null; } });
    return promise;
  }

  async stop(): Promise<void> { await this.cleanup('idle'); }
  async dispose(): Promise<void> { this.disposed = true; if (typeof document !== 'undefined') document.removeEventListener('visibilitychange', this.handleVisibilityChange); await this.cleanup('idle'); this.listeners.clear(); this.resultListeners.clear(); }

  suspend(): void {
    if (this.state !== 'running') return;
    this.cancelFrame();
    this.state = 'suspended';
    this.emit();
  }

  resume(): void {
    if (this.state !== 'suspended' || !this.stream) return;
    this.state = 'running';
    this.emit();
    this.scheduleFrame();
  }

  async switchCamera(deviceId: string): Promise<void> {
    if (!this.owner || !this.video || (this.state !== 'running' && this.state !== 'suspended')) throw new VisionRuntimeError('INVALID_STATE', '没有正在运行的视觉会话');
    const generation = this.generation;
    const video = this.video;
    let replacement: MediaStream;
    try { replacement = await this.requestCamera(deviceId); }
    catch (error) { if (!this.isCurrent(generation)) return; throw error; }
    if (!this.isCurrent(generation) || !this.stream || !this.video || this.video !== video || (this.state !== 'running' && this.state !== 'suspended')) { this.stopTracks(replacement); return; }
    const old = this.stream;
    this.stream = replacement;
    old?.getTracks().forEach(track => track.stop());
    video.srcObject = replacement;
    await video.play().catch(() => undefined);
    if (!this.isCurrent(generation) || this.stream !== replacement) { this.stopTracks(replacement); if (this.stream === replacement) this.stream = null; return; }
    this.emit();
  }

  private async startInternal(deviceId: string | undefined, generation: number): Promise<void> {
    this.lastError = null; this.state = 'loading'; this.model = 'loading'; this.emit();
    try {
      await this.startWorker(generation);
      if (!this.isCurrent(generation)) return;
      const stream = await this.requestCamera(deviceId);
      if (!this.isCurrent(generation)) { this.stopTracks(stream); return; }
      this.stream = stream;
      const video = this.video;
      if (!video) { this.stopTracks(stream); throw new VisionRuntimeError('INVALID_STATE', '缺少视频元素', false); }
      video.srcObject = stream;
      await video.play().catch(() => undefined);
      if (!this.isCurrent(generation) || this.stream !== stream) { this.stopTracks(stream); if (video.srcObject === stream) video.srcObject = null; return; }
      this.model = 'ready'; this.state = 'running'; this.emit(); this.scheduleFrame();
    } catch (error) {
      if (!this.isCurrent(generation)) return;
      const normalized = normalizeVisionError(error);
      this.lastError = { code: normalized.code, message: normalized.message };
      this.state = normalized.code === 'CAMERA_PERMISSION_DENIED' ? 'permission-denied' : 'error';
      this.emit(); await this.cleanup(this.state); throw normalized;
    }
  }

  private async startWorker(generation: number): Promise<void> {
    const worker = this.workerFactory();
    this.worker = worker;
    worker.onerror = event => {
      if (!this.isCurrent(generation) || this.worker !== worker) return;
      const error = new VisionRuntimeError('WORKER_ERROR', event.message || '视觉 Worker 出错');
      if (this.pendingWorkerInit?.generation === generation) { this.pendingWorkerInit.reject(error); return; }
      this.lastError = { code: error.code, message: error.message }; this.state = 'error'; this.emit(); void this.cleanup('error');
    };
    const requestId = crypto.randomUUID();
    const ready = new Promise<void>((resolve, reject) => {
      const timer = setTimeout(() => { this.pendingWorkerInit = null; reject(new VisionRuntimeError('MODEL_LOAD_FAILED', '视觉模型加载超时')); }, 15000);
      const settleReject = (error: unknown) => { clearTimeout(timer); if (this.pendingWorkerInit?.generation === generation) this.pendingWorkerInit = null; reject(error); };
      this.pendingWorkerInit = { generation, reject: settleReject, cancel: () => settleReject(new VisionRuntimeError('INVALID_STATE', '视觉会话已取消')) };
      worker.onmessage = event => {
        const message = event.data;
        if (!this.isCurrent(generation) || this.worker !== worker) return;
        if (message.requestId === requestId && message.type === 'error') { clearTimeout(timer); this.pendingWorkerInit = null; reject(new VisionRuntimeError(message.code === 'MODEL_LOAD_FAILED' ? 'MODEL_LOAD_FAILED' : 'WORKER_ERROR', message.message, false)); return; }
        if (message.type === 'ready' && message.requestId === requestId) { clearTimeout(timer); this.pendingWorkerInit = null; resolve(); return; }
        this.handleWorkerMessage(message, generation, worker);
      };
    });
    const request: VisionWorkerRequest = { type: 'init', requestId, modelAssetUrl: this.options.modelAssetUrl, wasmRootUrl: this.options.wasmRootUrl, numHands: this.options.numHands, minHandDetectionConfidence: this.options.minHandDetectionConfidence, minHandPresenceConfidence: this.options.minHandPresenceConfidence, minTrackingConfidence: this.options.minTrackingConfidence };
    worker.postMessage(request);
    await ready;
  }

  private async requestCamera(deviceId?: string): Promise<MediaStream> {
    if (!this.mediaDevices?.getUserMedia) throw new VisionRuntimeError('CAMERA_UNAVAILABLE', '浏览器不支持摄像头输入', false);
    try {
      const stream = await this.mediaDevices.getUserMedia({ video: deviceId ? { deviceId: { exact: deviceId } } : { facingMode: 'user' }, audio: false });
      stream.getVideoTracks().forEach(track => track.addEventListener('ended', () => this.handleTrackEnded(track)));
      return stream;
    }
    catch (error) { throw normalizeVisionError(error); }
  }

  private scheduleFrame(): void {
    if (this.state !== 'running' || !this.video || this.frameHandle !== null) return;
    const video = this.video;
    const generation = this.generation;
    if (video.requestVideoFrameCallback) this.frameHandle = video.requestVideoFrameCallback(timestamp => { this.frameHandle = null; void this.captureFrame(timestamp, generation); });
    else this.frameHandle = requestAnimationFrame(timestamp => { this.frameHandle = null; void this.captureFrame(timestamp, generation); });
  }

  private async captureFrame(timestamp: number, generation: number): Promise<void> {
    if (!this.isCurrent(generation) || this.state !== 'running' || !this.video) return;
    if (!this.gate.tryAcquire()) { this.scheduleFrame(); this.emit(); return; }
    const sequence = ++this.frameSequence;
    const current = this.now();
    this.fps = this.lastFrameTime === null || current <= this.lastFrameTime ? this.fps : 1000 / (current - this.lastFrameTime);
    this.lastFrameTime = current;
    try {
      const bitmap = await this.captureBitmap(this.video);
      if (!this.isCurrent(generation) || !this.worker || this.state !== 'running') { bitmap.close(); return; }
      const request: VisionWorkerRequest = { type: 'frame', requestId: crypto.randomUUID(), frameSequence: sequence, monotonicTimeMs: timestamp || current, fps: this.fps, droppedFrames: this.gate.droppedFrames, source: this.owner!, bitmap };
      this.worker.postMessage(request, [bitmap]);
    } catch (error) {
      this.gate.release(); this.lastError = { code: 'CAMERA_DEVICE_LOST', message: normalizeVisionError(error).message }; this.state = 'device-lost'; this.emit(); await this.cleanup('device-lost'); return;
    }
    if (this.isCurrent(generation)) this.scheduleFrame();
  }

  private async captureBitmap(video: HTMLVideoElement): Promise<ImageBitmap> {
    if (typeof createImageBitmap === 'function') return createImageBitmap(video);
    if (typeof OffscreenCanvas !== 'undefined') { const canvas = new OffscreenCanvas(video.videoWidth || 640, video.videoHeight || 480); const context = canvas.getContext('2d'); if (!context) throw new VisionRuntimeError('CAMERA_UNAVAILABLE', '无法创建视频帧画布'); context.drawImage(video, 0, 0); return canvas.transferToImageBitmap(); }
    throw new VisionRuntimeError('CAMERA_UNAVAILABLE', '浏览器不支持 ImageBitmap');
  }

  private handleWorkerMessage(message: VisionWorkerResponse, generation: number, worker: WorkerLike): void {
    if (!this.isCurrent(generation) || this.worker !== worker) return;
    if (message.type === 'result') { this.gate.release(); this.emit(); this.resultListeners.forEach(listener => listener(message.result)); return; }
    if (message.type === 'error') { this.gate.release(); this.lastError = { code: this.errorCode(message.code), message: message.message }; this.state = 'error'; this.emit(); void this.cleanup('error'); }
  }

  private cancelFrame(): void { if (this.frameHandle === null) return; if (this.video?.cancelVideoFrameCallback) this.video.cancelVideoFrameCallback(this.frameHandle); else cancelAnimationFrame(this.frameHandle); this.frameHandle = null; }

  private async cleanup(finalState: VisionRuntimeState, releaseOwner = true): Promise<void> {
    this.generation += 1;
    if (this.startPromiseGeneration === this.generation - 1) { this.startPromise = null; this.startPromiseGeneration = null; }
    this.pendingWorkerInit?.cancel(); this.pendingWorkerInit = null;
    this.cancelFrame(); if (this.state !== finalState && finalState === 'idle') { this.state = 'stopping'; this.emit(); }
    this.stream?.getTracks().forEach(track => track.stop()); this.stream = null;
    if (this.video) this.video.srcObject = null;
    this.video = null;
    this.worker?.terminate(); this.worker = null; this.gate.reset(); this.model = 'unloaded';
    if (releaseOwner) this.owner = null;
    this.state = finalState; this.emit();
  }

  private readonly handleVisibilityChange = (): void => { if (document.visibilityState === 'hidden' && this.state === 'running') void this.stop(); };
  private readonly handleTrackEnded = (track: MediaStreamTrack): void => { if (this.stream?.getVideoTracks().includes(track) && (this.state === 'running' || this.state === 'suspended')) { this.lastError = { code: 'CAMERA_DEVICE_LOST', message: '摄像头设备已断开' }; this.state = 'device-lost'; this.emit(); void this.cleanup('device-lost'); } };
  private errorCode(code: string): VisionErrorCode { const known: VisionErrorCode[] = ['VISION_BUSY', 'INVALID_STATE', 'CAMERA_UNAVAILABLE', 'CAMERA_PERMISSION_DENIED', 'CAMERA_DEVICE_LOST', 'MODEL_LOAD_FAILED', 'MODEL_NOT_READY', 'WORKER_ERROR', 'WORKER_INFERENCE_FAILED', 'RESOURCE_MISSING']; return known.includes(code as VisionErrorCode) ? code as VisionErrorCode : 'WORKER_ERROR'; }
  private isCurrent(generation: number): boolean { return !this.disposed && this.generation === generation; }
  private stopTracks(stream: MediaStream): void { stream.getTracks().forEach(track => track.stop()); }
  private emit(): void { const snapshot = this.snapshot(); this.listeners.forEach(listener => listener(snapshot)); }
}
