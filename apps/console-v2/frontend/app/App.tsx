import { Component, useEffect, useMemo, useState, type ErrorInfo, type ReactNode } from 'react';
import { Activity, Bot, Cable, CircleHelp, Hand, LayoutDashboard, Menu, Moon, Play, Settings as SettingsIcon, Sun, Terminal, WandSparkles, X, Zap } from 'lucide-react';
import type { DeviceCapabilities, DeviceConfig } from '../shared/contracts';
import { createComposition, type ConsoleComposition } from './composition';
import { isTauriRuntime } from '../shared/contracts';
import { ThemeProvider, useTheme } from '../shared/theme';
import { Badge } from '../shared/ui';
import { DeviceControl } from '../features/device-control';
import { SmartGrasp } from '../features/smart-grasp';
import { VisionMimic } from '../features/vision';
import { RockPaperScissors } from '../features/rock-paper-scissors';
import { ActionCenter } from '../features/actions';
import { Diagnostics } from '../features/diagnostics';
import { Settings } from '../features/settings';
import './styles.css';

type Page = 'device' | 'grasp' | 'vision' | 'rps' | 'actions' | 'diagnostics' | 'settings';
const nav: { id: Page; label: string; icon: typeof Activity; group: string }[] = [
  { id: 'device', label: '设备控制', icon: LayoutDashboard, group: '工作台' }, { id: 'grasp', label: '智能抓取', icon: Hand, group: '工作台' }, { id: 'vision', label: '视觉模仿', icon: WandSparkles, group: '互动' }, { id: 'rps', label: '猜拳互动', icon: Play, group: '互动' }, { id: 'actions', label: '动作中心', icon: Zap, group: '管理' }, { id: 'diagnostics', label: '诊断中心', icon: Terminal, group: '管理' }, { id: 'settings', label: '设置', icon: SettingsIcon, group: '管理' }
];

class GlobalErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) { return { error }; }
  componentDidCatch(error: Error, info: ErrorInfo) { console.error('console-v2 render failure', error, info); }
  render() { return this.state.error ? <div className="loading" role="alert"><strong>页面暂时无法显示</strong><span>{this.state.error.message || '未知界面错误'}</span><button className="button button-primary" onClick={() => this.setState({ error: null })}>重试</button></div> : this.props.children; }
}

