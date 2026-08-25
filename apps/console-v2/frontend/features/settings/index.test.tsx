import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ThemeProvider } from '../../shared/theme';
import { DEVICE_MODELS, Settings, type SettingsController, type SettingsSnapshot, type SettingsSaveResult, validateSettingsDraft, switchTransport } from './index';
import type { LogLevel } from '../../shared/contracts';

const snapshot: SettingsSnapshot = { config: { schemaVersion: 1, deviceId: 'test', name: '测试手', model: 'O6', hand: 'left', transport: { type: 'can', channel: 'can0' }, autoReconnect: true }, version: '2.0.0', build: 'test', cameraPermission: 'granted' };
const result: SettingsSaveResult = { applied: true, reconnectRequired: false, restartRequired: false, errors: [] };
function controller(overrides: Partial<SettingsController> = {}): SettingsController {
  return { load: async () => snapshot, validate: draft => validateSettingsDraft(draft), save: async () => result, testSidecar: async () => ({ ok: true, message: 'sidecar 可用' }), checkOfflineAssets: async () => ({ ok: true, message: '资源完整' }), listCameras: async () => ({ permission: 'granted', cameras: [{ deviceId: 'cam-1', label: 'USB Camera' }] }), openCameraPrivacySettings: async () => undefined, getConnectionState: async () => ({ state: 'disconnected' as const }), getFirmwareVersion: async () => ({ version: '0.0.0' }), getDebugMode: async () => false, setDebugMode: async () => undefined, getLogLevel: async () => 'info' as const, setLogLevel: async () => undefined, getLocale: async () => 'zh' as const, setLocale: async () => undefined, resetToFactory: async () => undefined, subscribe: () => () => undefined, ...overrides };
}
function renderSettings(next = controller()) { return render(<ThemeProvider><Settings model="O6" transport={{ type: 'can', channel: 'can0' }} controller={next} /></ThemeProvider>); }
function deferred<T>() { let resolve!: (value: T) => void; let reject!: (reason?: unknown) => void; const promise = new Promise<T>((resolvePromise, rejectPromise) => { resolve = resolvePromise; reject = rejectPromise; }); return { promise, resolve, reject }; }

