import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { DeviceConfig, DeviceModel, Hand, Transport } from '../../shared/contracts';
import { useTheme } from '../../shared/theme';
import { Badge, Card } from '../../shared/ui';
import './settings.css';

export const DEVICE_MODELS = ['O6', 'L6', 'L7', 'L10', 'L20', 'G20', 'L21', 'L25'] as const satisfies readonly DeviceModel[];
export type SettingsModel = (typeof DEVICE_MODELS)[number];
export type ThemePreference = 'light' | 'dark' | 'system';
export type CameraPermission = 'granted' | 'denied' | 'prompt' | 'unknown' | 'error';
export interface CameraDevice { deviceId: string; label: string; kind?: 'videoinput' | string }
export interface SettingsAdvancedDraft { autoReconnect: boolean; connectionTimeoutMs: number; diagnostics: boolean }
export interface SettingsDraft { model: SettingsModel; hand: Hand; transport: Transport; preferredCameraDeviceId: string | null; advanced: SettingsAdvancedDraft }
export interface SettingsSnapshot { config: DeviceConfig; preferredCameraDeviceId?: string | null; cameraPermission?: CameraPermission; theme?: ThemePreference; version?: string; build?: string; cameras?: CameraDevice[]; advanced?: Partial<SettingsAdvancedDraft> }
export interface SettingsValidationResult { valid: boolean; errors: Record<string, string> }
export interface SettingsSaveResult { applied: boolean; reconnectRequired: boolean; restartRequired: boolean; errors: string[] }
export interface SidecarCheckResult { ok: boolean; message: string; detail?: string }
export interface OfflineAssetsCheckResult { ok: boolean; message: string; detail?: string }

/** Runtime-owned feature seam. Settings only submits a staged draft. */
export interface SettingsController {
  load(): Promise<SettingsSnapshot>;
  validate(draft: SettingsDraft): SettingsValidationResult | Promise<SettingsValidationResult>;
  save(draft: SettingsDraft): Promise<SettingsSaveResult>;
  testSidecar(): Promise<SidecarCheckResult>;
  checkOfflineAssets(): Promise<OfflineAssetsCheckResult>;
  listCameras(): Promise<{ cameras: CameraDevice[]; permission: CameraPermission }>;
  subscribe(listener: (snapshot: SettingsSnapshot) => void): () => void;
}
/** App-owned theme adapter. The feature does not persist theme or own a provider. */
export interface ThemePort { getTheme(): ThemePreference | Promise<ThemePreference>; setTheme(theme: ThemePreference): void | Promise<void>; subscribe?(listener: (theme: ThemePreference) => void): () => void }

export const defaultAdvanced: SettingsAdvancedDraft = { autoReconnect: true, connectionTimeoutMs: 5000, diagnostics: false };
export function draftFromSnapshot(snapshot: SettingsSnapshot): SettingsDraft { return { model: snapshot.config.model, hand: snapshot.config.hand, transport: snapshot.config.transport, preferredCameraDeviceId: snapshot.preferredCameraDeviceId ?? null, advanced: { ...defaultAdvanced, autoReconnect: snapshot.config.autoReconnect, ...snapshot.advanced } }; }

