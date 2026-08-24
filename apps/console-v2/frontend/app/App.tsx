import { Component, useEffect, useMemo, useState, type ErrorInfo, type ReactNode } from 'react';
import { Activity, Bot, Cable, CircleHelp, Hand, LayoutDashboard, Menu, Moon, Play, Settings as SettingsIcon, Sun, Terminal, WandSparkles, X, Zap } from 'lucide-react';
import type { DeviceCapabilities, DeviceConfig, LogPort } from '../shared/contracts';
import type { ConnectionStateInfo } from '../features/settings';
import { createComposition, type ConsoleComposition } from './composition';
import { isTauriRuntime } from '../shared/contracts';
import { ThemeProvider, useTheme } from '../shared/theme';
import { Badge } from '../shared/ui';
import { I18nProvider, useI18n, type CatalogKey } from '../shared/i18n';
import { DeviceControl } from '../features/device-control';
import { SmartGrasp } from '../features/smart-grasp';
import { VisionMimic } from '../features/vision';
import { RockPaperScissors } from '../features/rock-paper-scissors';
import { ActionCenter } from '../features/actions';
import type { ProgrammedAction } from '../features/actions';
import type { DeviceControlQuickAction } from '../features/device-control';
import { Diagnostics } from '../features/diagnostics';
import { Settings } from '../features/settings';
import { createVirtualTelemetry, type VirtualTelemetryPort } from '../shared/telemetry/virtual';
import './styles.css';

type Page = 'device' | 'grasp' | 'vision' | 'rps' | 'actions' | 'diagnostics' | 'settings';
const nav: { id: Page; label: CatalogKey; icon: typeof Activity; group: CatalogKey }[] = [
  { id: 'device', label: 'app.nav.device', icon: LayoutDashboard, group: 'app.group.workspace' }, { id: 'grasp', label: 'app.nav.grasp', icon: Hand, group: 'app.group.workspace' }, { id: 'vision', label: 'app.nav.vision', icon: WandSparkles, group: 'app.group.interaction' }, { id: 'rps', label: 'app.nav.rps', icon: Play, group: 'app.group.interaction' }, { id: 'actions', label: 'app.nav.actions', icon: Zap, group: 'app.group.management' }, { id: 'diagnostics', label: 'app.nav.diagnostics', icon: Terminal, group: 'app.group.management' }, { id: 'settings', label: 'app.nav.settings', icon: SettingsIcon, group: 'app.group.management' }
];

export function recordDebugModeChange(logs: LogPort, enabled: boolean): Promise<void> {
  return logs.record?.({
    level: 'info',
    event: enabled ? 'debug_mode.enabled' : 'debug_mode.disabled',
    message: enabled ? '调试模式已开启' : '调试模式已关闭',
    fields: { enabled, source: 'settings' },
  }) ?? Promise.resolve();
}

const ACTION_CENTER_STORAGE_KEY = 'linkerhand-console-v2-action-center';
export type ActionCenterStorage = { localPresets: DeviceControlQuickAction[]; programmedActions: ProgrammedAction[] };
export const readActionCenterStorage = (): ActionCenterStorage => {
  try {
    const value = JSON.parse(localStorage.getItem(ACTION_CENTER_STORAGE_KEY) ?? '{}') as Partial<ActionCenterStorage>;
    return { localPresets: Array.isArray(value.localPresets) ? value.localPresets : [], programmedActions: Array.isArray(value.programmedActions) ? value.programmedActions : [] };
  } catch { return { localPresets: [], programmedActions: [] }; }
};
export const writeActionCenterStorage = (value: ActionCenterStorage): void => { try { localStorage.setItem(ACTION_CENTER_STORAGE_KEY, JSON.stringify(value)); } catch { /* ephemeral runtime */ } };

class GlobalErrorBoundary extends Component<{ children: ReactNode; fallback?: (error: Error, retry: () => void) => ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) { return { error }; }
  componentDidCatch(error: Error, info: ErrorInfo) { console.error('console-v2 render failure', error, info); }
  render() { return this.state.error ? this.props.fallback?.(this.state.error, () => this.setState({ error: null })) ?? <div className="loading" role="alert"><strong>页面暂时无法显示</strong><span>{this.state.error.message || '未知界面错误'}</span><button className="button button-primary" onClick={() => this.setState({ error: null })}>重试</button></div> : this.props.children; }
}

