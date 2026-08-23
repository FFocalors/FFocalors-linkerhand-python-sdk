import { useCallback, useEffect, useMemo, useState } from 'react';
import type { ActionPort, ActionRecording, MotionPort } from '../../shared/contracts';
import { Badge, Card, EmptyState, Progress } from '../../shared/ui';

export type ActionControllerState = {
  state: 'idle' | 'recording' | 'recordingPaused' | 'playing' | 'paused' | 'completed' | 'cancelled' | 'error';
  actionId?: string;
  progress: number;
  detail?: string;
};

/** Feature-local seam for app-runtime. It mirrors action-engine without changing frozen DTOs. */
export interface ActionController {
  startRecording(name: string): Promise<void>;
  pauseRecording(): Promise<void>;
  resumeRecording(): Promise<void>;
  finishRecording(): Promise<void>;
  cancelRecording(): Promise<void>;
  play(actionId: string, options: { speed: number; loopCount: number | null }): Promise<void>;
  pausePlayback(): Promise<void>;
  resumePlayback(): Promise<void>;
  stop(): Promise<void>;
  getState(): Promise<ActionControllerState>;
  subscribe(listener: (state: ActionControllerState) => void): () => void;
}

type Tab = 'all' | 'builtin' | 'custom';
const idleState: ActionControllerState = { state: 'idle', progress: 0 };

