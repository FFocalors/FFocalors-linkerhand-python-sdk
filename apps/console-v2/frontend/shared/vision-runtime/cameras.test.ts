import { describe, expect, it, vi } from 'vitest';
import { enumerateCameraDevices, readPreferredCameraDeviceId, writePreferredCameraDeviceId } from './cameras';

describe('shared camera helpers', () => {
  it('enumerates only video inputs and keeps unnamed devices selectable', async () => {
    const enumerateDevices = vi.fn(async () => [
      { kind: 'audioinput', deviceId: 'mic', label: 'Mic', groupId: 'g1' },
      { kind: 'videoinput', deviceId: 'laptop', label: 'Integrated Camera', groupId: 'g1' },
      { kind: 'videoinput', deviceId: 'remote', label: '', groupId: 'g2' },
    ] as MediaDeviceInfo[]);
    await expect(enumerateCameraDevices({ enumerateDevices })).resolves.toEqual([
      { kind: 'videoinput', deviceId: 'laptop', label: 'Integrated Camera', groupId: 'g1' },
      { kind: 'videoinput', deviceId: 'remote', label: '摄像头 remote', groupId: 'g2' },
    ]);
  });

  it('never stores the literal string null for auto selection', () => {
    const values = new Map<string, string>();
    const storage = { getItem: (key: string) => values.get(key) ?? null, setItem: (key: string, value: string) => values.set(key, value), removeItem: (key: string) => values.delete(key) };
    writePreferredCameraDeviceId('laptop', storage);
    expect(readPreferredCameraDeviceId(storage)).toBe('laptop');
    writePreferredCameraDeviceId(null, storage);
    expect(readPreferredCameraDeviceId(storage)).toBeNull();
  });
});
