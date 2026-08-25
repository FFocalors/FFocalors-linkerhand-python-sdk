/** Camera enumeration is intentionally shared by settings and both vision pages.
 * Keep it side-effect free: permission is requested only by the caller that
 * actually needs a stream, while enumeration itself never picks a device.
 */
export type CameraDeviceInfo = {
  deviceId: string;
  label: string;
  kind: 'videoinput';
  groupId?: string;
};

type MediaDevicesLike = Pick<MediaDevices, 'enumerateDevices'>;

export async function enumerateCameraDevices(mediaDevices: MediaDevicesLike | undefined = typeof navigator !== 'undefined' ? navigator.mediaDevices : undefined): Promise<CameraDeviceInfo[]> {
  if (!mediaDevices?.enumerateDevices) return [];
  const devices = await mediaDevices.enumerateDevices();
  return devices
    .filter(device => device.kind === 'videoinput')
    .map(device => ({
      deviceId: device.deviceId,
      label: device.label || (device.deviceId ? `摄像头 ${device.deviceId.slice(0, 8)}` : '未命名摄像头'),
      kind: 'videoinput' as const,
      groupId: device.groupId,
    }));
}

export const CAMERA_DEVICE_STORAGE_KEY = 'linkerhand-console-v2-camera-device-id';

export function readPreferredCameraDeviceId(storage: Pick<Storage, 'getItem'> | undefined = typeof localStorage !== 'undefined' ? localStorage : undefined): string | null {
  try {
    const raw = storage?.getItem(CAMERA_DEVICE_STORAGE_KEY);
    if (!raw) return null;
    const value = JSON.parse(raw) as unknown;
    return typeof value === 'string' && value.length > 0 ? value : null;
  } catch {
    return null;
  }
}

export function writePreferredCameraDeviceId(deviceId: string | null, storage: Pick<Storage, 'setItem' | 'removeItem'> | undefined = typeof localStorage !== 'undefined' ? localStorage : undefined): void {
  try {
    if (deviceId) storage?.setItem(CAMERA_DEVICE_STORAGE_KEY, JSON.stringify(deviceId));
    else storage?.removeItem(CAMERA_DEVICE_STORAGE_KEY);
  } catch {
    // Storage is optional in an ephemeral WebView/test environment.
  }
}