function Shell({ runtime }: { runtime: ConsoleComposition }) {
  const [page, setPage] = useState<Page>('device'); const [config, setConfig] = useState<DeviceConfig>(); const [capabilities, setCapabilities] = useState<DeviceCapabilities>(); const [initializationError, setInitializationError] = useState<string>(); const [loadAttempt, setLoadAttempt] = useState(0); const [locked, setLocked] = useState(false); const [safetyError, setSafetyError] = useState<string>(); const [sidebarOpen, setSidebarOpen] = useState(false); const { theme, toggle } = useTheme();
  useEffect(() => { let active = true; setInitializationError(undefined); void Promise.all([runtime.device.getConfig(), runtime.device.getCapabilities()]).then(([nextConfig, nextCapabilities]) => { if (!active) return; setConfig(nextConfig); setCapabilities(nextCapabilities); }).catch(error => { if (active) setInitializationError(error instanceof Error ? error.message : '读取工作区配置失败，请重试或检查诊断日志。'); }); return () => { active = false; }; }, [runtime, loadAttempt]);
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
  if (initializationError) return <div className="loading" role="alert"><div className="logo-mark">LH</div><strong>工作区启动失败</strong><span>{initializationError}</span><button className="button button-primary" onClick={() => setLoadAttempt(value => value + 1)}>重试</button></div>;
  if (!config || !capabilities) return <div className="loading"><div className="logo-mark">LH</div><span>正在准备工作区…</span></div>;
  const go = (next: Page) => { setPage(next); setSidebarOpen(false); };
  const renderPage = () => { switch (page) { case 'device': return <DeviceControl device={runtime.device} telemetry={runtime.telemetry} config={config} capabilities={capabilities} locked={locked} controller={runtime.deviceController} onNavigateToDiagnostics={() => go('diagnostics')} />; case 'grasp': return <SmartGrasp grasp={runtime.grasp} telemetry={runtime.telemetry} tactileAvailable={capabilities.touch.available} locked={locked} model={config.model} controller={runtime.graspController} jointCount={capabilities.jointCount} />; case 'vision': return <VisionMimic vision={runtime.vision} runtime={runtime.visionRuntime} proposalController={runtime.visionProposalController} capabilities={capabilities} locked={locked} />; case 'rps': return <RockPaperScissors vision={runtime.vision} runtime={runtime.visionRuntime} actionController={rpsActionController} capabilities={capabilities} locked={locked} />; case 'actions': return <ActionCenter actions={runtime.actions} motion={runtime.motion} locked={locked} controller={runtime.actionController} />; case 'diagnostics': return <Diagnostics logs={runtime.logs} telemetry={runtime.telemetry} device={runtime.device} config={config} capabilities={capabilities} />; case 'settings': return <Settings model={config.model} transport={config.transport} controller={runtime.settingsController} themePort={runtime.themePort} />; } };
  const stopAll = async () => { setLocked(true); setSafetyError(undefined); const results = await Promise.allSettled([runtime.visionRuntime.stop(), runtime.device.stopAll(), runtime.actionController.stop(), runtime.graspController.abort(), rpsActionController.cancel('locked'), runtime.visionProposalController.revoke('控制已锁定')]); const failures = results.filter(result => result.status === 'rejected'); if (failures.length) setSafetyError(`停止全部动作有 ${failures.length} 项未确认，请保持控制锁定并检查诊断中心。`); };
  const unlock = async () => { setSafetyError(undefined); try { await runtime.device.unlock(); setLocked(false); } catch (error) { setLocked(true); setSafetyError(error instanceof Error ? error.message : '恢复控制失败，控制仍保持锁定。'); } };
  return <div className="app-shell"><aside className={`sidebar ${sidebarOpen ? 'open' : ''}`}><div className="brand"><div className="logo-mark">LH</div><div><strong>LinkerHand</strong><span>CONSOLE V2</span></div><button className="icon-button close-menu" onClick={() => setSidebarOpen(false)} aria-label="关闭菜单"><X size={18} /></button></div><div className="device-chip"><span className="status-dot" /><div><strong>{config.name}</strong><small>{config.model} · {config.hand}</small></div></div><nav aria-label="主导航">{(['工作台', '互动', '管理'] as const).map(group => <div className="nav-group" key={group}><span className="nav-label">{group}</span>{nav.filter(item => item.group === group).map(item => { const Icon = item.icon; return <button className={`nav-item ${page === item.id ? 'active' : ''}`} key={item.id} onClick={() => go(item.id)} aria-current={page === item.id ? 'page' : undefined}><Icon size={18} aria-hidden="true" /><span>{item.label}</span>{item.id === 'diagnostics' && <i className="nav-alert" aria-hidden="true" />}</button>; })}</div>)}</nav><div className="sidebar-footer"><button className="nav-item"><CircleHelp size={18} /><span>帮助与快捷键</span></button><div className="operator"><div className="avatar">OP</div><div><strong>操作员</strong><small>本地工作区</small></div><Menu size={16} /></div></div></aside><main className="main"><header className="topbar"><button className="icon-button menu-button" onClick={() => setSidebarOpen(true)} aria-label="打开菜单"><Menu size={20} /></button><div className="breadcrumbs" aria-label="当前位置"><span>工作台</span><span aria-hidden="true">/</span><strong>{nav.find(item => item.id === page)?.label}</strong></div><div className="top-actions"><button className="icon-button" onClick={toggle} aria-label="切换主题">{theme === 'light' ? <Moon size={18} /> : <Sun size={18} />}</button><span className="top-divider" /><button className={`stop-button ${locked ? 'locked' : ''}`} onClick={locked ? unlock : stopAll}>{locked ? <><Cable size={16} aria-hidden="true" />恢复控制</> : <><Activity size={16} aria-hidden="true" />停止全部动作</>} </button></div></header><div className="content">{locked && <div className="lock-banner"><span><Activity size={17} aria-hidden="true" /><strong>控制已锁定</strong>{safetyError ? '控制保持锁定，但部分停止结果未确认，请保持控制锁定并检查诊断日志。' : '停止请求已完成确认，设备不会继续执行新的动作。'}</span><button onClick={unlock}>恢复控制</button></div>}{safetyError && <div className="permission-note" role="alert">停止/恢复控制未完成：{safetyError}</div>}<div className="page-transition" key={page}>{renderPage()}</div></div></main></div>;
}
function SimulatorBanner() { return isTauriRuntime() ? null : <div className="permission-note" role="status">浏览器模拟器：当前不会连接或伪装真实硬件，所有动作均为确定性本地演示。</div>; }
export function App() { const [runtime] = useState<ConsoleComposition>(() => createComposition()); return <GlobalErrorBoundary><ThemeProvider themePort={runtime.themePort}><SimulatorBanner /><Shell runtime={runtime} /></ThemeProvider></GlobalErrorBoundary>; }
