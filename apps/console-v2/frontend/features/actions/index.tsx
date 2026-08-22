import { useCallback, useEffect, useMemo, useState } from 'react';
import type { ActionPort, ActionRecording, MotionPort } from '../../shared/contracts';
import { Badge, Card, EmptyState, Progress } from '../../shared/ui';

type Tab = 'all' | 'builtin' | 'custom';

export function ActionCenter({ actions, motion, locked }: { actions: ActionPort; motion: MotionPort; locked: boolean }) {
  const [items, setItems] = useState<ActionRecording[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>();
  const [tab, setTab] = useState<Tab>('all');
  const [recording, setRecording] = useState(false);
  const [draftName, setDraftName] = useState('');
  const [speed, setSpeed] = useState(1);
  const [loops, setLoops] = useState('1');
  const [activeId, setActiveId] = useState<string>();
  const [progress, setProgress] = useState(0);

  const refresh = useCallback(async () => {
    setLoading(true); setError(undefined);
    try { setItems(await actions.list()); } catch { setError('动作列表暂时不可用，请稍后重试。'); } finally { setLoading(false); }
  }, [actions]);
  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => {
    if (!activeId) return;
    const timer = window.setInterval(() => setProgress(value => value >= 100 ? 100 : value + 5), 180);
    return () => window.clearInterval(timer);
  }, [activeId]);
  const visibleItems = useMemo(() => items.filter(item => tab === 'all' || (tab === 'builtin' ? item.id.startsWith('builtin:') : !item.id.startsWith('builtin:'))), [items, tab]);
  const run = async (item: ActionRecording) => { if (locked) return; setActiveId(item.id); setProgress(0); try { await motion.runAction(item.id); } catch { setError('动作未能启动，请确认设备已连接且控制未锁定。'); setActiveId(undefined); } };
  const pause = async () => { try { await motion.pause(); } catch { setError('当前运行时不支持暂停该动作。'); } };
  const remove = async (id: string) => { try { await actions.delete(id); setItems(current => current.filter(item => item.id !== id)); } catch { setError('动作未删除，运行时可能尚未接入持久化。'); } };

  return <div className="stack">
    <div className="page-heading"><div><p className="eyebrow">编排 / 动作中心</p><h1>动作中心</h1><p>把经过验证的操作保存为可复用动作，运行时仍由 ActionPort 执行。</p></div><button className="button button-primary" disabled={locked || recording} onClick={() => { setRecording(true); setDraftName(''); }}>＋ 新建动作</button></div>
    {recording && <Card><div className="card-header"><div><h2>录制自定义动作</h2><span className="muted">采样由运行时限制帧数并合并高频样本，不会无限占用内存。</span></div><Badge tone="red">录制中</Badge></div><div className="settings-row"><label htmlFor="action-name">动作名称</label><input id="action-name" value={draftName} onChange={event => setDraftName(event.target.value)} placeholder="例如：轻放到托盘" /><div className="heading-actions"><button className="button button-ghost" onClick={() => setRecording(false)}>取消</button><button className="button button-primary" disabled={!draftName.trim()} onClick={() => setRecording(false)}>完成录制</button></div></div></Card>}
    {activeId && <Card><div className="card-header"><div><h2>正在回放：{items.find(item => item.id === activeId)?.name ?? activeId}</h2><span className="muted">{speed.toFixed(2)}× · {loops === '0' ? '无限循环（软件上限 1000 次）' : `${loops} 次循环`}</span></div><div className="heading-actions"><Badge tone={progress >= 100 ? 'green' : 'blue'}>{progress >= 100 ? '已完成' : '运行中'}</Badge><button className="button button-ghost" onClick={() => void pause()}>暂停</button><button className="button button-ghost" onClick={() => setActiveId(undefined)}>停止</button></div></div><Progress value={progress} /><span className="muted">{progress}% · 停止或全部停止会释放 Playback/Loop 来源</span></Card>}
    <Card><div className="card-header"><div><div className="heading-actions"><button className={`button ${tab === 'all' ? 'button-secondary' : 'button-ghost'}`} onClick={() => setTab('all')}>全部</button><button className={`button ${tab === 'builtin' ? 'button-secondary' : 'button-ghost'}`} onClick={() => setTab('builtin')}>内置预设</button><button className={`button ${tab === 'custom' ? 'button-secondary' : 'button-ghost'}`} onClick={() => setTab('custom')}>自定义</button></div><span className="muted">回放速度与循环只影响当前运行，不会修改动作内容。</span></div><div className="heading-actions"><label className="muted" htmlFor="speed">倍速</label><select id="speed" value={speed} onChange={event => setSpeed(Number(event.target.value))}><option value="0.25">0.25×</option><option value="0.5">0.5×</option><option value="1">1×</option><option value="1.5">1.5×</option><option value="2">2×</option></select><label className="muted" htmlFor="loops">循环</label><select id="loops" value={loops} onChange={event => setLoops(event.target.value)}><option value="1">1 次</option><option value="3">3 次</option><option value="10">10 次</option><option value="0">无限</option></select></div></div>
      {loading ? <div className="empty"><span>正在读取动作…</span></div> : error ? <div className="permission-note" role="alert">{error}</div> : visibleItems.length === 0 ? <EmptyState title="还没有可运行的动作" detail={tab === 'builtin' ? '运行时接入内置预设后会显示在这里。' : '点击“新建动作”录制第一个自定义动作。'} /> : <><div className="table-head"><span>动作名称</span><span>来源</span><span>步骤</span><span>时长</span><span /></div>{visibleItems.map(item => <div className="table-row" key={item.id}><strong>{item.name}</strong><span><Badge tone={item.id.startsWith('builtin:') ? 'blue' : 'green'}>{item.id.startsWith('builtin:') ? '内置' : '自定义'}</Badge></span><span>{item.steps} 步</span><span>{(item.durationMs / 1000).toFixed(1)} 秒</span><div className="heading-actions"><button className="button button-ghost" disabled={locked} onClick={() => void run(item)}>运行 ↗</button><button className="button button-ghost" disabled={locked} onClick={() => void remove(item.id)}>删除</button></div></div>)}</>}
    </Card>
    <Card className="tip-card"><Badge>操作提示</Badge><span>运行前确认设备周围无遮挡；键盘焦点在运行按钮时按 Enter 可启动，Esc 可停止当前回放。</span></Card>
  </div>;
}
