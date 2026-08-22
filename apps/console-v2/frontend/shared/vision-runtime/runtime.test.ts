import { afterEach, describe, expect, it, vi } from 'vitest';
import { SingleFrameGate } from './backpressure';
import { VisionRuntime, VisionRuntimeError } from './index';

function fakeStream() {
  let ended: (() => void) | undefined;
  const track = { stop: vi.fn(), addEventListener: vi.fn((_type: string, listener: () => void) => { ended = listener; }), getSettings: () => ({ deviceId: 'camera-1' }) } as unknown as MediaStreamTrack;
  return { track, end: () => ended?.(), stream: { getTracks: () => [track], getVideoTracks: () => [track] } as unknown as MediaStream };
}
function fakeWorker(init: 'ready' | 'error' | 'deferred' = 'ready') {
  let worker: { onmessage: ((event: MessageEvent) => void) | null; onerror: ((event: ErrorEvent) => void) | null; postMessage: ReturnType<typeof vi.fn>; terminate: ReturnType<typeof vi.fn>; frames: Array<{ requestId: string; bitmap: ImageBitmap }> };
  let initRequestId: string | undefined;
  worker = { onmessage: null, onerror: null, terminate: vi.fn(), frames: [], postMessage: vi.fn((message: { type: string; requestId: string; bitmap?: ImageBitmap }) => {
    if (message.type === 'init') { initRequestId = message.requestId; if (init !== 'deferred') queueMicrotask(() => worker.onmessage?.({ data: init === 'ready' ? { type: 'ready', requestId: message.requestId } : { type: 'error', requestId: message.requestId, code: 'MODEL_LOAD_FAILED', message: 'fixture model error' } } as MessageEvent)); }
    if (message.type === 'frame') worker.frames.push({ requestId: message.requestId, bitmap: message.bitmap! });
  }) };
  return { worker, resolveInit: () => { if (initRequestId) worker.onmessage?.({ data: { type: 'ready', requestId: initRequestId } } as MessageEvent); }, emit: (data: unknown) => { const message = data as { type?: string; requestId?: string }; if (message.type === 'error') worker.frames.find(frame => frame.requestId === message.requestId)?.bitmap.close(); worker.onmessage?.({ data } as MessageEvent); }, fail: (message = 'fixture worker error') => worker.onerror?.({ message } as ErrorEvent) };
}
function fakeVideo() { let callback: ((timestamp: number) => void) | undefined; return { video: { play: vi.fn(async () => undefined), srcObject: null, requestVideoFrameCallback: vi.fn((next: (timestamp: number) => void) => { callback = next; return 1; }), cancelVideoFrameCallback: vi.fn() } as unknown as HTMLVideoElement, frame: (timestamp: number) => callback?.(timestamp) }; }
function bitmapFixture() { return { close: vi.fn() } as unknown as ImageBitmap; }
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(next => { resolve = next; }); return { promise, resolve }; }
afterEach(() => { vi.unstubAllGlobals(); Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' }); });

describe('SingleFrameGate', () => {
  it('never queues a second frame', () => {
    const gate = new SingleFrameGate();
    expect(gate.tryAcquire()).toBe(true);
    expect(gate.tryAcquire()).toBe(false);
    expect(gate.tryAcquire()).toBe(false);
    expect(gate.droppedFrames).toBe(2);
    expect(gate.inFlight).toBe(1);
    gate.release();
    expect(gate.tryAcquire()).toBe(true);
  });
});

describe('VisionRuntime ownership and release', () => {
  it('sends base-safe default asset URLs without a FilesetResolver trailing slash', async () => {
    const { stream } = fakeStream(); const workerFixture = fakeWorker();
    const runtime = new VisionRuntime({}, { mediaDevices: { getUserMedia: vi.fn(async () => stream) }, workerFactory: () => workerFixture.worker as never });
    await runtime.start(fakeVideo().video, 'vision');
    const init = workerFixture.worker.postMessage.mock.calls.map(([message]) => message).find(message => message.type === 'init') as { modelAssetUrl: string; wasmRootUrl: string };
    expect(new URL(init.modelAssetUrl).pathname).toMatch(/\/vision\/hand_landmarker\.task$/);
    expect(new URL(init.wasmRootUrl).pathname).toMatch(/\/vision\/wasm$/);
    expect(init.wasmRootUrl.endsWith('/')).toBe(false);
    await runtime.stop();
  });

  it('allows one source and closes camera/worker on stop', async () => {
    const { stream, track } = fakeStream();
    const { worker } = fakeWorker();
    const getUserMedia = vi.fn(async () => stream);
    const runtime = new VisionRuntime({}, { mediaDevices: { getUserMedia }, workerFactory: () => worker as never });
    const { video } = fakeVideo();
    await runtime.start(video, 'vision');
    await runtime.start(video, 'vision');
    await expect(runtime.start(video, 'rps')).rejects.toMatchObject({ code: 'VISION_BUSY' });
    await expect(runtime.start({} as HTMLVideoElement, 'vision')).rejects.toMatchObject({ code: 'INVALID_STATE' });
    expect(getUserMedia).toHaveBeenCalledTimes(1);
    await runtime.stop();
    expect(track.stop).toHaveBeenCalled();
    expect(worker.terminate).toHaveBeenCalled();
    expect(video.srcObject).toBeNull();
    expect(runtime.snapshot().state).toBe('idle');
  });

  it('maps permission denial to a stable non-retryable error', async () => {
    const { worker } = fakeWorker();
    const runtime = new VisionRuntime({}, { mediaDevices: { getUserMedia: vi.fn(async () => { throw new DOMException('denied', 'NotAllowedError'); }) }, workerFactory: () => worker as never });
    const { video } = fakeVideo();
    await expect(runtime.start(video, 'vision')).rejects.toBeInstanceOf(VisionRuntimeError);
    expect(runtime.snapshot().state).toBe('permission-denied');
    expect(runtime.snapshot().lastError?.code).toBe('CAMERA_PERMISSION_DENIED');
  });

  it('cleans model errors, track-ended device loss and worker errors', async () => {
    const modelWorker = fakeWorker('error');
    const modelRuntime = new VisionRuntime({}, { mediaDevices: { getUserMedia: vi.fn() }, workerFactory: () => modelWorker.worker as never });
    await expect(modelRuntime.start(fakeVideo().video, 'vision')).rejects.toMatchObject({ code: 'MODEL_LOAD_FAILED' });
    expect(modelWorker.worker.terminate).toHaveBeenCalled();

    const { stream, track, end } = fakeStream();
    const workerFixture = fakeWorker();
    const runtime = new VisionRuntime({}, { mediaDevices: { getUserMedia: vi.fn(async () => stream) }, workerFactory: () => workerFixture.worker as never });
    await runtime.start(fakeVideo().video, 'vision');
    end();
    await vi.waitFor(() => expect(runtime.snapshot().state).toBe('device-lost'));
    expect(track.stop).toHaveBeenCalled();
    expect(workerFixture.worker.terminate).toHaveBeenCalled();

    const workerError = fakeWorker();
    const { stream: errorStream, track: errorTrack } = fakeStream();
    const errorRuntime = new VisionRuntime({}, { mediaDevices: { getUserMedia: vi.fn(async () => errorStream) }, workerFactory: () => workerError.worker as never });
    await errorRuntime.start(fakeVideo().video, 'vision');
    workerError.fail();
    await vi.waitFor(() => expect(errorRuntime.snapshot().state).toBe('error'));
    expect(errorTrack.stop).toHaveBeenCalled();
    expect(workerError.worker.terminate).toHaveBeenCalled();
  });

  it('holds one frame until ack, drops newer frames, and continues after ack', async () => {
    const { stream, track } = fakeStream(); const workerFixture = fakeWorker(); const { video, frame } = fakeVideo();
    const bitmap1 = bitmapFixture(); const bitmap2 = bitmapFixture();
    const createBitmap = vi.fn().mockResolvedValueOnce(bitmap1).mockResolvedValueOnce(bitmap2);
    vi.stubGlobal('createImageBitmap', createBitmap);
    const runtime = new VisionRuntime({}, { mediaDevices: { getUserMedia: vi.fn(async () => stream) }, workerFactory: () => workerFixture.worker as never });
    const results: unknown[] = []; runtime.onResult(result => results.push(result));
    await runtime.start(video, 'vision');
    frame(100); await vi.waitFor(() => expect(workerFixture.worker.frames).toHaveLength(1));
    expect(runtime.snapshot().inflight).toBe(1);
    frame(116); await Promise.resolve();
    expect(workerFixture.worker.frames).toHaveLength(1); expect(runtime.snapshot().droppedFrames).toBe(1);
    workerFixture.emit({ type: 'result', requestId: workerFixture.worker.frames[0].requestId, result: { source: 'vision', hands: [], monotonicTimeMs: 100, frameSequence: 1, fps: null, droppedFrames: 0, inflight: 1 } });
    expect(runtime.snapshot().inflight).toBe(0); expect(results).toHaveLength(1);
    frame(132); await vi.waitFor(() => expect(workerFixture.worker.frames).toHaveLength(2));
    expect(runtime.snapshot().inflight).toBe(1);
    workerFixture.emit({ type: 'error', requestId: workerFixture.worker.frames[1].requestId, code: 'WORKER_INFERENCE_FAILED', message: 'fixture frame error' });
    await vi.waitFor(() => expect(runtime.snapshot().state).toBe('error'));
    expect(bitmap2.close).toHaveBeenCalled(); expect(runtime.snapshot().inflight).toBe(0); expect(track.stop).toHaveBeenCalled(); expect(workerFixture.worker.terminate).toHaveBeenCalled();
  });

  it('does not post or publish when stop wins an async bitmap capture', async () => {
    const { stream } = fakeStream(); const workerFixture = fakeWorker(); const { video, frame } = fakeVideo();
    let resolveBitmap: (bitmap: ImageBitmap) => void = () => undefined;
    vi.stubGlobal('createImageBitmap', vi.fn(() => new Promise<ImageBitmap>(resolve => { resolveBitmap = resolve; })));
    const bitmap = bitmapFixture(); const runtime = new VisionRuntime({}, { mediaDevices: { getUserMedia: vi.fn(async () => stream) }, workerFactory: () => workerFixture.worker as never });
    const results: unknown[] = []; runtime.onResult(result => results.push(result));
    await runtime.start(video, 'vision'); frame(100); await Promise.resolve(); await runtime.stop(); resolveBitmap(bitmap); await Promise.resolve();
    await vi.waitFor(() => expect(bitmap.close).toHaveBeenCalled());
    expect(workerFixture.worker.frames).toHaveLength(0); expect(results).toHaveLength(0);
  });

  it('stops on hidden documents and removes listeners on dispose', async () => {
    const { stream, track } = fakeStream(); const workerFixture = fakeWorker(); const runtime = new VisionRuntime({}, { mediaDevices: { getUserMedia: vi.fn(async () => stream) }, workerFactory: () => workerFixture.worker as never });
    const { video } = fakeVideo(); const listener = vi.fn(); runtime.subscribe(listener); await runtime.start(video, 'vision');
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' }); document.dispatchEvent(new Event('visibilitychange'));
    await vi.waitFor(() => expect(runtime.snapshot().state).toBe('idle')); expect(track.stop).toHaveBeenCalled();
    const count = listener.mock.calls.length; await runtime.dispose(); document.dispatchEvent(new Event('visibilitychange')); expect(listener.mock.calls.length).toBe(count + 1);
  });

  it('cancels deferred worker init immediately and permits a clean restart', async () => {
    const first = fakeWorker('deferred'); const second = fakeWorker(); const workers = [first, second];
    const { stream } = fakeStream(); const media = vi.fn(async () => stream); const runtime = new VisionRuntime({}, { mediaDevices: { getUserMedia: media }, workerFactory: () => workers.shift()!.worker as never });
    const { video } = fakeVideo(); const start = runtime.start(video, 'vision');
    await Promise.resolve(); await runtime.stop();
    await expect(Promise.race([start.then(() => 'settled'), new Promise(resolve => setTimeout(() => resolve('timeout'), 100))])).resolves.toBe('settled');
    expect(first.worker.terminate).toHaveBeenCalled(); expect(runtime.snapshot().state).toBe('idle'); expect(runtime.snapshot().owner).toBeNull();
    first.resolveInit(); await Promise.resolve(); expect(media).not.toHaveBeenCalled(); expect(first.worker.postMessage.mock.calls.some(([message]) => message.type === 'frame')).toBe(false);
    await runtime.start(video, 'vision'); expect(runtime.snapshot().state).toBe('running'); expect(media).toHaveBeenCalledTimes(1); await runtime.stop();
  });

  it('stops a late getUserMedia stream after cancellation without attaching or running', async () => {
    const workerFixture = fakeWorker(); const late = deferred<MediaStream>(); const lateCamera = fakeStream();
    const media = vi.fn(() => late.promise); const runtime = new VisionRuntime({}, { mediaDevices: { getUserMedia: media }, workerFactory: () => workerFixture.worker as never });
    const { video } = fakeVideo(); const start = runtime.start(video, 'vision'); await vi.waitFor(() => expect(media).toHaveBeenCalled()); await runtime.stop();
    late.resolve(lateCamera.stream); await expect(start).resolves.toBeUndefined();
    expect(lateCamera.track.stop).toHaveBeenCalled(); expect(video.srcObject).toBeNull(); expect(runtime.snapshot().state).toBe('idle'); expect(runtime.snapshot().owner).toBeNull(); expect(workerFixture.worker.terminate).toHaveBeenCalled(); expect(workerFixture.worker.postMessage.mock.calls.some(([message]) => message.type === 'frame')).toBe(false);
  });

  it('stops a late camera replacement when stop wins switchCamera', async () => {
    const initial = fakeStream(); const replacement = fakeStream(); const pending = deferred<MediaStream>(); const workerFixture = fakeWorker();
    const media = vi.fn().mockResolvedValueOnce(initial.stream).mockReturnValueOnce(pending.promise);
    const runtime = new VisionRuntime({}, { mediaDevices: { getUserMedia: media }, workerFactory: () => workerFixture.worker as never }); const { video } = fakeVideo();
    await runtime.start(video, 'vision'); const switching = runtime.switchCamera('camera-2'); await vi.waitFor(() => expect(media).toHaveBeenCalledTimes(2)); await runtime.stop();
    pending.resolve(replacement.stream); await expect(switching).resolves.toBeUndefined(); expect(replacement.track.stop).toHaveBeenCalled(); expect(initial.track.stop).toHaveBeenCalled();
    expect(video.srcObject).toBeNull(); expect(runtime.snapshot().state).toBe('idle'); expect(runtime.snapshot().owner).toBeNull();
  });
});
