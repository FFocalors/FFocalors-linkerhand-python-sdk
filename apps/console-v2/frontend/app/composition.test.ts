import { describe, expect, it, vi } from 'vitest';
import { createActionController, createDeviceController } from './composition';
import { mockRuntime } from '../shared/contracts/mock-runtime';
import type { ConnectionSnapshot, ConsolePorts, OperationSnapshot } from '../shared/contracts';
import type { PosePreset, ProgrammedAction } from '../features/actions';

describe('runtime composition adapters', () => {
  it('explicitly delegates real connection, vector and channel lifecycle to Tauri extras', async () => {
    const connection: ConnectionSnapshot = { schemaVersion: 1, deviceId: 'real-1', state: 'connected', attempt: 2, lastError: null };
    const operation: OperationSnapshot = { schemaVersion: 1, operationId: 'op', kind: 'motion', state: 'running', progress: 0, detail: null };
    const callbacks = { connection: undefined as ((value: ConnectionSnapshot) => void) | undefined, operation: undefined as ((value: OperationSnapshot) => void) | undefined };
    const cleanup = { connection: vi.fn(), operation: vi.fn() };
    const extras = {
      connect: vi.fn(async () => connection), disconnect: vi.fn(async () => ({ ...connection, state: 'disconnected' as const })), reconnect: vi.fn(async () => connection),
      setSpeed: vi.fn(async () => undefined), setTorque: vi.fn(async () => undefined),
      subscribeConnection: vi.fn((listener: (value: ConnectionSnapshot) => void) => { callbacks.connection = listener; return cleanup.connection; }),
      subscribeOperation: vi.fn((listener: (value: OperationSnapshot) => void) => { callbacks.operation = listener; return cleanup.operation; }),
    };
    const runtime: ConsolePorts = { ...mockRuntime, device: { ...mockRuntime.device, getConnection: vi.fn(async () => ({ ...connection, state: 'disconnected' as const })) } };
    const controller = createDeviceController(runtime, false, extras);
    await controller.connect();
    await controller.disconnect();
    await controller.reconnect();
    await controller.setSpeed({ values: [0.2, 0.2], finalCommand: true });
    await controller.setTorque({ values: [0.3, 0.3], finalCommand: true });
    const removeConnection = controller.subscribeConnection(vi.fn());
    const removeOperation = controller.subscribeOperation?.(vi.fn());
    callbacks.connection?.(connection);
    callbacks.operation?.(operation);
    removeConnection();
    removeOperation?.();
    expect(extras.connect).toHaveBeenCalledOnce();
    expect(extras.disconnect).toHaveBeenCalledOnce();
    expect(extras.reconnect).toHaveBeenCalledOnce();
    expect(extras.setSpeed).toHaveBeenCalledWith({ values: [0.2, 0.2], finalCommand: true });
    expect(extras.setTorque).toHaveBeenCalledWith({ values: [0.3, 0.3], finalCommand: true });
    expect(cleanup.connection).toHaveBeenCalledOnce();
    expect(cleanup.operation).toHaveBeenCalledOnce();
  });

  it('passes complete pose keyframes, reverses in runtime seam, preserves loop options, and cancels', async () => {
    const playFrames = vi.fn(async () => undefined);
    const stop = vi.fn(async () => undefined);
    const pause = vi.fn(async () => undefined);
    const resume = vi.fn(async () => undefined);
    const extras = {
      startRecording: vi.fn(async () => undefined), pauseRecording: vi.fn(async () => undefined), resumeRecording: vi.fn(async () => undefined), finishRecording: vi.fn(async () => undefined), cancelRecording: vi.fn(async () => undefined),
      play: vi.fn(async () => undefined), playFrames, pause, resume, stop,
      subscribe: vi.fn(() => () => undefined),
    } as any;
    const runtime: ConsolePorts = { ...mockRuntime, logs: { ...mockRuntime.logs, record: vi.fn(async () => undefined) } };
    const controller = createActionController(runtime, false, extras);
    const poses: PosePreset[] = [
      { kind: 'pose', id: 'a', name: 'A', source: 'local', positions: [0, .1, .2, .3, .4, .5] },
      { kind: 'pose', id: 'b', name: 'B', source: 'local', positions: [.5, .4, .3, .2, .1, 0] },
    ];
    const action: ProgrammedAction = { kind: 'sequence', id: 'sequence-1', name: '序列', source: 'local', poseIds: ['a', 'b'], poses, playback: { mode: 'loop', speed: 1.5, direction: 'reverse', loopCount: 3 }, createdAt: 'now' };
    await controller.playProgrammedAction!(action, action.playback);
    expect(playFrames).toHaveBeenCalledWith('sequence-1', '序列', expect.arrayContaining([
      expect.objectContaining({ positions: poses[0].positions, durationMs: 500 }),
      expect.objectContaining({ positions: poses[1].positions, durationMs: 500 }),
    ]), action.playback);
    expect(stop).not.toHaveBeenCalled();
    await controller.playPose!(poses[0], { mode: 'single', speed: 1, direction: 'forward', loopCount: 1 });
    expect(playFrames).toHaveBeenLastCalledWith('a', 'A', [expect.objectContaining({ positions: poses[0].positions, durationMs: 500 })], { mode: 'single', speed: 1, direction: 'forward', loopCount: 1 });
    await controller.pausePlayback?.();
    await controller.resumePlayback?.();
    expect(extras.pause).toHaveBeenCalledOnce();
    expect(extras.resume).toHaveBeenCalledOnce();
    await controller.stop();
    expect(stop).toHaveBeenCalledOnce();
  });

  it('rejects malformed vectors and records an actionable validation event', async () => {
    const record = vi.fn(async () => undefined);
    const runtime: ConsolePorts = { ...mockRuntime, logs: { ...mockRuntime.logs, record } };
    const controller = createActionController(runtime, true);
    await expect(controller.playPose!({ kind: 'pose', id: 'bad', name: '坏姿态', source: 'local', positions: [2] }, { mode: 'single', speed: 1, direction: 'forward', loopCount: 1 })).rejects.toThrow('6 个 0..1');
    expect(record).toHaveBeenCalledWith(expect.objectContaining({ event: 'control.action.validation_failed', level: 'error' }));
    expect((await controller.getState()).state).toBe('error');
  });

  it('keeps simulator infinite loops cancellable', async () => {
    const controller = createActionController(mockRuntime, true);
    await controller.playPose!({ kind: 'pose', id: 'loop-pose', name: '循环姿态', source: 'local', positions: [.5, .5, .5, .5, .5, .5] }, { mode: 'loop', speed: 1, direction: 'forward', loopCount: null });
    await controller.stop();
    expect((await controller.getState()).state).toBe('cancelled');
  });
});
