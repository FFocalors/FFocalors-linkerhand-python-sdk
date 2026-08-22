import { invoke, isTauri } from '@tauri-apps/api/core';
import type { DeviceConfig } from '../shared/contracts';
import type { SettingsController, SettingsDraft, SettingsSnapshot, SettingsSaveResult, SidecarCheckResult, OfflineAssetsCheckResult, CameraDevice, CameraPermission, ThemePort, ThemePreference } from '../features/settings';
import { draftFromSnapshot, validateSettingsDraft } from '../features/settings';
import type { ConsolePorts } from '../shared/contracts';
import { visionAssetUrl } from '../shared/vision-runtime';

const CONFIG_KEY = 'linkerhand-console-v2-config';
const THEME_KEY = 'linkerhand-console-v2-theme';
const readStored = (): Partial<DeviceConfig> | null => {
  try { const value = localStorage.getItem(CONFIG_KEY); return value ? JSON.parse(value) as Partial<DeviceConfig> : null; } catch { return null; }
};
const saveStored = (config: DeviceConfig) => { try { localStorage.setItem(CONFIG_KEY, JSON.stringify(config)); } catch { /* ephemeral runtime */ } };
const cameraPermission = (error?: unknown): CameraPermission => {
  const name = error instanceof DOMException ? error.name : '';
  return name === 'NotAllowedError' || name === 'SecurityError' ? 'denied' : error ? 'error' : 'granted';
};

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
      const snapshot: SettingsSnapshot = { config, theme: (localStorage.getItem(THEME_KEY) as ThemePreference | null) ?? 'system', version: import.meta.env.VITE_APP_VERSION || '2.0.0-rc.1', build: import.meta.env.MODE };
      emit(snapshot); return snapshot;
    },
    validate: draft => validateSettingsDraft(draft),
    async save(draft: SettingsDraft): Promise<SettingsSaveResult> {
      const previous = current?.config;
      const config: DeviceConfig = { ...(previous ?? await runtime.device.getConfig()), model: draft.model, hand: draft.hand, transport: draft.transport };
      if (simulator) saveStored(config); else await invoke<void>('settings_save', { config });
      const restartRequired = Boolean(previous && (previous.model !== config.model || previous.hand !== config.hand));
      const reconnectRequired = Boolean(previous && JSON.stringify(previous.transport) !== JSON.stringify(config.transport));
      const snapshot: SettingsSnapshot = { ...(current ?? {}), config };
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
      if (!navigator.mediaDevices?.enumerateDevices) return { cameras: [], permission: 'error' as const };
      try {
        const devices = await navigator.mediaDevices.enumerateDevices();
        let permission: CameraPermission = devices.some(device => device.kind === 'videoinput' && device.label) ? 'granted' : 'prompt';
        if (permission !== 'granted' && navigator.mediaDevices.getUserMedia) {
          try { const stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false }); stream.getTracks().forEach(track => track.stop()); permission = 'granted'; }
          catch (error) { permission = cameraPermission(error); }
        }
        const cameras: CameraDevice[] = (await navigator.mediaDevices.enumerateDevices()).filter(device => device.kind === 'videoinput').map(device => ({ deviceId: device.deviceId, label: device.label || '未命名摄像头', kind: device.kind }));
        return { cameras, permission };
      } catch (error) { return { cameras: [], permission: cameraPermission(error) === 'granted' ? 'error' : cameraPermission(error) }; }
    },
    subscribe(listener) { listeners.add(listener); if (current) listener(current); return () => listeners.delete(listener); },
  };
}

export function createThemePort(): ThemePort {
  const listeners = new Set<(theme: ThemePreference) => void>();
  const get = () => (localStorage.getItem(THEME_KEY) as ThemePreference | null) ?? 'system';
  return { getTheme: get, setTheme(theme) { localStorage.setItem(THEME_KEY, theme); listeners.forEach(listener => listener(theme)); }, subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener); } };
}
