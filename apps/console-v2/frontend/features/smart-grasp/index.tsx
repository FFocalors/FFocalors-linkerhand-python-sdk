import { useEffect, useMemo, useState } from 'react';
import type { GraspPort } from '../../shared/contracts';
import { Badge, Card, EmptyState, Progress } from '../../shared/ui';

type Model = 'O6' | 'L6' | 'L7' | 'L10' | 'L20' | 'G20' | 'L21' | 'L25';
type Phase = 'idle' | 'calibrating' | 'ready' | 'approach' | 'grasping' | 'holding' | 'releasing' | 'aborted' | 'failed';
const supportedModels: Model[] = ['O6', 'L6', 'L7', 'L10', 'L20'];

export function SmartGrasp({ grasp, locked, tactileAvailable, model = 'O6' }: { grasp: GraspPort; locked: boolean; tactileAvailable: boolean; model?: Model }) {
  const [presets, setPresets] = useState<{ id: string; name: string; description: string }[]>([]);
  const [selected, setSelected] = useState<string>();
  const [phase, setPhase] = useState<Phase>('idle');
  const [degraded, setDegraded] = useState(false);
  const [advanced, setAdvanced] = useState(false);
  const [error, setError] = useState<string>();
  useEffect(() => { void grasp.listPresets().then(setPresets).catch(() => setError('抓取预设暂时不可用，请检查运行时接线。')); }, [grasp]);
  const available = supportedModels.includes(model);
  const phaseLabel = useMemo(() => ({ idle: '等待开始', calibrating: '正在标定', ready: '已就绪', approach: '接近目标', grasping: '自适应抓取', holding: '保持中', releasing: '释放中', aborted: '已中止', failed: '失败' } satisfies Record<Phase, string>)[phase], [phase]);
  const run = async () => { if (!selected || locked || !available || (!tactileAvailable && !degraded)) return; setError(undefined); setPhase('grasping'); try { await grasp.runPreset(selected); setPhase('holding'); } catch { setPhase('failed'); setError('抓取未启动。请确认设备已连接、控制未锁定且触觉模式可用。'); } };
  const abort = () => { setPhase('aborted'); setError('操作员已中止；请确认手部姿态后重新标定。'); };
  return <div className="stack">
    <div className="page-heading"><div><p className="eyebrow">动作编排 / 智能抓取</p><h1>智能抓取</h1><p>按标定、接近、抓取、保持、释放的阶段执行；每一步都可中止。</p></div><Badge tone={!available ? 'red' : tactileAvailable ? 'green' : 'amber'}>{!available ? `${model} 暂不可用` : tactileAvailable ? '触觉反馈可用' : '需要显式降级'}</Badge></div>
    {!available && <div className="permission-note" role="alert"><strong>{model} 不支持智能自适应抓取。</strong> 当前支持 O6、L6、L7、L10、L20；G20、L21、L25 仅可使用普通动作预设。</div>}
    {!tactileAvailable && available && <Card><div className="card-header"><div><h2>触觉反馈不可用</h2><span className="muted">系统不会静默假装自适应成功。启用后将以固定步长执行显式的无触觉降级模式。</span></div><Badge tone="amber">降级模式</Badge></div><label><input type="checkbox" checked={degraded} onChange={event => setDegraded(event.target.checked)} /> 我确认以无触觉降级模式执行</label></Card>}
    <Card><div className="card-header"><div><h2>操作流程</h2><span className="muted">当前阶段：{phaseLabel}</span></div><div className="heading-actions"><Badge tone={phase === 'failed' || phase === 'aborted' ? 'red' : phase === 'holding' ? 'green' : 'blue'}>{phaseLabel}</Badge>{!['idle', 'ready', 'aborted', 'failed'].includes(phase) && <button className="button button-ghost" onClick={abort}>中止</button>}</div></div><Progress value={phase === 'idle' ? 0 : phase === 'calibrating' ? 18 : phase === 'ready' ? 35 : phase === 'approach' ? 55 : phase === 'grasping' ? 72 : phase === 'holding' ? 88 : phase === 'releasing' ? 65 : 0} /><div className="heading-actions"><button className="button button-secondary" disabled={locked || !available || phase !== 'idle'} onClick={() => setPhase('calibrating')}>1. 开始标定</button><button className="button button-secondary" disabled={locked || phase !== 'calibrating'} onClick={() => setPhase('ready')}>2. 标定完成</button><button className="button button-secondary" disabled={locked || phase !== 'ready'} onClick={() => setPhase('approach')}>3. 接近目标</button><button className="button button-secondary" disabled={locked || phase !== 'approach'} onClick={() => void run()}>4. 抓取</button><button className="button button-ghost" disabled={phase !== 'holding'} onClick={() => setPhase('releasing')}>释放</button><button className="button button-ghost" disabled={phase !== 'releasing'} onClick={() => setPhase('ready')}>完成释放</button></div></Card>
    <div className="grid grid-3">{presets.length === 0 ? <Card><EmptyState title="没有可用抓取预设" detail="运行时通过 GraspPort 提供预设后会显示在这里。" /></Card> : presets.map(p => <Card className="preset" key={p.id}><div className="preset-icon">{p.id === 'soft' ? '◌' : p.id === 'cube' ? '◇' : '⌁'}</div><h2>{p.name}</h2><p className="muted">{p.description}</p><button className={`button ${selected === p.id ? 'button-primary' : 'button-secondary'}`} disabled={locked || !available} onClick={() => setSelected(p.id)} aria-pressed={selected === p.id}>{selected === p.id ? '已选择' : '选择预设'} <span>→</span></button></Card>)}<Card className="tactile-card"><div className="card-header"><div><h2>触觉矩阵</h2><span className="muted">接触后单指停止并保持当前位置</span></div><Badge tone={tactileAvailable ? 'green' : 'amber'}>{tactileAvailable ? '在线' : '不可用'}</Badge></div><div className="tactile-grid">{Array.from({ length: 24 }, (_, i) => <i key={i} style={{ opacity: tactileAvailable ? .35 + ((i * 7) % 60) / 100 : .12 }} />)}</div><span className="muted">{tactileAvailable ? '固定周期采样 · 归一化完整向量' : degraded ? '已显式选择无触觉降级' : '请先选择降级模式'}</span></Card></div>
    {error && <div className="permission-note" role="alert">{error}</div>}
    <Card><div className="card-header"><div><h2>高级参数</h2><span className="muted">EMA、死区、发送周期与 raw 阈值仅供诊断，不进入默认操作路径。</span></div><button className="button button-ghost" onClick={() => setAdvanced(value => !value)} aria-expanded={advanced}>{advanced ? '收起' : '展开'}</button></div>{advanced && <div className="grid grid-3"><label className="muted">发送周期<input value="50 ms" readOnly /></label><label className="muted">步长限制<input value="0.05 normalized" readOnly /></label><label className="muted">接触阈值<input value="由 profile 提供" readOnly /></label></div>}</Card>
  </div>;
}
