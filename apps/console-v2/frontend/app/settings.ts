import { invoke, isTauri } from '@tauri-apps/api/core';
import type { CameraPermissionStatus, DeviceConfig, ConnectionSnapshot, LogLevel } from '../shared/contracts';
import type { SettingsController, SettingsDraft, SettingsSnapshot, SettingsSaveResult, SidecarCheckResult, OfflineAssetsCheckResult, CameraDevice, CameraPermission, ThemePort, ThemePreference, ConnectionStateInfo, FirmwareVersion } from '../features/settings';
import type { ConsolePorts } from '../shared/contracts';
import { visionAssetUrl } from '../shared/vision-runtime/asset-paths';
import { validateSettingsDraft } from './settings-validation';

const CONFIG_KEY = 'linkerhand-console-v2-config';
const THEME_KEY = 'linkerhand-console-v2-theme';
const CAMERA_KEY = 'linkerhand-console-v2-camera-device-id';
const DEBUG_KEY = 'linkerhand-console-v2-debug-mode';
const readStored = (): Partial<DeviceConfig> | null => {
  try { const value = localStorage.getItem(CONFIG_KEY); return value ? JSON.parse(value) as Partial<DeviceConfig> : null; } catch { return null; }
};
const saveStored = (config: DeviceConfig) => { try { localStorage.setItem(CONFIG_KEY, JSON.stringify(config)); } catch { /* ephemeral runtime */ } };
const readPreferredCamera = (): string | null => {
  try { const stored = localStorage.getItem(CAMERA_KEY); return stored ? JSON.parse(stored) as string : null; } catch { return null; }
};
export function classifyCameraError(error: unknown): CameraPermission {
  const name = error instanceof DOMException ? error.name : error && typeof error === 'object' && 'name' in error ? String((error as { name?: unknown }).name) : '';
  if (name === 'SecurityError') return 'webview-denied';
  if (name === 'NotAllowedError') return 'windows-denied';
  if (name === 'NotFoundError' || name === 'DevicesNotFoundError') return 'no-device';
  if (name === 'NotReadableError' || name === 'TrackStartError' || name === 'AbortError') return 'in-use';
  return error ? 'error' : 'granted';
}

