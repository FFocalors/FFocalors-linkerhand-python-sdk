import { useEffect, useMemo, useState } from 'react';
import type { GraspPort } from '../../shared/contracts';
import { Badge, Card, EmptyState, Progress } from '../../shared/ui';

export type GraspPhase = 'idle' | 'calibrating' | 'ready' | 'approach' | 'grasping' | 'holding' | 'releasing' | 'aborted' | 'failed';
export type GraspControllerState = { phase: GraspPhase; failure?: { code: string; message: string }; tactileAvailable: boolean; rawTouch?: number[] | null; degraded: boolean };

/** Feature-local seam for app-runtime. Phase changes and touch data are controller-owned. */
export interface GraspController {
  calibrate(): Promise<void>;
  completeCalibration(): Promise<void>;
  approach(): Promise<void>;
  startGrasp(presetId: string, degraded: boolean): Promise<void>;
  release(): Promise<void>;
  abort(): Promise<void>;
  getState(): Promise<GraspControllerState>;
  subscribe(listener: (state: GraspControllerState) => void): () => void;
}

type Model = 'O6' | 'L6' | 'L7' | 'L10' | 'L20' | 'G20' | 'L21' | 'L25';
const supportedModels: Model[] = ['O6', 'L6', 'L7', 'L10', 'L20'];
const idleState: GraspControllerState = { phase: 'idle', tactileAvailable: false, rawTouch: null, degraded: false };