function Shell({ runtime }: { runtime: ConsoleComposition }) {
  const { t } = useI18n();
  const [page, setPage] = useState<Page>('device'); const [config, setConfig] = useState<DeviceConfig>(); const [capabilities, setCapabilities] = useState<DeviceCapabilities>(); const [initializationError, setInitializationError] = useState<string>(); const [loadAttempt, setLoadAttempt] = useState(0); const [locked, setLocked] = useState(false); const [safetyError, setSafetyError] = useState<string>(); const [sidebarOpen, setSidebarOpen] = useState(false); const [debugMode, setDebugMode] = useState(false); const [diagnosticsAlert, setDiagnosticsAlert] = useState(false); const [customPresets, setCustomPresets] = useState<DeviceControlQuickAction[]>([]); const [actionCenterState, setActionCenterState] = useState<ActionCenterStorage>(readActionCenterStorage); const [physicalConnected, setPhysicalConnected] = useState(false); const [preferredCameraDeviceId, setPreferredCameraDeviceId] = useState<string | null>(() => { try { const stored = localStorage.getItem('linkerhand-console-v2-camera-device-id'); return stored ? JSON.parse(stored) : null; } catch { return null; } }); const { theme, toggle } = useTheme();
  const updateActionCenterState = (next: Partial<ActionCenterStorage>) => setActionCenterState(previous => {
    const value = { ...previous, ...next };
    writeActionCenterStorage(value);
    return value;
  });
  const isPhysicalDevice = !runtime.simulator && physicalConnected;
  // Keep one virtual telemetry stream at the shell boundary so every feature
  // observes and updates the same debug-hand pose.
  const virtualTelemetry = useMemo<VirtualTelemetryPort | undefined>(() => debugMode && !isPhysicalDevice ? createVirtualTelemetry(capabilities?.jointCount ?? 0) : undefined, [debugMode, isPhysicalDevice, capabilities?.jointCount]);
  useEffect(() => { let active = true; setInitializationError(undefined); void Promise.all([runtime.device.getConfig(), runtime.device.getCapabilities()]).then(([nextConfig, nextCapabilities]) => { if (!active) return; setConfig(nextConfig); setCapabilities(nextCapabilities); }).catch(error => { if (active) setInitializationError(error instanceof Error ? error.message : '读取工作区配置失败，请重试或检查诊断日志。'); }); return () => { active = false; }; }, [runtime, loadAttempt]);
  useEffect(() => { if (runtime.simulator) { setPhysicalConnected(false); return; } let mounted = true; const unsubscribe = runtime.deviceController.subscribeConnection(snapshot => { if (mounted) setPhysicalConnected(snapshot.state === 'connected'); }); return () => { mounted = false; unsubscribe(); }; }, [runtime]);
  useEffect(() => { const unsubscribe = runtime.settingsController.subscribe(snapshot => { if (snapshot.preferredCameraDeviceId !== undefined) setPreferredCameraDeviceId(snapshot.preferredCameraDeviceId); }); return unsubscribe; }, [runtime]);
  useEffect(() => {
    // React StrictMode replays effect cleanup/setup in development. A replay
    // is not an application shutdown, so cleanup must only stop the current
    // session and must never permanently dispose the shared runtime. The
    // browser lifecycle events are the real terminal boundary for disposing
    // its worker and listeners.
    const stop = () => { void runtime.visionRuntime.stop().catch(() => undefined); };
    const dispose = () => { void Promise.resolve(runtime.visionRuntime.dispose?.()).catch(() => undefined); };
    window.addEventListener('pagehide', dispose);
    window.addEventListener('beforeunload', dispose);
    return () => {
      window.removeEventListener('pagehide', dispose);
      window.removeEventListener('beforeunload', dispose);
      stop();
    };
  }, [runtime]);
  const rpsActionController = useMemo(() => capabilities ? runtime.createRpsActionController(capabilities) : runtime.rpsActionController, [capabilities, runtime]);
  useEffect(() => { void runtime.settingsController.getDebugMode().then(value => { if (value) setDebugMode(true); }); }, [runtime]);
  useEffect(() => {
    let previousError: string | null = null;
    return runtime.visionRuntime.subscribe(snapshot => {
      const error = snapshot.lastError;
      const key = error ? error.code + ':' + error.message : null;
      if (!error || key === previousError) return;
      previousError = key;
      void runtime.logs.record?.({ level: 'error', event: 'vision.error', message: error.message, fields: { code: error.code, state: snapshot.state, source: snapshot.owner } });
    });
  }, [runtime]);
  if (initializationError) return <div className="loading" role="alert"><div className="logo-mark">LH</div><strong>{t('app.error.workspaceStart')}</strong><span>{initializationError}</span><button className="button button-primary" onClick={() => setLoadAttempt(value => value + 1)}>{t('app.error.retry')}</button></div>;
  if (!config || !capabilities) return <div className="loading"><div className="logo-mark">LH</div><span>{t('app.loading.prepareWorkspace')}</span></div>;
  const go = (next: Page) => { setPage(next); setSidebarOpen(false); };
  const renderPage = () => { switch (page) { case 'device': return <DeviceControl device={runtime.device} telemetry={runtime.telemetry} config={config} capabilities={capabilities} locked={locked} controller={runtime.deviceController} debugMode={debugMode} isPhysicalDevice={isPhysicalDevice} virtualTelemetry={virtualTelemetry} customPresets={customPresets} onCustomPresetsChange={setCustomPresets} onNavigateToDiagnostics={() => go('diagnostics')} />; case 'grasp': return <SmartGrasp grasp={runtime.grasp} telemetry={runtime.telemetry} tactileAvailable={capabilities.touch.available} locked={locked} model={config.model} controller={runtime.graspController} jointCount={capabilities.jointCount} debugMode={debugMode} isPhysicalDevice={isPhysicalDevice} />; case 'vision': return <VisionMimic vision={runtime.vision} runtime={runtime.visionRuntime} proposalController={runtime.visionProposalController} capabilities={capabilities} locked={locked} debugMode={debugMode} isPhysicalDevice={isPhysicalDevice} preferredCameraDeviceId={preferredCameraDeviceId} />; case 'rps': return <RockPaperScissors vision={runtime.vision} runtime={runtime.visionRuntime} actionController={rpsActionController} capabilities={capabilities} locked={locked} debugMode={debugMode} isPhysicalDevice={isPhysicalDevice} preferredCameraDeviceId={preferredCameraDeviceId} />; case 'actions': return <ActionCenter actions={runtime.actions} motion={runtime.motion} locked={locked} controller={runtime.actionController} customPresets={customPresets} localPresets={actionCenterState.localPresets} onLocalPresetsChange={localPresets => updateActionCenterState({ localPresets })} programmedActions={actionCenterState.programmedActions} onProgrammedActionsChange={programmedActions => updateActionCenterState({ programmedActions })} capabilities={capabilities} telemetry={runtime.telemetry} debugMode={debugMode} isPhysicalDevice={isPhysicalDevice} onVirtualPoseChange={positions => virtualTelemetry?.setPositions(positions)} />; case 'diagnostics': return <Diagnostics logs={runtime.logs} telemetry={runtime.telemetry} device={runtime.device} config={config} capabilities={capabilities} debugMode={debugMode} isPhysicalDevice={isPhysicalDevice} virtualTelemetry={virtualTelemetry} onAlertChange={setDiagnosticsAlert} />; case 'settings': return <Settings model={config.model} transport={config.transport} controller={runtime.settingsController} themePort={runtime.themePort} debugMode={debugMode} onDebugModeChange={enabled => { setDebugMode(enabled); void recordDebugModeChange(runtime.logs, enabled); }} />; } };
  const stopAll = async () => { setLocked(true); setSafetyError(undefined); const results = await Promise.allSettled([runtime.visionRuntime.stop(), runtime.device.stopAll(), runtime.actionController.stop(), runtime.graspController.abort(), rpsActionController.cancel('locked'), runtime.visionProposalController.revoke('控制已锁定')]); const failures = results.filter(result => result.status === 'rejected'); if (failures.length) setSafetyError(`停止全部动作有 ${failures.length} 项未确认，请保持控制锁定并检查诊断中心。`); };
  const unlock = async () => { setSafetyError(undefined); try { await runtime.device.unlock(); setLocked(false); } catch (error) { setLocked(true); setSafetyError(error instanceof Error ? error.message : '恢复控制失败，控制仍保持锁定。'); } };
  return <div className="app-shell"><aside className={`sidebar ${sidebarOpen ? 'open' : ''}`}><div className="brand"><div className="logo-mark">LH</div><div><strong>LinkerHand</strong><span>{t('app.brand.console')}</span></div><button className="icon-button close-menu" onClick={() => setSidebarOpen(false)} aria-label={t('app.aria.closeMenu')}><X size={18} /></button></div><div className="device-chip"><span className="status-dot" /><div><strong>{config.name}</strong><small>{config.model} · {config.hand}</small></div></div><nav aria-label={t('app.aria.mainNavigation')}>{(['app.group.workspace', 'app.group.interaction', 'app.group.management'] as const).map(group => <div className="nav-group" key={group}>{nav.filter(item => item.group === group).map(item => { const Icon = item.icon; return <button className={`nav-item ${page === item.id ? 'active' : ''}`} key={item.id} onClick={() => go(item.id)} aria-current={page === item.id ? 'page' : undefined}><Icon size={18} aria-hidden="true" /><span>{t(item.label)}</span>{item.id === 'diagnostics' && diagnosticsAlert && <i className="nav-alert" aria-hidden="true" />}</button>; })}</div>)}</nav><div className="sidebar-footer"><button className="nav-item"><CircleHelp size={18} /><span>{t('app.help')}</span></button><div className="operator"><div className="avatar">OP</div><div><strong>{t('app.operator')}</strong><small>{t('app.localWorkspace')}</small></div><Menu size={16} /></div></div></aside><main className="main"><header className="topbar"><button className="icon-button menu-button" onClick={() => setSidebarOpen(true)} aria-label={t('app.aria.openMenu')}><Menu size={20} /></button><div className="breadcrumbs" aria-label={t('app.aria.currentLocation')}><span>{t('app.group.workspace')}</span><span aria-hidden="true">/</span><strong>{t(nav.find(item => item.id === page)?.label ?? 'app.nav.device')}</strong></div><div className="top-actions"><button className="icon-button" onClick={toggle} aria-label={t('app.aria.toggleTheme')}>{theme === 'light' ? <Moon size={18} /> : <Sun size={18} />}</button><span className="top-divider" /><button className={`stop-button ${locked ? 'locked' : ''}`} onClick={locked ? unlock : stopAll}>{locked ? <><Cable size={16} aria-hidden="true" />{t('app.safety.restore')}</> : <><Activity size={16} aria-hidden="true" />{t('app.safety.stopAll')}</>} </button></div></header><div className="content">{locked && <div className="lock-banner"><span><Activity size={17} aria-hidden="true" /><strong>{t('app.safety.locked')}</strong>{safetyError ? t('app.safety.unconfirmed') : t('app.safety.confirmed')}</span><button onClick={unlock}>{t('app.safety.restore')}</button></div>}{safetyError && <div className="permission-note" role="alert">{t('app.safety.failed', { detail: safetyError })}</div>}<div className="page-transition" key={page}>{renderPage()}</div></div></main></div>;
}
function SimulatorBanner() { const { t } = useI18n(); return isTauriRuntime() ? null : <div className="permission-note" role="status">{t('app.simulator.banner')}</div>; }
function AppContent() { const { t } = useI18n(); const [runtime] = useState<ConsoleComposition>(() => createComposition()); return <GlobalErrorBoundary fallback={(error, retry) => <div className="loading" role="alert"><strong>{t('app.error.renderTitle')}</strong><span>{error.message || t('app.error.unknown')}</span><button className="button button-primary" onClick={retry}>{t('app.error.retry')}</button></div>}><ThemeProvider themePort={runtime.themePort}><SimulatorBanner /><Shell runtime={runtime} /></ThemeProvider></GlobalErrorBoundary>; }
export function App() { return <I18nProvider><AppContent /></I18nProvider>; }