export function ActionCenter({ actions, motion: _motion, locked, controller }: { actions: ActionPort; motion: MotionPort; locked: boolean; controller?: ActionController }) {
  const [items, setItems] = useState<ActionRecording[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>();
  const [tab, setTab] = useState<Tab>('all');
  const [draftName, setDraftName] = useState('');
  const [drafting, setDrafting] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [loops, setLoops] = useState('1');
  const [controllerState, setControllerState] = useState<ActionControllerState>(idleState);

  const refresh = useCallback(async () => {
    setLoading(true); setError(undefined);
    try { setItems(await actions.list()); } catch { setError('动作列表暂时不可用，请稍后重试。'); } finally { setLoading(false); }
  }, [actions]);
  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => {
    if (!controller) { setControllerState(idleState); return; }
    let mounted = true;
    void controller.getState().then(state => { if (mounted) setControllerState(state); }).catch(() => setError('动作控制器状态暂时不可用。'));
    return () => { mounted = false; };
  }, [controller]);
  useEffect(() => controller ? controller.subscribe(setControllerState) : undefined, [controller]);

  const controllerReady = Boolean(controller);
  const visibleItems = useMemo(() => items.filter(item => tab === 'all' || (tab === 'builtin' ? item.id.startsWith('builtin:') : !item.id.startsWith('builtin:'))), [items, tab]);
  const invoke = async (operation: () => Promise<void>, failure: string) => { try { await operation(); } catch { setError(failure); } };
  const startRecording = () => { if (!controller || !draftName.trim()) return; void invoke(() => controller.startRecording(draftName.trim()), '录制未启动，请确认运行时已连接。'); };
  const run = (item: ActionRecording) => { if (!controller || locked) return; void invoke(() => controller.play(item.id, { speed, loopCount: loops === '0' ? null : Number(loops) }), '动作未能启动，请确认设备已连接且控制未锁定。'); };
  const remove = async (id: string) => { try { await actions.delete(id); setItems(current => current.filter(item => item.id !== id)); } catch { setError('动作未删除，运行时可能尚未接入持久化。'); } };
  const recording = controllerState.state === 'recording' || controllerState.state === 'recordingPaused';
  const playing = controllerState.state === 'playing' || controllerState.state === 'paused';
  const active = controllerState.actionId ? items.find(item => item.id === controllerState.actionId) : undefined;

  return <div className="stack">
    <div className="page-heading"><div><h1>动作中心</h1><p className="muted">把经过验证的操作保存为可复用动作，所有执行状态来自 ActionController。</p></div><button className="button button-primary" disabled={locked || !controllerReady || recording || drafting} onClick={() => setDrafting(true)}>＋ 新建动作</button></div>
    {!controllerReady && <div className="permission-note" role="status">动作控制器尚未接线；录制、回放、暂停和停止已禁用。列表和删除仍可通过 ActionPort 使用。</div>}
    {(drafting || recording) && <Card><div className="card-header"><div><h2>录制自定义动作</h2><span className="muted">采样和帧数上限由 action-engine 控制。</span></div><Badge tone={recording ? 'red' : 'blue'}>{!recording ? '准备录制' : controllerState.state === 'recordingPaused' ? '已暂停' : '录制中'}</Badge></div><div className="settings-row"><label htmlFor="action-name">动作名称</label><input id="action-name" value={draftName} onChange={event => setDraftName(event.target.value)} placeholder="先填写名称，再开始录制" disabled={recording} /><div className="heading-actions">{!recording ? <><button className="button button-ghost" onClick={() => setDrafting(false)}>取消</button><button className="button button-primary" disabled={!draftName.trim()} onClick={startRecording}>开始录制</button></> : <><button className="button button-ghost" onClick={() => void invoke(() => controller!.cancelRecording().then(() => setDrafting(false)), '取消录制失败。')}>取消</button>{controllerState.state === 'recording' ? <button className="button button-ghost" onClick={() => void invoke(() => controller!.pauseRecording(), '暂停录制失败。')}>暂停</button> : <button className="button button-ghost" onClick={() => void invoke(() => controller!.resumeRecording(), '继续录制失败。')}>继续</button>}<button className="button button-primary" onClick={() => void invoke(() => controller!.finishRecording().then(async () => { setDrafting(false); await refresh(); }), '完成录制失败。')}>完成录制</button></>}</div></div></Card>}
    {playing && <Card><div className="card-header"><div><h2>正在回放：{active?.name ?? controllerState.actionId ?? '动作'}</h2><span className="muted">状态由 controller 推送 · {speed.toFixed(2)}× · {loops === '0' ? '无限循环（上限由引擎控制）' : `${loops} 次循环`}</span></div><div className="heading-actions"><Badge tone={controllerState.state === 'paused' ? 'amber' : 'blue'}>{controllerState.state === 'paused' ? '已暂停' : '运行中'}</Badge>{controllerState.state === 'paused' ? <button className="button button-ghost" onClick={() => void invoke(() => controller!.resumePlayback(), '继续回放失败。')}>继续</button> : <button className="button button-ghost" onClick={() => void invoke(() => controller!.pausePlayback(), '暂停回放失败。')}>暂停</button>}<button className="button button-ghost" onClick={() => void invoke(() => controller!.stop(), '停止回放失败。')}>停止</button></div></div><Progress value={controllerState.progress} /><span className="muted">{Math.round(controllerState.progress)}% · {controllerState.detail ?? '等待运行时状态'}</span></Card>}
    <Card><div className="card-header"><div><div className="heading-actions"><button className={`button ${tab === 'all' ? 'button-secondary' : 'button-ghost'}`} onClick={() => setTab('all')}>全部</button><button className={`button ${tab === 'builtin' ? 'button-secondary' : 'button-ghost'}`} onClick={() => setTab('builtin')}>内置预设</button><button className={`button ${tab === 'custom' ? 'button-secondary' : 'button-ghost'}`} onClick={() => setTab('custom')}>自定义</button></div><span className="muted">倍速和循环在启动时传给 controller。</span></div><div className="heading-actions"><label className="muted" htmlFor="speed">倍速</label><select id="speed" value={speed} onChange={event => setSpeed(Number(event.target.value))} disabled={!controllerReady}><option value="0.25">0.25×</option><option value="0.5">0.5×</option><option value="1">1×</option><option value="1.5">1.5×</option><option value="2">2×</option></select><label className="muted" htmlFor="loops">循环</label><select id="loops" value={loops} onChange={event => setLoops(event.target.value)} disabled={!controllerReady}><option value="1">1 次</option><option value="3">3 次</option><option value="10">10 次</option><option value="0">无限</option></select></div></div>
      {loading ? <div className="empty"><span>正在读取动作…</span></div> : error ? <div className="permission-note" role="alert">{error}</div> : visibleItems.length === 0 ? <EmptyState title="还没有可运行的动作" detail={tab === 'builtin' ? '运行时接入内置预设后会显示在这里。' : '控制器接线后可录制第一个自定义动作。'} /> : <><div className="table-head"><span>动作名称</span><span>来源</span><span>步骤</span><span>时长</span><span /></div>{visibleItems.map(item => <div className="table-row" key={item.id}><strong>{item.name}</strong><span><Badge tone={item.id.startsWith('builtin:') ? 'blue' : 'green'}>{item.id.startsWith('builtin:') ? '内置' : '自定义'}</Badge></span><span>{item.steps} 步</span><span>{(item.durationMs / 1000).toFixed(1)} 秒</span><div className="heading-actions"><button className="button button-ghost" disabled={locked || !controllerReady} onClick={() => run(item)}>运行 ↗</button><button className="button button-ghost" disabled={locked} onClick={() => void remove(item.id)}>删除</button></div></div>)}</>}
    </Card>
    <Card className="tip-card"><Badge>操作提示</Badge><span>停止按钮会调用 controller.stop，释放 Playback/Loop 来源；没有接线时不会伪造运行进度。</span></Card>
  </div>;
}