export function SmartGrasp({ grasp, locked, tactileAvailable: _tactileAvailable, model = 'O6', controller }: { grasp: GraspPort; locked: boolean; tactileAvailable: boolean; model?: Model; controller?: GraspController }) {
  const [presets, setPresets] = useState<{ id: string; name: string; description: string }[]>([]);
  const [selected, setSelected] = useState<string>();
  const [degraded, setDegraded] = useState(false);
  const [advanced, setAdvanced] = useState(false);
  const [state, setState] = useState<GraspControllerState>(idleState);
  const [error, setError] = useState<string>();
  const available = supportedModels.includes(model);
  useEffect(() => { void grasp.listPresets().then(setPresets).catch(() => setError('抓取预设暂时不可用，请检查运行时接线。')); }, [grasp]);
  useEffect(() => {
    if (!controller) { setState(idleState); return; }
    let mounted = true;
    void controller.getState().then(next => { if (mounted) setState(next); }).catch(() => setError('抓取控制器状态暂时不可用。'));
    return () => { mounted = false; };
  }, [controller]);
  useEffect(() => controller ? controller.subscribe(setState) : undefined, [controller]);
  const phaseLabel = useMemo(() => ({ idle: '等待开始', calibrating: '正在标定', ready: '已就绪', approach: '接近目标', grasping: '自适应抓取', holding: '保持中', releasing: '释放中', aborted: '已中止', failed: '失败' } satisfies Record<GraspPhase, string>)[state.phase], [state.phase]);
  const controllerReady = Boolean(controller);
  const canRun = controllerReady && available && Boolean(selected) && !locked && (state.tactileAvailable || degraded);
  const invoke = async (operation: () => Promise<void>, failure: string) => { try { await operation(); } catch { setError(failure); } };
  const run = () => { if (!controller || !selected || !canRun) return; void invoke(() => controller.startGrasp(selected, degraded), '抓取未启动，请查看控制器失败原因。'); };
  const failureMessage = state.failure?.message ?? error;
  const touch = state.rawTouch && state.rawTouch.length > 0 ? state.rawTouch : null;
  return <div className="stack">
    <div className="page-heading"><div><p className="eyebrow">动作编排 / 智能抓取</p><h1>智能抓取</h1><p>阶段和反馈均来自 GraspController；未接线时不会模拟动作。</p></div><Badge tone={!available ? 'red' : state.tactileAvailable ? 'green' : 'amber'}>{!available ? `${model} 暂不可用` : state.tactileAvailable ? '触觉反馈可用' : '暂无触觉数据'}</Badge></div>
    {!controllerReady && <div className="permission-note" role="status">抓取控制器尚未接线；标定、接近、释放和中止已禁用。当前只展示运行时提供的预设。</div>}
    {!available && <div className="permission-note" role="alert"><strong>{model} 不支持智能自适应抓取。</strong> 当前支持 O6、L6、L7、L10、L20；G20、L21、L25 仅可使用普通动作预设。</div>}
    {controllerReady && !state.tactileAvailable && <Card><div className="card-header"><div><h2>触觉反馈不可用</h2><span className="muted">系统不会静默假装自适应成功。启用后将把降级选择传给 controller。</span></div><Badge tone="amber">降级模式</Badge></div><label><input type="checkbox" checked={degraded} onChange={event => setDegraded(event.target.checked)} /> 我确认以无触觉降级模式执行</label></Card>}
    <Card><div className="card-header"><div><h2>操作流程</h2><span className="muted">当前阶段：{phaseLabel}</span></div><div className="heading-actions"><Badge tone={state.phase === 'failed' || state.phase === 'aborted' ? 'red' : state.phase === 'holding' ? 'green' : 'blue'}>{phaseLabel}</Badge>{controllerReady && state.phase !== 'idle' && state.phase !== 'ready' && state.phase !== 'aborted' && state.phase !== 'failed' && <button className="button button-ghost" onClick={() => void invoke(() => controller!.abort(), '中止请求失败，请立即使用顶部停止全部动作。')}>中止</button>}</div></div><Progress value={state.phase === 'idle' ? 0 : state.phase === 'calibrating' ? 18 : state.phase === 'ready' ? 35 : state.phase === 'approach' ? 55 : state.phase === 'grasping' ? 72 : state.phase === 'holding' ? 88 : state.phase === 'releasing' ? 65 : 0} /><div className="grid grid-5" style={{ marginTop: 10 }}><button className="button button-secondary" disabled={locked || !controllerReady || !available || state.phase !== 'idle'} onClick={() => void invoke(() => controller!.calibrate(), '标定启动失败。')}>1. 标定</button><button className="button button-secondary" disabled={locked || !controllerReady || state.phase !== 'calibrating'} onClick={() => void invoke(() => controller!.completeCalibration(), '标定完成失败。')}>2. 完成</button><button className="button button-secondary" disabled={locked || !controllerReady || state.phase !== 'ready'} onClick={() => void invoke(() => controller!.approach(), '接近阶段启动失败。')}>3. 接近</button><button className="button button-secondary" disabled={!canRun || state.phase !== 'approach'} onClick={run}>4. 抓取</button><button className="button button-ghost" disabled={!controllerReady || state.phase !== 'holding'} onClick={() => void invoke(() => controller!.release(), '释放请求失败。')}>释放</button></div></Card>
    <div className="grid grid-3">{presets.length === 0 ? <Card><EmptyState title="没有可用抓取预设" detail="运行时通过 GraspPort 提供预设后会显示在这里。" /></Card> : presets.map(p => <Card className="preset" key={p.id}><div className="preset-icon">{p.id === 'soft' ? '◌' : p.id === 'cube' ? '◇' : '⌁'}</div><h2>{p.name}</h2><p className="muted">{p.description}</p><button className={`button ${selected === p.id ? 'button-primary' : 'button-secondary'}`} disabled={locked || !available || !controllerReady} onClick={() => setSelected(p.id)} aria-pressed={selected === p.id}>{selected === p.id ? '已选择' : '选择预设'} <span>→</span></button></Card>)}<Card className="tactile-card"><div className="card-header"><div><h2>触觉矩阵</h2><span className="muted">数据完全来自 controller.rawTouch</span></div><Badge tone={touch ? 'green' : 'amber'}>{touch ? '在线' : '暂无数据'}</Badge></div>{touch ? <div className="tactile-grid">{touch.map((value, index) => <i key={index} title={`触觉 ${index + 1}: ${value}`} style={{ opacity: Math.max(.15, Math.min(1, value / 255)) }} />)}</div> : <EmptyState title="暂无触觉数据" detail="等待运行时 telemetry 提供 rawTouch；不会使用伪造强度。" />}</Card></div>
    {failureMessage && <div className="permission-note" role="alert">{failureMessage}</div>}
    <Card><div className="card-header"><div><h2>高级参数</h2><span className="muted">EMA、死区、发送周期与 raw 阈值仅供诊断，不进入默认操作路径。</span></div><button className="button button-ghost" onClick={() => setAdvanced(value => !value)} aria-expanded={advanced}>{advanced ? '收起' : '展开'}</button></div>{advanced && <div className="grid grid-3"><label className="muted">发送周期<input value="由 controller 提供" readOnly /></label><label className="muted">步长限制<input value="由 profile 提供" readOnly /></label><label className="muted">接触阈值<input value="由 profile 提供" readOnly /></label></div>}</Card>
  </div>;
}
