import { vi } from 'vitest';
import type { ConsolePorts } from '../shared/contracts';

const invokeMock = vi.hoisted(() => vi.fn());
vi.mock('@tauri-apps/api/core', () => ({ invoke: invokeMock, isTauri: () => true }));

import { classifyCameraError, createSettingsController } from './settings';

describe('camera error classification', () => {
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
});
