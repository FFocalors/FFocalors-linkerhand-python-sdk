import { describe, expect, it, vi } from 'vitest';
import { createDeviceController } from './composition';
import { mockRuntime } from '../shared/contracts/mock-runtime';
import type { ConnectionSnapshot, ConsolePorts, OperationSnapshot } from '../shared/contracts';

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
});