describe('settings feature boundary', () => {
  it('covers every supported model and validates transport drafts', () => {
    expect(DEVICE_MODELS).toHaveLength(8);
    const draft = { model: 'O6' as const, hand: 'left' as const, transport: { type: 'rs485' as const, port: 'bad', baudrate: 1 }, preferredCameraDeviceId: null, advanced: { autoReconnect: true, connectionTimeoutMs: 5000, diagnostics: false, debugMode: false } };
    expect(validateSettingsDraft(draft).valid).toBe(false);
    expect(validateSettingsDraft({ ...draft, transport: { type: 'rs485', port: 'COM3', baudrate: 115200 } }).valid).toBe(true);
    expect(switchTransport({ ...draft, transport: { type: 'can', channel: 'can0' } }, 'rs485').transport).toEqual({ type: 'rs485', port: 'COM3', baudrate: 115200 });
  });

  it('loads camera state, saves a staged draft, and reports restart', async () => {
    const user = userEvent.setup(); const save = vi.fn(async () => ({ ...result, restartRequired: true }));
    renderSettings(controller({ save }));
    await screen.findByText(/版本 2\.0\.0 · 构建 test/);
    await user.click(screen.getByRole('button', { name: '刷新摄像头' }));
    expect(await screen.findByText('已发现 1 个摄像头。')).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: '左手' })).toBeChecked();
    await user.click(screen.getByRole('radio', { name: 'RS485' }));
    await user.clear(screen.getByLabelText('串口')); await user.type(screen.getByLabelText('串口'), 'COM7');
    await user.click(screen.getByRole('button', { name: '保存设置' }));
    await waitFor(() => expect(save).toHaveBeenCalled());
    expect(await screen.findByText('已保存。需要重启服务后生效。')).toBeInTheDocument();
  });

  it('disables mutation and checks without a controller', () => {
    render(<ThemeProvider><Settings model="O6" transport={{ type: 'can', channel: 'can0' }} /></ThemeProvider>);
    expect(screen.getByText(/未注入 SettingsController/)).toBeInTheDocument();
    expect(screen.getByText(/版本 2\.0\.0-rc\.1 · 构建 dev/)).toBeInTheDocument();
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

  it('locks editable fields during save and ignores a late result for a newer draft', async () => {
    const user = userEvent.setup(); const saveDeferred = deferred<SettingsSaveResult>(); const save = vi.fn(() => saveDeferred.promise);
    renderSettings(controller({ save }));
    await screen.findByText(/版本 2\.0\.0 · 构建 test/);
    await user.click(screen.getByRole('radio', { name: 'RS485' }));
    const port = screen.getByLabelText('串口');
    await user.clear(port); await user.type(port, 'COM7');
    await user.click(screen.getByRole('button', { name: '保存设置' }));
    await waitFor(() => expect(save).toHaveBeenCalledWith(expect.objectContaining({ transport: { type: 'rs485', port: 'COM7', baudrate: 115200 } })));
    expect(screen.getByRole('button', { name: '保存设置' })).toBeDisabled();
    expect(screen.getByLabelText('串口')).toBeDisabled();
    // A controller event can arrive while an older save is in flight; it must not
    // make that older result claim the current draft was applied.
    fireEvent.change(screen.getByLabelText('串口'), { target: { value: 'COM8' } });
    saveDeferred.resolve({ ...result, restartRequired: true });
    await waitFor(() => expect(screen.getByText('旧草稿已完成保存；当前修改仍未保存。')).toBeInTheDocument());
    expect(screen.getByText('未保存')).toBeInTheDocument();
    expect(screen.queryByText('已保存。需要重启服务后生效。')).not.toBeInTheDocument();
  });

  it('reports camera permission denial with recovery guidance and allows retry', async () => {
    const listCameras = vi.fn(async () => ({ permission: 'denied' as const, cameras: [] }));
    const openCameraPrivacySettings = vi.fn(async () => undefined);
    renderSettings(controller({ listCameras, openCameraPrivacySettings }));
    await screen.findByText(/版本 2\.0\.0 · 构建 test/);
    expect(await screen.findByRole('alert')).toHaveTextContent('允许桌面应用访问摄像头');
    expect(screen.getByRole('button', { name: '打开 Windows 摄像头设置' })).toBeEnabled();
    await userEvent.setup().click(screen.getByRole('button', { name: '打开 Windows 摄像头设置' }));
    expect(openCameraPrivacySettings).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('button', { name: '重试摄像头' })).toBeEnabled();
    expect(listCameras).toHaveBeenCalledTimes(1);
  });

  it('preserves a hand edit across a late initial snapshot and subscription event', async () => {
    const loadDeferred = deferred<SettingsSnapshot>();
    let emitSnapshot: ((value: SettingsSnapshot) => void) | undefined;
    const load = vi.fn(() => loadDeferred.promise);
    const subscribe = vi.fn((listener: (value: SettingsSnapshot) => void) => { emitSnapshot = listener; return () => undefined; });
    renderSettings(controller({ load, subscribe }));
    await userEvent.setup().click(screen.getByRole('radio', { name: '左手' }));
    loadDeferred.resolve({ ...snapshot, config: { ...snapshot.config, hand: 'right' } });
    await screen.findByText(/版本 2\.0\.0 · 构建 test/);
    expect(screen.getByRole('radio', { name: '左手' })).toBeChecked();
    emitSnapshot?.({ ...snapshot, config: { ...snapshot.config, hand: 'right' } });
    expect(screen.getByRole('radio', { name: '左手' })).toBeChecked();
  });

  it('keeps a hand edit while camera refresh is pending', async () => {
    const cameraDeferred = deferred<{ permission: 'granted'; cameras: never[] }>();
    renderSettings(controller({ listCameras: vi.fn(() => cameraDeferred.promise) }));
    await screen.findByText(/版本 2\.0\.0 · 构建 test/);
    await userEvent.setup().click(screen.getByRole('radio', { name: '左手' }));
    await userEvent.setup().click(screen.getByRole('button', { name: '刷新摄像头' }));
    cameraDeferred.resolve({ permission: 'granted', cameras: [] });
    await screen.findByText('已发现 0 个摄像头。');
    expect(screen.getByRole('radio', { name: '左手' })).toBeChecked();
  });

  it('keeps each hand radio hit target local instead of stretching it across the row', async () => {
    renderSettings();
    await screen.findByText(/版本 2\.0\.0 · 构建 test/);
    const rightHand = screen.getByRole('radio', { name: '右手' });
    const hitTarget = rightHand.closest('label');
    expect(hitTarget).toHaveClass('ui-radio');
    expect(hitTarget).not.toHaveClass('ui-field');
    expect(hitTarget?.parentElement).toHaveClass('settings-options');
  });

  it('distinguishes an app-profile denial and resets only that permission before retry', async () => {
    const listCameras = vi.fn(async () => ({ permission: 'windows-denied' as const, cameras: [] }));
    const getCameraPermission = vi.fn(async () => ({ state: 'deny' as const, origin: 'http://tauri.localhost' }));
    const resetCameraPermission = vi.fn(async () => ({ state: 'default' as const, origin: 'http://tauri.localhost' }));
    renderSettings(controller({ listCameras, getCameraPermission, resetCameraPermission }));
    await screen.findByText(/版本 2\.0\.0 · 构建 test/);
    expect(await screen.findByRole('alert')).toHaveTextContent('应用配置文件拒绝了摄像头权限');
    expect(screen.getByRole('button', { name: '重置本应用摄像头权限' })).toBeEnabled();
    await userEvent.setup().click(screen.getByRole('button', { name: '重置本应用摄像头权限' }));
    await waitFor(() => expect(resetCameraPermission).toHaveBeenCalledTimes(1));
    expect(await screen.findByText('已重置本应用摄像头权限，请点击“重试摄像头”。')).toBeInTheDocument();
  });

  it('turns camera enumeration rejection into retryable error and suppresses updates after unmount', async () => {
    const cameraDeferred = deferred<{ permission: 'granted'; cameras: never[] }>(); const listCameras = vi.fn(() => cameraDeferred.promise);
    const { unmount } = renderSettings(controller({ listCameras }));
    await screen.findByText(/版本 2\.0\.0 · 构建 test/);
    const user = userEvent.setup(); await user.click(screen.getByRole('button', { name: '刷新摄像头' }));
    expect(screen.getByRole('button', { name: '枚举中…' })).toBeDisabled();
    await user.click(screen.getByRole('button', { name: '枚举中…' }));
    expect(listCameras).toHaveBeenCalledTimes(2);
    unmount();
    cameraDeferred.reject(new Error('NotReadableError'));
    await Promise.resolve();
  });

  it('contains async check and save failures without unhandled rejection', async () => {
    const unhandled: unknown[] = []; const onUnhandled = (reason: unknown) => unhandled.push(reason); process.on('unhandledRejection', onUnhandled);
    const save = vi.fn(async () => { throw new Error('sidecar unavailable'); }); const testSidecar = vi.fn(async () => ({ ok: false, message: 'sidecar 不可用' }));
    renderSettings(controller({ save, testSidecar }));
    await screen.findByText(/版本 2\.0\.0 · 构建 test/);
    const user = userEvent.setup(); await user.click(screen.getByRole('radio', { name: 'RS485' }));
    await user.click(screen.getByRole('button', { name: '测试 sidecar' }));
    expect(await screen.findByText('检查未通过：sidecar 不可用')).toBeInTheDocument();
    await user.clear(screen.getByLabelText('串口')); await user.type(screen.getByLabelText('串口'), 'COM9');
    await user.click(screen.getByRole('button', { name: '保存设置' }));
    expect(await screen.findByText('保存失败：sidecar unavailable')).toBeInTheDocument();
    expect(unhandled).toHaveLength(0); process.off('unhandledRejection', onUnhandled);
  });

  it('shows live connection state with status indicator', async () => {
    const getConnectionState = vi.fn(async () => ({ state: 'connected' as const, since: Date.now() - 60000 }));
    renderSettings(controller({ getConnectionState }));
    await screen.findByText('已连接');
    expect(screen.getByText('已连接')).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText(/已连接时长 \d+分\d+秒/)).toBeInTheDocument());
    await userEvent.setup().click(screen.getByRole('button', { name: '保存设置' }));
    await waitFor(() => expect(getConnectionState).toHaveBeenCalled());
  });

  it('shows firmware version alongside app version', async () => {
    const getFirmwareVersion = vi.fn(async () => ({ version: '1.2.3', buildDate: '2024-01-15' }));
    renderSettings(controller({ getFirmwareVersion }));
    await screen.findByText(/固件 v1\.2\.3/);
    await userEvent.setup().click(screen.getByRole('button', { name: '保存设置' }));
    await waitFor(() => expect(getFirmwareVersion).toHaveBeenCalled());
  });

  it('resets to factory defaults with confirmation', async () => {
    const user = userEvent.setup();
    const load = vi.fn(async () => ({ ...snapshot, logLevel: 'warn' as const, locale: 'en' as const }));
    const resetToFactory = vi.fn(async () => undefined);
    renderSettings(controller({ load, resetToFactory }));
    await screen.findByText(/版本 2\.0\.0 · 构建 test/);
    await user.click(screen.getByRole('button', { name: /高级设置/ }));
    await user.click(screen.getByRole('button', { name: '恢复默认设置' }));
    expect(screen.getByRole('alertdialog')).toHaveTextContent('确定要恢复所有设置为出厂默认值吗');
    await user.click(screen.getByRole('button', { name: '确认恢复' }));
    await waitFor(() => expect(resetToFactory).toHaveBeenCalled());
    await waitFor(() => expect(load).toHaveBeenCalled());
    expect(await screen.findByText('已恢复出厂设置。')).toBeInTheDocument();
    expect(screen.getByLabelText('日志级别')).toHaveValue('warn');
    expect(screen.getByRole('radio', { name: 'English' }).className).toContain('selected');
  });

  it('changes log level and updates draft', async () => {
    const user = userEvent.setup();
    const setLogLevel = vi.fn(async () => undefined);
    renderSettings(controller({ setLogLevel }));
    await screen.findByText(/版本 2\.0\.0 · 构建 test/);
    await user.click(screen.getByRole('button', { name: /高级设置/ }));
    await user.selectOptions(screen.getByLabelText('日志级别'), 'warn');
    expect(screen.getByLabelText('日志级别')).toHaveValue('warn');
    expect(setLogLevel).toHaveBeenCalledWith('warn');
    expect(screen.getByText('未保存')).toBeInTheDocument();
  });

  it('toggles locale and updates draft', async () => {
    const user = userEvent.setup();
    const setLocale = vi.fn(async () => undefined);
    const getLocale = vi.fn(async () => 'zh' as const);
    renderSettings(controller({ setLocale, getLocale }));
    await screen.findByText(/版本 2\.0\.0 · 构建 test/);
    await user.click(screen.getByRole('radio', { name: 'English' }));
    expect(screen.getByRole('radio', { name: 'English' }).className).toContain('selected');
    expect(setLocale).toHaveBeenCalledWith('en');
    await user.click(screen.getByRole('radio', { name: '中文' }));
    expect(setLocale).toHaveBeenCalledWith('zh');
  });

  it('toggles debug mode in advanced settings', async () => {
    const user = userEvent.setup();
    const setDebugMode = vi.fn(async () => undefined);
    const getDebugMode = vi.fn(async () => true);
    const load = vi.fn(async () => ({ ...snapshot, advanced: { debugMode: true } }));
    renderSettings(controller({ setDebugMode, getDebugMode, load }));
    await screen.findByText(/版本 2\.0\.0 · 构建 test/);
    await user.click(screen.getByRole('button', { name: /高级设置/ }));
    const checkbox = screen.getByLabelText(/调试模式/);
    expect(checkbox).toBeChecked();
    await user.click(checkbox);
    expect(checkbox).not.toBeChecked();
    expect(setDebugMode).toHaveBeenCalledWith(false);
    expect(screen.getByText('未保存')).toBeInTheDocument();
  });
});
