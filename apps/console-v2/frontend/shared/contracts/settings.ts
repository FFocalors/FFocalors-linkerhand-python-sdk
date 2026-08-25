import type { Transport } from './generated';

/** Public camera descriptor shared by settings and camera-backed features. */
export interface CameraDevice {
  deviceId: string;
  label: string;
  kind?: 'videoinput' | string;
  groupId?: string;
}

export interface SettingsValidationResult {
  valid: boolean;
  errors: Record<string, string>;
}

/** The app adapter validates this public shape without depending on a feature. */
export interface SettingsDraftForValidation {
  model: string;
  hand: string;
  transport: Transport;
  advanced: { connectionTimeoutMs: number };
}

const DEVICE_MODELS = ['O6', 'L6', 'L7', 'L10', 'L20', 'G20', 'L21', 'L25'] as const;

/** Runtime-independent settings validation used by the composition adapter. */
export function validateSettingsDraft(draft: SettingsDraftForValidation): SettingsValidationResult {
  const errors: Record<string, string> = {};
  if (!(DEVICE_MODELS as readonly string[]).includes(draft.model)) errors.model = '请选择支持的设备型号。';
  if (draft.hand !== 'left' && draft.hand !== 'right') errors.hand = '请选择左手或右手。';
  if (draft.transport.type === 'can') {
    if (!draft.transport.channel.trim()) errors['transport.channel'] = 'CAN channel 不能为空。';
    else if (/^\d+$/.test(draft.transport.channel) && (Number(draft.transport.channel) < 0 || Number(draft.transport.channel) > 63)) errors['transport.channel'] = 'CAN channel 应为 0–63。';
  } else {
    if (!/^COM\d+$/i.test(draft.transport.port.trim()) && !/^\/dev\/tty[A-Za-z0-9._-]+$/.test(draft.transport.port.trim())) errors['transport.port'] = '请输入串口，例如 COM3。';
    if (!Number.isInteger(draft.transport.baudrate) || draft.transport.baudrate < 1200 || draft.transport.baudrate > 2_000_000) errors['transport.baudrate'] = '波特率应为 1200–2000000 的整数。';
  }
  if (!Number.isInteger(draft.advanced.connectionTimeoutMs) || draft.advanced.connectionTimeoutMs < 100 || draft.advanced.connectionTimeoutMs > 120_000) errors.connectionTimeoutMs = '连接超时应为 100–120000 ms。';
  return { valid: Object.keys(errors).length === 0, errors };
}
