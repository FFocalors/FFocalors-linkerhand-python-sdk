import { afterEach, vi } from 'vitest';
import type { ConsolePorts } from '../shared/contracts';

const invokeMock = vi.hoisted(() => vi.fn());
vi.mock('@tauri-apps/api/core', () => ({ invoke: invokeMock, isTauri: () => true }));

import { classifyCameraError, createSettingsController } from './settings';

describe('camera error classification', () => {
  afterEach(() => { vi.unstubAllGlobals(); });
  it('keeps WebView rejection separate from Windows privacy denial', () => {
    expect(classifyCameraError(new DOMException('blocked', 'SecurityError'))).toBe('webview-denied');
    expect(classifyCameraError(new DOMException('blocked', 'NotAllowedError'))).toBe('windows-denied');
  });

  it('reports missing and occupied devices as actionable states', () => {
    expect(classifyCameraError(new DOMException('missing', 'NotFoundError'))).toBe('no-device');
    expect(classifyCameraError(new DOMException('busy', 'NotReadableError'))).toBe('in-use');
  });

  it('wires WebView2 profile camera permission query and scoped reset IPC', async () => {
    invokeMock.mockResolvedValueOnce({ state: 'deny', origin: 'http://tauri.localhost' });
    invokeMock.mockResolvedValueOnce({ state: 'default', origin: 'http://tauri.localhost' });
    const controller = createSettingsController({} as ConsolePorts, false);
    await expect(controller.getCameraPermission?.()).resolves.toEqual({ state: 'deny', origin: 'http://tauri.localhost' });
    await expect(controller.resetCameraPermission?.()).resolves.toEqual({ state: 'default', origin: 'http://tauri.localhost' });
    expect(invokeMock).toHaveBeenNthCalledWith(1, 'camera_permission_status');
    expect(invokeMock).toHaveBeenNthCalledWith(2, 'reset_camera_permission');
  });

  it('returns enumerated camera ids without waiting for a permission prompt', async () => {
    const getUserMedia = vi.fn(() => new Promise<MediaStream>(() => undefined));
    Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: {
      enumerateDevices: vi.fn(async () => [{ kind: 'videoinput', deviceId: 'laptop', label: 'Integrated Camera', groupId: 'local' }]),
      getUserMedia,
    } });
    const controller = createSettingsController({} as ConsolePorts, false);
    const result = await controller.listCameras();
    expect(result.cameras).toHaveLength(1);
    expect(result.cameras[0].deviceId).toBe('laptop');
    expect(getUserMedia).not.toHaveBeenCalled();
  });

  it('bounds permission discovery when no camera is initially enumerated', async () => {
    const getUserMedia = vi.fn(() => new Promise<MediaStream>(() => undefined));
    Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: {
      enumerateDevices: vi.fn(async () => []),
      getUserMedia,
    } });
    const controller = createSettingsController({} as ConsolePorts, false);
    const pending = controller.listCameras();
    await expect(pending).resolves.toMatchObject({ cameras: [], permission: 'unknown' });
    expect(getUserMedia).toHaveBeenCalledTimes(1);
  });

  it('supplements an initial unnamed device with the complete post-permission list', async () => {
    const config = { schemaVersion: 1 as const, deviceId: 'test', name: '测试手', model: 'O6' as const, hand: 'left' as const, transport: { type: 'can' as const, channel: 'can0' }, autoReconnect: true };
    const enumerateDevices = vi.fn()
      .mockResolvedValueOnce([{ kind: 'videoinput', deviceId: 'default', label: '', groupId: 'local' }])
      .mockResolvedValueOnce([
        { kind: 'videoinput', deviceId: 'laptop', label: 'Integrated Camera', groupId: 'local' },
        { kind: 'videoinput', deviceId: 'phone', label: 'Phone Camera', groupId: 'remote' },
      ]);
    const stream = { getTracks: () => [{ stop: vi.fn() }] } as unknown as MediaStream;
    Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: { enumerateDevices, getUserMedia: vi.fn(async () => stream) } });
    const runtime = { device: { getConfig: vi.fn(async () => config) } } as unknown as ConsolePorts;
    const controller = createSettingsController(runtime, true);
    await controller.load();
    const snapshots: Array<{ cameras?: Array<{ deviceId: string }> }> = [];
    controller.subscribe(value => snapshots.push(value));
    const initial = await controller.listCameras();
    expect(initial.cameras).toHaveLength(1);
    await vi.waitFor(() => expect(snapshots.some(snapshot => snapshot.cameras?.length === 2)).toBe(true));
    expect(snapshots.at(-1)?.cameras?.map(camera => camera.deviceId)).toEqual(['laptop', 'phone']);
  });
});