export function createSettingsController(runtime: ConsolePorts, simulator: boolean): SettingsController {
  const listeners = new Set<(snapshot: SettingsSnapshot) => void>();
  let current: SettingsSnapshot | undefined;
  const emit = (snapshot: SettingsSnapshot) => { current = snapshot; listeners.forEach(listener => listener(snapshot)); };
  return {
    async load() {
      const base = await runtime.device.getConfig();
      let config = base;
      if (simulator) config = { ...base, ...readStored(), transport: readStored()?.transport ?? base.transport };
      else {
        try { config = await invoke<DeviceConfig>('settings_load'); } catch { /* first run or older preview build */ }
      }
      const snapshot: SettingsSnapshot = {
        config,
        theme: (localStorage.getItem(THEME_KEY) as ThemePreference | null) ?? 'system',
        version: import.meta.env.VITE_APP_VERSION || '2.0.0-rc.1',
        build: import.meta.env.MODE,
        preferredCameraDeviceId: readPreferredCamera(),
        advanced: { debugMode: localStorage.getItem('linkerhand-console-v2-debug-mode') === 'true' },
      };
      emit(snapshot); return snapshot;
    },
    validate: draft => validateSettingsDraft(draft),
    async save(draft: SettingsDraft): Promise<SettingsSaveResult> {
      const previous = current?.config;
      const config: DeviceConfig = { ...(previous ?? await runtime.device.getConfig()), model: draft.model, hand: draft.hand, transport: draft.transport };
      if (simulator) saveStored(config); else await invoke<void>('settings_save', { config });
      if (draft.preferredCameraDeviceId) localStorage.setItem('linkerhand-console-v2-camera-device-id', JSON.stringify(draft.preferredCameraDeviceId));
      else localStorage.removeItem('linkerhand-console-v2-camera-device-id');
      const restartRequired = Boolean(previous && (previous.model !== config.model || previous.hand !== config.hand));
      const reconnectRequired = Boolean(previous && JSON.stringify(previous.transport) !== JSON.stringify(config.transport));
      const snapshot: SettingsSnapshot = { ...(current ?? {}), config, preferredCameraDeviceId: draft.preferredCameraDeviceId ?? null, advanced: { ...(current?.advanced ?? {}), debugMode: draft.advanced.debugMode } };
      emit(snapshot);
      return { applied: simulator, reconnectRequired, restartRequired, errors: [] };
    },
    async testSidecar(): Promise<SidecarCheckResult> {
      if (simulator) return { ok: true, message: '浏览器模拟器已就绪', detail: '未启动硬件 sidecar' };
      try { return await invoke<SidecarCheckResult>('sidecar_self_check'); } catch (error) { return { ok: false, message: 'sidecar 自检失败', detail: error instanceof Error ? error.message : String(error) }; }
    },
    async checkOfflineAssets(): Promise<OfflineAssetsCheckResult> {
      const resources = [visionAssetUrl('vision/hand_landmarker.task'), visionAssetUrl('vision/wasm/vision_wasm_internal.wasm')];
      const results = await Promise.all(resources.map(async resource => { try { const response = await fetch(resource, { method: 'HEAD', cache: 'no-store' }); return response.ok; } catch { return false; } }));
      return results.every(Boolean) ? { ok: true, message: '离线视觉模型与 WASM 资源可用' } : { ok: false, message: '离线视觉资源缺失或不可读', detail: resources.filter((_, index) => !results[index]).join(', ') };
    },
    async listCameras() {
      if (!navigator.mediaDevices?.enumerateDevices) return { cameras: [], permission: 'error' as const, detail: '当前 WebView 不支持媒体设备 API' };
      try {
        const devices = await navigator.mediaDevices.enumerateDevices();
        let permission: CameraPermission = devices.some(device => device.kind === 'videoinput' && device.label) ? 'granted' : 'prompt';
        let detail: string | undefined;
        if (permission !== 'granted' && navigator.mediaDevices.getUserMedia) {
          try { const stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false }); stream.getTracks().forEach(track => track.stop()); permission = 'granted'; }
          catch (error) { permission = classifyCameraError(error); detail = error instanceof Error ? error.name : String(error); }
        }
        const cameras: CameraDevice[] = (await navigator.mediaDevices.enumerateDevices()).filter(device => device.kind === 'videoinput').map(device => ({ deviceId: device.deviceId, label: device.label || '未命名摄像头', kind: device.kind }));
        if (cameras.length === 0 && permission === 'granted') permission = 'no-device';
        return { cameras, permission, detail };
      } catch (error) { return { cameras: [], permission: classifyCameraError(error) === 'granted' ? 'error' : classifyCameraError(error), detail: error instanceof Error ? error.message : String(error) }; }
    },
    async getCameraPermission(): Promise<CameraPermissionStatus> {
      if (simulator || !isTauri()) return { state: 'default' };
      return invoke<CameraPermissionStatus>('camera_permission_status');
    },
    async resetCameraPermission(): Promise<CameraPermissionStatus> {
      if (simulator || !isTauri()) return { state: 'default' };
      return invoke<CameraPermissionStatus>('reset_camera_permission');
    },
    async openCameraPrivacySettings() {
      if (simulator || !isTauri()) {
        window.open('ms-settings:privacy-webcam', '_blank', 'noopener,noreferrer');
        return;
      }
      await invoke<void>('open_camera_privacy_settings');
    },
    subscribe(listener) { listeners.add(listener); if (current) listener(current); return () => listeners.delete(listener); },
    async getConnectionState(): Promise<ConnectionStateInfo> {
      try {
        const connection = await runtime.device.getConnection();
        const state = connection.state === 'reconnecting' ? 'connecting' : connection.state;
        return { state: state as ConnectionStateInfo['state'] };
      } catch {
        return { state: 'disconnected' };
      }
    },
    async getFirmwareVersion(): Promise<FirmwareVersion> {
      try {
        if (simulator) return { version: 'sim-1.0.0', buildDate: new Date().toISOString().split('T')[0] };
        return await invoke<{ version: string; buildDate?: string }>('firmware_info');
      } catch {
        return { version: 'unknown' };
      }
    },
    async getDebugMode(): Promise<boolean> {
      return localStorage.getItem('linkerhand-console-v2-debug-mode') === 'true';
    },
    async setDebugMode(enabled: boolean) {
      localStorage.setItem('linkerhand-console-v2-debug-mode', String(enabled));
    },
    async getLogLevel(): Promise<LogLevel> {
      return (localStorage.getItem('linkerhand-console-v2-log-level') as LogLevel | null) ?? 'info';
    },
    async setLogLevel(level: LogLevel) {
      localStorage.setItem('linkerhand-console-v2-log-level', level);
    },
    async getLocale(): Promise<'zh' | 'en'> {
      return (localStorage.getItem('linkerhand-console-v2-locale') as 'zh' | 'en' | null) ?? 'zh';
    },
    async setLocale(locale: 'zh' | 'en') {
      localStorage.setItem('linkerhand-console-v2-locale', locale);
    },
    async resetToFactory() {
      localStorage.removeItem(CONFIG_KEY);
      localStorage.removeItem('linkerhand-console-v2-log-level');
      localStorage.removeItem('linkerhand-console-v2-locale');
      localStorage.removeItem('linkerhand-console-v2-debug-mode');
      localStorage.removeItem(CAMERA_KEY);
    },
  };
}

export function createThemePort(): ThemePort {
  const listeners = new Set<(theme: ThemePreference) => void>();
  const get = () => (localStorage.getItem(THEME_KEY) as ThemePreference | null) ?? 'system';
  return { getTheme: get, setTheme(theme) { localStorage.setItem(THEME_KEY, theme); listeners.forEach(listener => listener(theme)); }, subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener); } };
}
