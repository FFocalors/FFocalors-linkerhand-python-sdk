import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ThemeProvider } from '../../shared/theme';
import { DEVICE_MODELS, Settings, type SettingsController, type SettingsSnapshot, type SettingsSaveResult, validateSettingsDraft, switchTransport } from './index';

const snapshot: SettingsSnapshot = { config: { schemaVersion: 1, deviceId: 'test', name: '测试手', model: 'O6', hand: 'left', transport: { type: 'can', channel: 'can0' }, autoReconnect: true }, version: '2.0.0', build: 'test', cameraPermission: 'granted' };
const result: SettingsSaveResult = { applied: true, reconnectRequired: false, restartRequired: false, errors: [] };
function controller(overrides: Partial<SettingsController> = {}): SettingsController {
  return { load: async () => snapshot, validate: draft => validateSettingsDraft(draft), save: async () => result, testSidecar: async () => ({ ok: true, message: 'sidecar 可用' }), checkOfflineAssets: async () => ({ ok: true, message: '资源完整' }), listCameras: async () => ({ permission: 'granted', cameras: [{ deviceId: 'cam-1', label: 'USB Camera' }] }), subscribe: () => () => undefined, ...overrides };
}
function renderSettings(next = controller()) { return render(<ThemeProvider><Settings model="O6" transport={{ type: 'can', channel: 'can0' }} controller={next} /></ThemeProvider>); }

describe('settings feature boundary', () => {
  it('covers every supported model and validates transport drafts', () => {
    expect(DEVICE_MODELS).toHaveLength(8);
    const draft = { model: 'O6' as const, hand: 'left' as const, transport: { type: 'rs485' as const, port: 'bad', baudrate: 1 }, preferredCameraDeviceId: null, advanced: { autoReconnect: true, connectionTimeoutMs: 5000, diagnostics: false } };
    expect(validateSettingsDraft(draft).valid).toBe(false);
    expect(validateSettingsDraft({ ...draft, transport: { type: 'rs485', port: 'COM3', baudrate: 115200 } }).valid).toBe(true);
    expect(switchTransport({ ...draft, transport: { type: 'can', channel: 'can0' } }, 'rs485').transport).toEqual({ type: 'rs485', port: 'COM3', baudrate: 115200 });
  });

  it('loads camera state, saves a staged draft, and reports restart', async () => {
    const user = userEvent.setup(); const save = vi.fn(async () => ({ ...result, restartRequired: true }));
    renderSettings(controller({ save }));
    await screen.findByText('版本 2.0.0 · 构建 test');
    await user.click(screen.getByRole('button', { name: '刷新摄像头' }));
    expect(await screen.findByText('已发现 1 个摄像头。')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'RS485' }));
    await user.clear(screen.getByLabelText('串口')); await user.type(screen.getByLabelText('串口'), 'COM7');
    await user.click(screen.getByRole('button', { name: '保存设置' }));
    await waitFor(() => expect(save).toHaveBeenCalled());
    expect(await screen.findByText('已保存。需要重启服务后生效。')).toBeInTheDocument();
  });

  it('disables mutation and checks without a controller', () => {
    render(<ThemeProvider><Settings model="O6" transport={{ type: 'can', channel: 'can0' }} /></ThemeProvider>);
    expect(screen.getByText(/未注入 SettingsController/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '保存设置' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '刷新摄像头' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '测试 sidecar' })).toBeDisabled();
  });

  it('uses injected ThemePort and cleans up subscriptions', async () => {
    const unsubscribe = vi.fn(); const subscribe = vi.fn(() => unsubscribe); const setTheme = vi.fn();
    const themePort = { getTheme: () => 'light' as const, setTheme, subscribe };
    const { unmount } = render(<ThemeProvider><Settings model="O6" transport={{ type: 'can', channel: 'can0' }} controller={controller()} themePort={themePort} /></ThemeProvider>);
    await userEvent.setup().click(screen.getByRole('radio', { name: '深色' }));
    expect(setTheme).toHaveBeenCalledWith('dark');
    unmount(); expect(unsubscribe).toHaveBeenCalled();
  });
});
