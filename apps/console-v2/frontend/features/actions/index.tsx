import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { CheckSquare, Hand, Hash, ListOrdered } from 'lucide-react';
import type { ActionPort, ActionRecording, DeviceCapabilities, MotionPort, TelemetryPort } from '../../shared/contracts';
import { Badge, Card, EmptyState, Progress } from '../../shared/ui';
import { O6_BASIC_ACTIONS, O6_NUMBER_ACTIONS, JointSlider, O6_JOINT_NAMES, toVector, type DeviceControlQuickAction } from '../device-control';
import './actions.css';

export type ActionControllerState = {
  state: 'idle' | 'recording' | 'recordingPaused' | 'playing' | 'paused' | 'completed' | 'cancelled' | 'error';
  actionId?: string;
  progress: number;
  detail?: string;
};

export interface LoopSequence {
  id: string;
  name: string;
  actionIds: string[];
  loopCount: number | null;
  createdAt: string;
}

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
  playLoop(loop: LoopSequence, options: { speed: number }): Promise<void>;
  stopLoop(): Promise<void>;
  getState(): Promise<ActionControllerState>;
  subscribe(listener: (state: ActionControllerState) => void): () => void;
}

type Tab = 'all' | 'builtin' | 'custom';
const idleState: ActionControllerState = { state: 'idle', progress: 0 };

