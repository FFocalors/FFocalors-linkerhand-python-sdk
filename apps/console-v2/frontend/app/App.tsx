import { useEffect, useState } from 'react';
import { Activity, Bot, Cable, CircleHelp, Hand, LayoutDashboard, Menu, Moon, Play, Settings as SettingsIcon, Sun, Terminal, WandSparkles, X, Zap } from 'lucide-react';
import { mockRuntime } from '../shared/contracts/mock-runtime';
import type { DeviceCapabilities, DeviceConfig } from '../shared/contracts';
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

function Shell() {
  const [page, setPage] = useState<Page>('device'); const [config, setConfig] = useState<DeviceConfig>(); const [capabilities, setCapabilities] = useState<DeviceCapabilities>(); const [locked, setLocked] = useState(false); const [sidebarOpen, setSidebarOpen] = useState(false); const { theme, toggle } = useTheme();
  useEffect(() => { void Promise.all([mockRuntime.device.getConfig(), mockRuntime.device.getCapabilities()]).then(([nextConfig, nextCapabilities]) => { setConfig(nextConfig); setCapabilities(nextCapabilities); }); }, []);
  if (!config || !capabilities) return <div className="loading"><div className="logo-mark">LH</div><span>正在准备工作区…</span></div>;
  const go = (next: Page) => { setPage(next); setSidebarOpen(false); };
  const renderPage = () => { switch (page) { case 'device': return <DeviceControl device={mockRuntime.device} telemetry={mockRuntime.telemetry} config={config} capabilities={capabilities} locked={locked} />; case 'grasp': return <SmartGrasp grasp={mockRuntime.grasp} locked={locked} />; case 'vision': return <VisionMimic vision={mockRuntime.vision} capabilities={capabilities} locked={locked} />; case 'rps': return <RockPaperScissors vision={mockRuntime.vision} capabilities={capabilities} locked={locked} />; case 'actions': return <ActionCenter actions={mockRuntime.actions} motion={mockRuntime.motion} locked={locked} />; case 'diagnostics': return <Diagnostics logs={mockRuntime.logs} />; case 'settings': return <Settings model={config.model} address={config.address} />; } };
  const stopAll = async () => { await mockRuntime.device.stopAll(); setLocked(true); };
  const unlock = async () => { await mockRuntime.device.unlock(); setLocked(false); };
  return <div className="app-shell"><aside className={`sidebar ${sidebarOpen ? 'open' : ''}`}><div className="brand"><div className="logo-mark">LH</div><div><strong>LinkerHand</strong><span>CONSOLE V2</span></div><button className="icon-button close-menu" onClick={() => setSidebarOpen(false)} aria-label="关闭菜单"><X size={18} /></button></div><div className="device-chip"><span className="status-dot" /><div><strong>{config.name}</strong><small>{config.model} · {config.address}</small></div></div><nav>{(['工作台', '互动', '管理'] as const).map(group => <div className="nav-group" key={group}><span className="nav-label">{group}</span>{nav.filter(item => item.group === group).map(item => { const Icon = item.icon; return <button className={`nav-item ${page === item.id ? 'active' : ''}`} key={item.id} onClick={() => go(item.id)}><Icon size={18} /><span>{item.label}</span>{item.id === 'diagnostics' && <i className="nav-alert" />}</button>; })}</div>)}</nav><div className="sidebar-footer"><button className="nav-item"><CircleHelp size={18} /><span>帮助与快捷键</span></button><div className="operator"><div className="avatar">OP</div><div><strong>操作员</strong><small>本地工作区</small></div><Menu size={16} /></div></div></aside><main className="main"><header className="topbar"><button className="icon-button menu-button" onClick={() => setSidebarOpen(true)} aria-label="打开菜单"><Menu size={20} /></button><div className="breadcrumbs"><span>工作台</span><span>/</span><strong>{nav.find(item => item.id === page)?.label}</strong></div><div className="top-actions"><button className="icon-button" onClick={toggle} aria-label="切换主题">{theme === 'light' ? <Moon size={18} /> : <Sun size={18} />}</button><span className="top-divider" /><button className={`stop-button ${locked ? 'locked' : ''}`} onClick={locked ? unlock : stopAll}>{locked ? <><Cable size={16} />恢复控制</> : <><Activity size={16} />停止全部动作</>} </button></div></header><div className="content">{locked && <div className="lock-banner"><span><Activity size={17} /><strong>控制已锁定</strong>停止全部动作已生效，设备不会继续执行新的动作。</span><button onClick={unlock}>恢复控制</button></div>}{renderPage()}</div></main></div>;
}
export function App() { return <ThemeProvider><Shell /></ThemeProvider>; }