export function validateSettingsDraft(draft: SettingsDraft): SettingsValidationResult {
  const errors: Record<string, string> = {};
  if (!DEVICE_MODELS.includes(draft.model)) errors.model = '请选择支持的设备型号。';
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
export function switchTransport(draft: SettingsDraft, type: 'can' | 'rs485'): SettingsDraft { if (type === draft.transport.type) return draft; return { ...draft, transport: type === 'can' ? { type: 'can', channel: 'can0' } : { type: 'rs485', port: 'COM3', baudrate: 115200 } }; }
function errorText(error: unknown) { return error instanceof Error ? error.message : typeof error === 'string' ? error : '操作未完成，请查看诊断中心。'; }
function transportLabel(transport: Transport) { return transport.type === 'can' ? `CAN · ${transport.channel}` : `RS485 · ${transport.port} · ${transport.baudrate}`; }
function fallbackConfig(model: string, transport: { type: string; channel?: string; port?: string }): DeviceConfig { return { schemaVersion: 1, deviceId: 'unwired', name: '未接线设备', model: DEVICE_MODELS.includes(model as SettingsModel) ? model as SettingsModel : 'O6', hand: 'right', transport: transport.type === 'rs485' ? { type: 'rs485', port: transport.port ?? '', baudrate: 115200 } : { type: 'can', channel: transport.channel ?? '' }, autoReconnect: true }; }
function normaliseSnapshot(value: SettingsSnapshot | DeviceConfig): SettingsSnapshot { return 'config' in value ? value : { config: value }; }
function cameraPermissionGuidance(permission: CameraPermission, detail?: string) {
  if (permission === 'denied') return '摄像头权限被拒绝。请在系统设置中为本应用开启摄像头权限，然后点击“重试摄像头”。';
  if (permission === 'error') return `无法枚举摄像头${detail ? `：${detail}` : ''}。请确认摄像头已连接且未被其他应用占用，然后点击“重试摄像头”。`;
  return '';
}

interface SettingsProps { model: string; transport: { type: string; channel?: string; port?: string }; controller?: SettingsController; themePort?: ThemePort; version?: string; build?: string }

export function Settings({ model, transport, controller, themePort, version = '2.0.0-rc.1', build = 'dev' }: SettingsProps) {
  const fallbackTheme = useTheme();
  const wired = Boolean(controller);
  const [snapshot, setSnapshot] = useState<SettingsSnapshot>(() => ({ config: fallbackConfig(model, transport), version, build }));
  const [draft, setDraft] = useState<SettingsDraft>(() => draftFromSnapshot(snapshot));
  const [savedDraft, setSavedDraft] = useState<SettingsDraft>();
  const savedDraftRef = useRef<SettingsDraft | undefined>(undefined);
  const [cameras, setCameras] = useState<CameraDevice[]>([]);
  const [permission, setPermission] = useState<CameraPermission>('unknown');
  const [cameraError, setCameraError] = useState('');
  const [theme, setTheme] = useState<ThemePreference>(themePort ? 'system' : fallbackTheme.theme);
  const [status, setStatus] = useState<'loading' | 'saved' | 'dirty' | 'saving' | 'applied' | 'reconnect' | 'restart' | 'error'>('loading');
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [message, setMessage] = useState('');
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [busyCheck, setBusyCheck] = useState<'sidecar' | 'offline' | 'camera' | undefined>();
  const [snapshotVersion, setSnapshotVersion] = useState(version);
  const mountedRef = useRef(true);
  const draftRevisionRef = useRef(0);
  const saveInFlightRef = useRef(false);
  const busyCheckRef = useRef<'sidecar' | 'offline' | 'camera' | undefined>(undefined);
  const cameraRequestRef = useRef(0);
  const applySnapshot = useCallback((value: SettingsSnapshot | DeviceConfig) => { const next = normaliseSnapshot(value); setSnapshot(previous => ({ ...previous, ...next, config: next.config })); setDraft(previous => savedDraftRef.current ? previous : draftFromSnapshot(next)); if (next.cameras) setCameras(next.cameras); if (next.cameraPermission) { setPermission(next.cameraPermission); setCameraError(cameraPermissionGuidance(next.cameraPermission)); } if (next.theme) setTheme(next.theme); if (next.version) setSnapshotVersion(next.version); }, []);

  useEffect(() => { mountedRef.current = true; return () => { mountedRef.current = false; cameraRequestRef.current += 1; }; }, []);

  useEffect(() => {
    let active = true;
    if (!controller) { setStatus('saved'); return () => { active = false; }; }
    void controller.load().then(value => { if (!active) return; const next = normaliseSnapshot(value); setSnapshot(next); const nextDraft = draftFromSnapshot(next); setDraft(nextDraft); draftRevisionRef.current = 0; savedDraftRef.current = nextDraft; setSavedDraft(nextDraft); setPermission(next.cameraPermission ?? 'unknown'); setCameraError(cameraPermissionGuidance(next.cameraPermission ?? 'unknown')); setCameras(next.cameras ?? []); setSnapshotVersion(next.version ?? version); setStatus('saved'); }).catch(error => { if (active) { setStatus('error'); setMessage(`读取设置失败：${errorText(error)}`); } });
    const unsubscribe = controller.subscribe(value => { if (active) applySnapshot(value); });
    return () => { active = false; unsubscribe(); };
  }, [applySnapshot, controller, version]);
  useEffect(() => { if (!themePort) return undefined; let active = true; void Promise.resolve(themePort.getTheme()).then(value => { if (active) setTheme(value); }).catch(() => undefined); const unsubscribe = themePort.subscribe?.(value => { if (active) setTheme(value); }); return () => { active = false; unsubscribe?.(); }; }, [themePort]);

  const setDraftValue = <K extends keyof SettingsDraft>(key: K, value: SettingsDraft[K]) => { draftRevisionRef.current += 1; setDraft(previous => ({ ...previous, [key]: value })); setStatus('dirty'); };
  const setTransport = (next: SettingsDraft['transport']) => { setDraftValue('transport', next); setErrors(previous => { const copy = { ...previous }; delete copy['transport.channel']; delete copy['transport.port']; delete copy['transport.baudrate']; return copy; }); };
  const setThemePreference = (next: ThemePreference) => { setTheme(next); if (themePort) void Promise.resolve(themePort.setTheme(next)).catch(error => setMessage(`主题未应用：${errorText(error)}`)); };
  const save = async () => {
    if (!controller || saveInFlightRef.current || status === 'loading') return;
    const saveRevision = draftRevisionRef.current;
    const saveDraft = draft;
    saveInFlightRef.current = true;
    setStatus('saving');
    setMessage('');
    try {
      const validation = await Promise.resolve(controller.validate(saveDraft));
      if (!mountedRef.current) return;
      if (!validation.valid) {
        if (draftRevisionRef.current === saveRevision) { setErrors(validation.errors); setStatus('dirty'); setMessage('请修正设置后再保存。'); }
        return;
      }
      const result = await controller.save(saveDraft);
      if (!mountedRef.current) return;
      if (draftRevisionRef.current !== saveRevision) {
        setStatus('dirty');
        setMessage('旧草稿已完成保存；当前修改仍未保存。');
        return;
      }
      setErrors(result.errors.reduce<Record<string, string>>((all, item) => ({ ...all, save: item }), {}));
      if (result.errors.length) { setStatus('error'); setMessage(result.errors.join('；')); return; }
      savedDraftRef.current = saveDraft;
      setSavedDraft(saveDraft);
      setStatus(result.restartRequired ? 'restart' : result.reconnectRequired ? 'reconnect' : result.applied ? 'applied' : 'saved');
      setMessage(result.restartRequired ? '已保存。需要重启服务后生效。' : result.reconnectRequired ? '已保存。需要重新连接设备后生效。' : result.applied ? '已保存并由运行时确认应用。' : '已保存，等待运行时确认。');
    } catch (error) {
      if (!mountedRef.current) return;
      if (draftRevisionRef.current !== saveRevision) { setStatus('dirty'); setMessage('保存旧草稿失败；当前修改仍未保存。'); }
      else { setStatus('error'); setMessage(`保存失败：${errorText(error)}`); }
    } finally { saveInFlightRef.current = false; }
  };
  const runCheck = async (kind: 'sidecar' | 'offline' | 'camera') => {
    if (!controller || busyCheckRef.current) return;
    const cameraRequest = kind === 'camera' ? ++cameraRequestRef.current : cameraRequestRef.current;
    busyCheckRef.current = kind;
    setBusyCheck(kind); setMessage('');
    try {
      if (kind === 'camera') {
        const result = await controller.listCameras();
        if (!mountedRef.current || cameraRequest !== cameraRequestRef.current) return;
        setCameras(result.cameras); setPermission(result.permission);
        const guidance = cameraPermissionGuidance(result.permission);
        setCameraError(guidance);
        setMessage(guidance || `已发现 ${result.cameras.length} 个摄像头。`);
      } else {
        const result = kind === 'sidecar' ? await controller.testSidecar() : await controller.checkOfflineAssets();
        if (!mountedRef.current) return;
        setMessage(`${result.ok ? '检查通过' : '检查未通过'}：${result.message}${result.detail ? `（${result.detail}）` : ''}`);
      }
    } catch (error) {
      if (!mountedRef.current) return;
      const detail = errorText(error);
      setMessage(kind === 'camera' ? cameraPermissionGuidance('error', detail) : `检查失败：${detail}`);
      if (kind === 'camera') { setPermission('error'); setCameraError(cameraPermissionGuidance('error', detail)); }
    } finally {
      if (busyCheckRef.current === kind) busyCheckRef.current = undefined;
      if (mountedRef.current && (kind !== 'camera' || cameraRequest === cameraRequestRef.current)) setBusyCheck(undefined);
    }
  };
  const dirty = status === 'dirty' || Boolean(savedDraft && JSON.stringify(savedDraft) !== JSON.stringify(draft));
  const statusLabel = dirty ? '未保存' : status === 'loading' ? '读取中' : status === 'saving' ? '保存中' : status === 'reconnect' ? '需要重连' : status === 'restart' ? '需要重启服务' : status === 'error' ? '检查失败' : status === 'applied' ? '已应用' : '已保存';
  const editingDisabled = status === 'saving';
  const versionLabel = snapshot.version ?? snapshotVersion;
  const cameraSelection = draft.preferredCameraDeviceId ?? '';
  const rs485Transport = draft.transport.type === 'rs485' ? draft.transport : undefined;
  const transportHint = useMemo(() => draft.transport.type === 'can' ? '由运行时选择 CAN channel；不会在此页面直接打开硬件。' : '串口只在保存后交给运行时；格式示例 COM3。', [draft.transport.type]);

  return <div className="stack settings-feature">
    <div className="page-heading"><div><p className="eyebrow">系统 / 设置</p><h1>设置</h1><p>保存的是设备配置草稿；硬件状态仍以运行时返回为准。</p></div><div className="settings-heading-status"><Badge tone={!wired ? 'amber' : dirty ? 'amber' : status === 'error' ? 'red' : 'green'}>{!wired ? '未接线' : statusLabel}</Badge><button className="button button-primary" disabled={!wired || editingDisabled || status === 'loading'} onClick={() => void save()}>保存设置</button></div></div>
    {!wired && <div className="settings-notice" role="status">当前页面未注入 SettingsController，仅展示已知配置；保存、自检和摄像头枚举已禁用。</div>}
    {message && <div className={`settings-message ${status === 'error' ? 'is-error' : ''}`} role={status === 'error' ? 'alert' : 'status'}>{message}</div>}
    <div className="settings-grid">
      <Card><div className="card-header"><div><h2>设备连接</h2><span className="muted">所有字段进入 staged draft，提交前不会改变运行中设备。</span></div><Badge>{transportLabel(draft.transport)}</Badge></div><div className="settings-fields">
        <label>设备型号<select value={draft.model} disabled={!wired || editingDisabled} onChange={event => setDraftValue('model', event.target.value as SettingsModel)}>{DEVICE_MODELS.map(item => <option key={item} value={item}>{item}</option>)}</select></label>
        <fieldset><legend>左右手</legend><div className="settings-options"><label><input type="radio" name="hand" checked={draft.hand === 'left'} disabled={!wired || editingDisabled} onChange={() => setDraftValue('hand', 'left')} />左手</label><label><input type="radio" name="hand" checked={draft.hand === 'right'} disabled={!wired || editingDisabled} onChange={() => setDraftValue('hand', 'right')} />右手</label></div></fieldset>
        <fieldset><legend>传输方式</legend><div className="transport-switch"><button type="button" className={draft.transport.type === 'can' ? 'selected' : ''} disabled={!wired || editingDisabled} onClick={() => { draftRevisionRef.current += 1; setDraft(switchTransport(draft, 'can')); setStatus('dirty'); }}>CAN</button><button type="button" className={draft.transport.type === 'rs485' ? 'selected' : ''} disabled={!wired || editingDisabled} onClick={() => { draftRevisionRef.current += 1; setDraft(switchTransport(draft, 'rs485')); setStatus('dirty'); }}>RS485</button></div></fieldset>
        {draft.transport.type === 'can' ? <label>CAN channel<input value={draft.transport.channel} disabled={!wired || editingDisabled} onChange={event => setTransport({ type: 'can', channel: event.target.value })} aria-invalid={Boolean(errors['transport.channel'])} />{errors['transport.channel'] && <small className="field-error">{errors['transport.channel']}</small>}</label> : rs485Transport ? <div className="settings-two-fields"><label>串口<input value={rs485Transport.port} disabled={!wired || editingDisabled} onChange={event => setTransport({ type: 'rs485', port: event.target.value, baudrate: rs485Transport.baudrate })} aria-invalid={Boolean(errors['transport.port'])} />{errors['transport.port'] && <small className="field-error">{errors['transport.port']}</small>}</label><label>波特率<select value={rs485Transport.baudrate} disabled={!wired || editingDisabled} onChange={event => setTransport({ type: 'rs485', port: rs485Transport.port, baudrate: Number(event.target.value) })}>{[9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600].map(rate => <option key={rate} value={rate}>{rate}</option>)}</select>{errors['transport.baudrate'] && <small className="field-error">{errors['transport.baudrate']}</small>}</label></div> : null}
        <p className="muted settings-hint">{transportHint}</p>
      </div></Card>
      <Card><div className="card-header"><div><h2>摄像头</h2><span className="muted">只保存首选 deviceId；不会创建 VisionRuntime 或打开第二个摄像头。</span></div><Badge tone={permission === 'granted' ? 'green' : permission === 'denied' || permission === 'error' ? 'red' : 'amber'}>{permission === 'granted' ? '权限已允许' : permission === 'denied' ? '权限被拒绝' : permission === 'error' ? '枚举失败' : '权限未确认'}</Badge></div><div className="camera-controls"><label>首选摄像头<select value={cameraSelection} disabled={!wired || cameras.length === 0 || editingDisabled} onChange={event => setDraftValue('preferredCameraDeviceId', event.target.value || null)}><option value="">不指定</option>{cameras.map(camera => <option value={camera.deviceId} key={camera.deviceId}>{camera.label || camera.deviceId}</option>)}</select></label><button className="button button-secondary" disabled={!wired || busyCheck === 'camera'} onClick={() => void runCheck('camera')}>{busyCheck === 'camera' ? '枚举中…' : permission === 'denied' || permission === 'error' ? '重试摄像头' : '刷新摄像头'}</button></div>{cameraError && <p className="camera-error" role="alert">{cameraError}</p>}{cameras.length === 0 && !cameraError && <p className="muted camera-empty">尚未枚举摄像头。请点击刷新；权限和错误均来自 controller。</p>}</Card>
      <Card><div className="card-header"><div><h2>外观</h2><span className="muted">主题由应用 ThemePort 持有。</span></div><Badge>{theme === 'system' ? '跟随系统' : theme === 'light' ? '浅色' : '深色'}</Badge></div><div className="theme-options" role="radiogroup" aria-label="主题"><label className={theme === 'light' ? 'selected' : ''}><input type="radio" name="theme" checked={theme === 'light'} disabled={editingDisabled} onChange={() => setThemePreference('light')} />浅色</label><label className={theme === 'dark' ? 'selected' : ''}><input type="radio" name="theme" checked={theme === 'dark'} disabled={editingDisabled} onChange={() => setThemePreference('dark')} />深色</label><label className={theme === 'system' ? 'selected' : ''}><input type="radio" name="theme" checked={theme === 'system'} disabled={editingDisabled} onChange={() => setThemePreference('system')} />跟随系统</label></div></Card>
      <Card><div className="card-header"><div><h2>版本与离线资源</h2><span className="muted">版本 {versionLabel} · 构建 {snapshot.build ?? build}</span></div><Badge tone="green">本地应用</Badge></div><div className="check-actions"><button className="button button-secondary" disabled={!wired || busyCheck === 'offline'} onClick={() => void runCheck('offline')}>{busyCheck === 'offline' ? '检查中…' : '检查离线资源'}</button><button className="button button-secondary" disabled={!wired || busyCheck === 'sidecar'} onClick={() => void runCheck('sidecar')}>{busyCheck === 'sidecar' ? '检查中…' : '测试 sidecar'}</button></div><p className="muted">V2 不迁移旧配置；如需使用旧版本设置，请重新确认本页草稿。</p></Card>
    </div>
    <Card className="settings-advanced"><button className="advanced-toggle" type="button" aria-expanded={advancedOpen} onClick={() => setAdvancedOpen(value => !value)} disabled={editingDisabled}><span><strong>高级设置</strong><small>自动重连、连接超时、诊断参数</small></span><span aria-hidden="true">{advancedOpen ? '收起' : '展开'}</span></button>{advancedOpen && <div className="advanced-content"><label className="checkbox-row"><input type="checkbox" checked={draft.advanced.autoReconnect} disabled={!wired || editingDisabled} onChange={event => { setDraftValue('advanced', { ...draft.advanced, autoReconnect: event.target.checked }); }} />自动重连<span className="muted">由运行时决定重连时机</span></label><label>连接超时（ms）<input type="number" min="100" max="120000" step="100" value={draft.advanced.connectionTimeoutMs} disabled={!wired || editingDisabled} onChange={event => setDraftValue('advanced', { ...draft.advanced, connectionTimeoutMs: Number(event.target.value) })} aria-invalid={Boolean(errors.connectionTimeoutMs)} />{errors.connectionTimeoutMs && <small className="field-error">{errors.connectionTimeoutMs}</small>}</label><label className="checkbox-row"><input type="checkbox" checked={draft.advanced.diagnostics} disabled={!wired || editingDisabled} onChange={event => { setDraftValue('advanced', { ...draft.advanced, diagnostics: event.target.checked }); }} />允许诊断参数<span className="muted">仅供排障，不改变普通操作员默认视图</span></label></div>}</Card>
    {dirty && <p className="muted settings-footer-note">有未保存更改。关闭页面不会将草稿应用到硬件。</p>}
  </div>;
}