export function ActionCenter({
  actions,
  motion: _motion,
  locked,
  controller,
  customPresets,
  capabilities,
  telemetry,
  debugMode,
}: {
  actions: ActionPort;
  motion: MotionPort;
  locked: boolean;
  controller?: ActionController;
  customPresets?: DeviceControlQuickAction[];
  capabilities?: DeviceCapabilities;
  telemetry?: TelemetryPort;
  debugMode?: boolean;
}) {
  const [items, setItems] = useState<ActionRecording[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>();
  const [tab, setTab] = useState<Tab>('all');
  const [draftName, setDraftName] = useState('');
  const [drafting, setDrafting] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [loops, setLoops] = useState('1');
  const [controllerState, setControllerState] = useState<ActionControllerState>(idleState);

  const [loopMode, setLoopMode] = useState<'off' | 'selecting'>('off');
  const [selectedActionIds, setSelectedActionIds] = useState<string[]>([]);
  const [loopSequences, setLoopSequences] = useState<LoopSequence[]>([]);
  const [loopDialog, setLoopDialog] = useState<{ mode: 'create' | 'edit'; loop?: LoopSequence; name: string; order: string[]; loopCount: number | null } | null>(null);
  const [loopExecution, setLoopExecution] = useState<{ loop: LoopSequence; currentActionIndex: number } | null>(null);

  // Built-in preset local hide state
  const [hiddenBuiltinIds, setHiddenBuiltinIds] = useState<Set<string>>(() => new Set());

  // Joint slider read-only telemetry state
  const sliderJoints = capabilities ? Math.max(0, capabilities.jointCount) : 0;
  const [sliderValues, setSliderValues] = useState<number[]>([]);

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

  // Telemetry subscription for joint slider card
  useEffect(() => {
    if (!telemetry || !capabilities || capabilities.jointCount <= 0) return;
    const jointCount = capabilities.jointCount;
    const { min, max } = capabilities.position.range;
    const normalize = (raw: number) => Math.max(0, Math.min(1, (raw - min) / (max - min)));
    const update = (snapshot: { rawPosition: number[] }) => {
      const next = Array.from({ length: jointCount }, (_, i) => normalize(snapshot.rawPosition[i] ?? 0));
      setSliderValues(next);
    };
    let mounted = true;
    void telemetry.read().then(snapshot => { if (mounted) update(snapshot); }).catch(() => {});
    const unsubscribe = telemetry.subscribe(update);
    return () => { mounted = false; unsubscribe(); };
  }, [telemetry, capabilities]);

  const controllerReady = Boolean(controller);
  const visibleItems = useMemo(() => items.filter(item => tab === 'all' || (tab === 'builtin' ? item.id.startsWith('builtin:') : !item.id.startsWith('builtin:'))), [items, tab]);

  // Custom tab: merge homepage customPresets with local non-builtin recordings
  const customTabItems = useMemo(() => {
    const homepagePresets: (DeviceControlQuickAction & { _source: 'homepage' })[] = (customPresets ?? []).map(p => ({ ...p, _source: 'homepage' as const }));
    const localRecordings: (ActionRecording & { _source: 'local' })[] = items
      .filter(item => !item.id.startsWith('builtin:'))
      .map(item => ({ ...item, _source: 'local' as const }));
    return [...homepagePresets, ...localRecordings];
  }, [customPresets, items]);

  const isHomepagePreset = (item: typeof customTabItems[number]): item is DeviceControlQuickAction & { _source: 'homepage' } => item._source === 'homepage';

  const invoke = async (operation: () => Promise<void>, failure: string) => { try { await operation(); } catch { setError(failure); } };

  const toggleSelection = (id: string) => {
    setSelectedActionIds(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]);
  };

  const startRecording = () => { if (!controller || !draftName.trim()) return; void invoke(() => controller.startRecording(draftName.trim()), '录制未启动，请确认运行时已连接。'); };
  const run = (item: ActionRecording) => { if (!controller || locked) return; void invoke(() => controller.play(item.id, { speed, loopCount: loops === '0' ? null : Number(loops) }), '动作未能启动，请确认设备已连接且控制未锁定。'); };

  const runBuiltin = (action: DeviceControlQuickAction) => {
    if (!controller || locked) return;
    void invoke(
      () => controller.play(action.id, { speed: 1, loopCount: 1 }),
      `内置预设「${action.label}」未能启动，请确认设备已连接且控制未锁定。`
    );
  };

  const remove = async (id: string) => { try { await actions.delete(id); setItems(current => current.filter(item => item.id !== id)); } catch { setError('动作未删除，运行时可能尚未接入持久化。'); } };
  const hideBuiltin = (id: string) => { setHiddenBuiltinIds(prev => { const next = new Set(prev); next.add(id); return next; }); };

  const openCreateLoopDialog = () => {
    if (selectedActionIds.length < 2) return;
    setLoopDialog({ mode: 'create', name: '', order: [...selectedActionIds], loopCount: 1 });
  };

  const openEditLoopDialog = (loop: LoopSequence) => {
    setLoopDialog({ mode: 'edit', loop, name: loop.name, order: [...loop.actionIds], loopCount: loop.loopCount });
  };

  const saveLoop = () => {
    if (!loopDialog || !loopDialog.name.trim()) return;
    const loop: LoopSequence = {
      id: loopDialog.loop?.id ?? `loop-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
      name: loopDialog.name.trim(),
      actionIds: loopDialog.order,
      loopCount: loopDialog.loopCount,
      createdAt: loopDialog.loop?.createdAt ?? new Date().toISOString(),
    };
    setLoopSequences(prev => loopDialog.mode === 'edit' && loopDialog.loop ? prev.map(l => l.id === loopDialog.loop!.id ? loop : l) : [...prev, loop]);
    setLoopDialog(null);
    setLoopMode('off');
    setSelectedActionIds([]);
  };

  const deleteLoop = (id: string) => {
    setLoopSequences(prev => prev.filter(l => l.id !== id));
    setLoopExecution(prev => prev?.loop.id === id ? null : prev);
  };

  const moveLoopOrderItem = (index: number, direction: -1 | 1) => {
    if (!loopDialog) return;
    const target = index + direction;
    if (target < 0 || target >= loopDialog.order.length) return;
    const order = [...loopDialog.order];
    [order[index], order[target]] = [order[target], order[index]];
    setLoopDialog({ ...loopDialog, order });
  };

  const runLoop = (loop: LoopSequence) => {
    if (!controller || locked || loopExecution) return;
    setLoopExecution({ loop, currentActionIndex: 0 });
    void invoke(() => controller.playLoop(loop, { speed }), '循环未能启动，请确认设备已连接且控制未锁定。');
  };

  const stopLoopExecution = () => {
    if (!controller) return;
    void invoke(() => controller.stopLoop(), '停止循环失败。');
    setLoopExecution(null);
  };

  const recording = controllerState.state === 'recording' || controllerState.state === 'recordingPaused';
  const playing = controllerState.state === 'playing' || controllerState.state === 'paused';
  const active = controllerState.actionId ? items.find(item => item.id === controllerState.actionId) : undefined;

  useEffect(() => {
    if (!loopExecution) return;
    if (controllerState.state === 'idle' || controllerState.state === 'completed' || controllerState.state === 'cancelled' || controllerState.state === 'error') {
      setLoopExecution(null);
    }
  }, [controllerState.state, loopExecution]);

  const currentLoopActionIndex = useMemo(() => {
    if (!loopExecution || !controllerState.actionId) return -1;
    return loopExecution.loop.actionIds.indexOf(controllerState.actionId);
  }, [loopExecution, controllerState.actionId]);

  // ---- Built-in preset render helpers ----

  const allBuiltinPresets = useMemo(() => [...O6_BASIC_ACTIONS, ...O6_NUMBER_ACTIONS], []);
  const visibleBuiltinPresets = useMemo(
    () => allBuiltinPresets.filter(action => !hiddenBuiltinIds.has(action.id)),
    [allBuiltinPresets, hiddenBuiltinIds]
  );
  const basicBuiltins = useMemo(() => visibleBuiltinPresets.filter(a => a.category === 'basic'), [visibleBuiltinPresets]);
  const numberBuiltins = useMemo(() => visibleBuiltinPresets.filter(a => a.category === 'number'), [visibleBuiltinPresets]);

  const renderBuiltinPresetButton = (action: DeviceControlQuickAction) => (
    <button
      className="preset-button"
      key={action.id}
      disabled={!controller || locked}
      onClick={() => runBuiltin(action)}
    >
      {action.category === 'basic' ? <Hand size={16} /> : <Hash size={16} />}
      <span>{action.label}</span>
      <span
        role="button"
        tabIndex={0}
        className="preset-delete"
        aria-label={`隐藏 ${action.label}`}
        title="从此视图隐藏"
        aria-disabled={!controller || locked}
        onClick={(event) => { event.stopPropagation(); event.preventDefault(); hideBuiltin(action.id); }}
        onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); event.stopPropagation(); hideBuiltin(action.id); } }}
      >
        ×
      </span>
    </button>
  );

  // ---- Joint slider card ----
  const showJointSliderCard = Boolean(capabilities && capabilities.jointCount > 0);

  return (
    <div className="stack">
      <div className="page-heading">
        <div><h1>动作中心</h1><p className="muted">把经过验证的操作保存为可复用动作，所有执行状态来自 ActionController。</p></div>
        <div className="heading-actions">
          {loopMode === 'off' ? (
            <button className="button button-secondary" onClick={() => setLoopMode('selecting')}>
              <CheckSquare size={14} />选择动作创建循环
            </button>
          ) : (
            <>
              <button className="button button-ghost" onClick={() => { setLoopMode('off'); setSelectedActionIds([]); }}>取消选择</button>
              {selectedActionIds.length >= 2 && (
                <button className="button button-primary" onClick={openCreateLoopDialog}>
                  <ListOrdered size={14} />创建循环
                </button>
              )}
            </>
          )}
          <button className="button button-primary" disabled={locked || !controllerReady || recording || drafting} onClick={() => setDrafting(true)}>＋ 新建动作</button>
        </div>
      </div>

      {debugMode && <Badge tone="amber">调试模式</Badge>}

      {/* Joint slider card */}
      {showJointSliderCard && (
        <Card className="joint-slider-card">
          <div className="card-header">
            <div><h2>关节位置</h2><span className="muted">{capabilities!.jointCount} 关节 · 遥测实时更新</span></div>
            <Badge tone="blue">只读</Badge>
          </div>
          <div className="joint-slider-grid">
            {Array.from({ length: capabilities!.jointCount }, (_, index) => (
              <div className="joint-slider-item" key={index}>
                <label>{O6_JOINT_NAMES[index] ?? `J${index + 1}`}</label>
                <JointSlider
                  index={index}
                  label={O6_JOINT_NAMES[index]}
                  value={sliderValues[index] ?? 0}
                  disabled
                  onBegin={() => {}}
                  onInput={() => {}}
                  onFinish={() => {}}
                />
              </div>
            ))}
          </div>
        </Card>
      )}

      {!controllerReady && <div className="permission-note" role="status">动作控制器尚未接线；录制、回放、暂停和停止已禁用。列表和删除仍可通过 ActionPort 使用。</div>}
      {(drafting || recording) && <Card><div className="card-header"><div><h2>录制自定义动作</h2><span className="muted">采样和帧数上限由 action-engine 控制。</span></div><Badge tone={recording ? 'red' : 'blue'}>{!recording ? '准备录制' : controllerState.state === 'recordingPaused' ? '已暂停' : '录制中'}</Badge></div><div className="settings-row"><label htmlFor="action-name">动作名称</label><input id="action-name" value={draftName} onChange={event => setDraftName(event.target.value)} placeholder="先填写名称，再开始录制" disabled={recording} /><div className="heading-actions">{!recording ? <><button className="button button-ghost" onClick={() => setDrafting(false)}>取消</button><button className="button button-primary" disabled={!draftName.trim()} onClick={startRecording}>开始录制</button></> : <><button className="button button-ghost" onClick={() => void invoke(() => controller!.cancelRecording().then(() => setDrafting(false)), '取消录制失败。')}>取消</button>{controllerState.state === 'recording' ? <button className="button button-ghost" onClick={() => void invoke(() => controller!.pauseRecording(), '暂停录制失败。')}>暂停</button> : <button className="button button-ghost" onClick={() => void invoke(() => controller!.resumeRecording(), '继续录制失败。')}>继续</button>}<button className="button button-primary" onClick={() => void invoke(() => controller!.finishRecording().then(async () => { setDrafting(false); await refresh(); }), '完成录制失败。')}>完成录制</button></>}</div></div></Card>}
      {playing && <Card>
        <div className="card-header">
          <div>
            <h2>{loopExecution ? `正在播放循环：${loopExecution.loop.name}` : `正在回放：${active?.name ?? controllerState.actionId ?? '动作'}`}</h2>
            <span className="muted">
              {loopExecution
                ? `第 ${currentLoopActionIndex >= 0 ? currentLoopActionIndex + 1 : '?'}/${loopExecution.loop.actionIds.length} 个动作 · ${speed.toFixed(2)}× · ${loopExecution.loop.loopCount === null ? '无限循环' : `${loopExecution.loop.loopCount} 次循环`}`
                : `状态由 controller 推送 · ${speed.toFixed(2)}× · ${loops === '0' ? '无限循环（上限由引擎控制）' : `${loops} 次循环`}`}
            </span>
          </div>
          <div className="heading-actions">
            <Badge tone={controllerState.state === 'paused' ? 'amber' : 'blue'}>{controllerState.state === 'paused' ? '已暂停' : '运行中'}</Badge>
            {controllerState.state === 'paused' ? <button className="button button-ghost" onClick={() => void invoke(() => controller!.resumePlayback(), '继续回放失败。')}>继续</button> : <button className="button button-ghost" onClick={() => void invoke(() => controller!.pausePlayback(), '暂停回放失败。')}>暂停</button>}
            <button className="button button-ghost" onClick={() => void invoke(() => loopExecution ? controller!.stopLoop() : controller!.stop(), '停止失败。')}>停止</button>
          </div>
        </div>
        <Progress value={controllerState.progress} />
        <span className="muted">{Math.round(controllerState.progress)}% · {controllerState.detail ?? '等待运行时状态'}</span>
      </Card>}
      <Card>
        <div className="card-header">
          <div>
            <div className="heading-actions">
              <button className={`button ${tab === 'all' ? 'button-secondary' : 'button-ghost'}`} onClick={() => setTab('all')}>全部</button>
              <button className={`button ${tab === 'builtin' ? 'button-secondary' : 'button-ghost'}`} onClick={() => setTab('builtin')}>内置预设</button>
              <button className={`button ${tab === 'custom' ? 'button-secondary' : 'button-ghost'}`} onClick={() => setTab('custom')}>自定义</button>
            </div>
            <span className="muted">倍速和循环在启动时传给 controller。</span>
          </div>
          <div className="heading-actions">
            <label className="muted" htmlFor="speed">倍速</label>
            <select id="speed" value={speed} onChange={event => setSpeed(Number(event.target.value))} disabled={!controllerReady}>
              <option value="0.25">0.25×</option>
              <option value="0.5">0.5×</option>
              <option value="1">1×</option>
              <option value="1.5">1.5×</option>
              <option value="2">2×</option>
            </select>
            <label className="muted" htmlFor="loops">循环</label>
            <select id="loops" value={loops} onChange={event => setLoops(event.target.value)} disabled={!controllerReady}>
              <option value="1">1 次</option>
              <option value="3">3 次</option>
              <option value="10">10 次</option>
              <option value="0">无限</option>
            </select>
          </div>
        </div>

        {/* Built-in presets tab: O6 action grids */}
        {tab === 'builtin' && (
          visibleBuiltinPresets.length === 0 ? (
            <EmptyState title="没有可显示的内置预设" detail="所有内置预设已被隐藏。刷新页面可恢复显示。" />
          ) : (
            <div>
              {basicBuiltins.length > 0 && (
                <div style={{ marginBottom: 14 }}>
                  <strong style={{ display: 'block', marginBottom: 6, fontSize: 13, color: 'var(--muted, #6f7d91)' }}>基本预设</strong>
                  <div className="preset-grid preset-grid-basic">
                    {basicBuiltins.map(renderBuiltinPresetButton)}
                  </div>
                </div>
              )}
              {numberBuiltins.length > 0 && (
                <div>
                  <strong style={{ display: 'block', marginBottom: 6, fontSize: 13, color: 'var(--muted, #6f7d91)' }}>数字预设</strong>
                  <div className="preset-grid preset-grid-number">
                    {numberBuiltins.map(renderBuiltinPresetButton)}
                  </div>
                </div>
              )}
            </div>
          )
        )}

        {/* All / Custom tabs: table-based rendering */}
        {(tab === 'all' || tab === 'custom') && (
          loading ? <div className="empty"><span>正在读取动作…</span></div> : error ? <div className="permission-note" role="alert">{error}</div> : visibleItems.length === 0 ? (
            <EmptyState title="还没有可运行的动作" detail={tab === 'custom' ? '控制器接线后可录制第一个自定义动作，或从首页同步预设。' : '运行时接入内置预设后会显示在这里。'} />
          ) : (
            <>
              <div className={`table-head actions-table-head ${loopMode === 'selecting' ? 'loop-mode' : ''}`}>
                {loopMode === 'selecting' && <span>选择</span>}
                <span>名称</span>
                <span>来源</span>
                <span>步骤</span>
                <span>时长</span>
                <span />
              </div>
              {visibleItems.map(item => (
                <div key={item.id} className={`table-row actions-table-row ${loopMode === 'selecting' ? 'loop-mode' : ''}`}>
                  {loopMode === 'selecting' && (
                    <input type="checkbox" checked={selectedActionIds.includes(item.id)} onChange={() => toggleSelection(item.id)} aria-label={`选择 ${item.name}`} />
                  )}
                  <strong>{item.name}</strong>
                  <span><Badge tone={item.id.startsWith('builtin:') ? 'blue' : 'green'}>{item.id.startsWith('builtin:') ? '内置' : '自定义'}</Badge></span>
                  <span>{item.steps} 步</span>
                  <span>{(item.durationMs / 1000).toFixed(1)} 秒</span>
                  <div className="heading-actions">
                    <button className="button button-ghost" disabled={locked || !controllerReady || loopMode === 'selecting'} onClick={() => run(item)}>运行 ↗</button>
                    <button className="button button-ghost" disabled={locked} onClick={() => void remove(item.id)}>删除</button>
                  </div>
                </div>
              ))}
            </>
          )
        )}

        {/* Custom tab: homepage presets + local recordings */}
        {tab === 'custom' && (
          customTabItems.length === 0 ? (
            <EmptyState title="还没有自定义预设" detail="控制器接线后可录制自定义动作，首页也可同步预设。" />
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 10 }}>
              {customTabItems.map((item) => {
                const isHomepage = isHomepagePreset(item);
                const preset = item as DeviceControlQuickAction;
                const recording = item as ActionRecording;
                return (
                  <div
                    key={(isHomepage ? preset.id : recording.id) + (isHomepage ? '-hp' : '')}
                    className="preset-button"
                    style={{ justifyContent: 'space-between', cursor: 'default' }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <strong>{isHomepage ? preset.label : recording.name}</strong>
                      <span className="preset-badge">{isHomepage ? '首页' : '自定义'}</span>
                    </div>
                    <div className="heading-actions">
                      {!isHomepage && (
                        <button className="button button-ghost" disabled={locked || !controllerReady} onClick={() => run(recording)}>运行 ↗</button>
                      )}
                      {isHomepage && controller && !locked && (
                        <button className="button button-ghost" disabled={locked || !controllerReady} onClick={() => runBuiltin(preset)}>运行 ↗</button>
                      )}
                      {!isHomepage && (
                        <button className="button button-ghost" disabled={locked} onClick={() => void remove(recording.id)}>删除</button>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )
        )}
      </Card>

      {loopDialog && <Card>
        <div className="card-header">
          <div><h2>{loopDialog.mode === 'create' ? '创建循环' : '编辑循环'}</h2><span className="muted">调整动作顺序和循环次数</span></div>
          <button className="button button-ghost" onClick={() => setLoopDialog(null)}>关闭</button>
        </div>
        <div className="settings-row">
          <label htmlFor="loop-name">循环名称</label>
          <input id="loop-name" value={loopDialog.name} onChange={event => setLoopDialog(prev => prev ? { ...prev, name: event.target.value } : null)} placeholder="给循环起个名字" />
        </div>
        <div className="loop-order-section">
          <span className="muted">动作顺序（可调整）</span>
          {loopDialog.order.map((actionId, index) => {
            const action = items.find(item => item.id === actionId);
            return (
              <div key={actionId} className="loop-order-item">
                <span>{index + 1}. {action?.name ?? actionId}</span>
                <div className="heading-actions">
                  <button className="button button-ghost" disabled={index === 0} onClick={() => moveLoopOrderItem(index, -1)}>↑</button>
                  <button className="button button-ghost" disabled={index === loopDialog.order.length - 1} onClick={() => moveLoopOrderItem(index, 1)}>↓</button>
                </div>
              </div>
            );
          })}
        </div>
        <div className="settings-row">
          <label htmlFor="loop-count">循环次数</label>
          <select id="loop-count" value={loopDialog.loopCount === null ? '0' : String(loopDialog.loopCount)} onChange={event => setLoopDialog(prev => prev ? { ...prev, loopCount: event.target.value === '0' ? null : Number(event.target.value) } : null)}>
            <option value="1">1 次</option>
            <option value="3">3 次</option>
            <option value="5">5 次</option>
            <option value="10">10 次</option>
            <option value="0">无限</option>
          </select>
        </div>
        <div className="heading-actions" style={{ justifyContent: 'flex-end' }}>
          <button className="button button-ghost" onClick={() => setLoopDialog(null)}>取消</button>
          <button className="button button-primary" disabled={!loopDialog.name.trim()} onClick={saveLoop}>确认</button>
        </div>
      </Card>}
      {loopSequences.length > 0 && <Card>
        <div className="card-header">
          <div><h2>循环列表</h2><span className="muted">已保存的循环序列</span></div>
        </div>
        <div className="table-head">
          <span>名称</span>
          <span>动作数</span>
          <span>循环次数</span>
          <span>创建时间</span>
          <span />
        </div>
        {loopSequences.map(loop => (
          <div className="table-row" key={loop.id}>
            <strong>{loop.name}</strong>
            <span>{loop.actionIds.length} 个动作</span>
            <span>{loop.loopCount === null ? '无限' : `${loop.loopCount} 次`}</span>
            <span>{loop.createdAt}</span>
            <div className="heading-actions">
              <button className="button button-ghost" disabled={locked || !controllerReady || loopExecution?.loop.id === loop.id} onClick={() => runLoop(loop)}>▶ 运行</button>
              <button className="button button-ghost" onClick={() => openEditLoopDialog(loop)}>✏ 编辑</button>
              <button className="button button-ghost" onClick={() => deleteLoop(loop.id)}>🗑 删除</button>
            </div>
          </div>
        ))}
      </Card>}
      <Card className="tip-card"><Badge>操作提示</Badge><span>停止按钮会调用 controller.stop 或 stopLoop，释放 Playback/Loop 来源；没有接线时不会伪造运行进度。</span></Card>
    </div>
  );
}
