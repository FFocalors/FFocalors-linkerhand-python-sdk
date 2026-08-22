import { describe, expect, it, vi } from 'vitest';
import { SingleFrameGate } from './backpressure';
import { VisionRuntime, VisionRuntimeError } from './index';

function fakeStream() {
  const track = { stop: vi.fn(), addEventListener: vi.fn(), getSettings: () => ({ deviceId: 'camera-1' }) } as unknown as MediaStreamTrack;
  return { track, stream: { getTracks: () => [track], getVideoTracks: () => [track] } as unknown as MediaStream };
}
function fakeWorker() {
  let worker: { onmessage: ((event: MessageEvent) => void) | null; onerror: ((event: ErrorEvent) => void) | null; postMessage: (message: { type: string; requestId: string }) => void; terminate: ReturnType<typeof vi.fn> };
  worker = { onmessage: null, onerror: null, terminate: vi.fn(), postMessage(message) { if (message.type === 'init') queueMicrotask(() => worker.onmessage?.({ data: { type: 'ready', requestId: message.requestId } } as MessageEvent)); } };
  return worker;
}

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
  it('allows one source and closes camera/worker on stop', async () => {
    const { stream, track } = fakeStream();
    const worker = fakeWorker();
    const runtime = new VisionRuntime({}, { mediaDevices: { getUserMedia: vi.fn(async () => stream) }, workerFactory: () => worker as never });
    const video = { play: vi.fn(async () => undefined), srcObject: null, requestVideoFrameCallback: vi.fn(() => 1), cancelVideoFrameCallback: vi.fn() } as unknown as HTMLVideoElement;
    await runtime.start(video, 'vision');
    await expect(runtime.start(video, 'rps')).rejects.toMatchObject({ code: 'VISION_BUSY' });
    await runtime.stop();
    expect(track.stop).toHaveBeenCalled();
    expect(worker.terminate).toHaveBeenCalled();
    expect(runtime.snapshot().state).toBe('idle');
  });

  it('maps permission denial to a stable non-retryable error', async () => {
    const worker = fakeWorker();
    const runtime = new VisionRuntime({}, { mediaDevices: { getUserMedia: vi.fn(async () => { throw new DOMException('denied', 'NotAllowedError'); }) }, workerFactory: () => worker as never });
    const video = { play: vi.fn(async () => undefined), srcObject: null, requestVideoFrameCallback: vi.fn(() => 1), cancelVideoFrameCallback: vi.fn() } as unknown as HTMLVideoElement;
    await expect(runtime.start(video, 'vision')).rejects.toBeInstanceOf(VisionRuntimeError);
    expect(runtime.snapshot().state).toBe('permission-denied');
    expect(runtime.snapshot().lastError?.code).toBe('CAMERA_PERMISSION_DENIED');
  });
});
