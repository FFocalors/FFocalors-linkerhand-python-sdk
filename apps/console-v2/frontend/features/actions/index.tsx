import { useCallback, useEffect, useMemo, useState } from 'react';
import { CheckSquare, Hand, Hash, ListOrdered, Save } from 'lucide-react';
import type { ActionPort, ActionRecording, DeviceCapabilities, MotionPort, TelemetryPort } from '../../shared/contracts';
import { Badge, Button, Card, Checkbox, EmptyState, Progress, Select, TextField } from '../../shared/ui';
import { useI18n } from '../../shared/i18n';
import { O6_BASIC_ACTIONS, O6_NUMBER_ACTIONS, JointSlider, O6_JOINT_NAMES, type DeviceControlQuickAction } from '../device-control';
import './actions.css';

export type PlaybackMode = 'single' | 'loop';
export type PlaybackDirection = 'forward' | 'reverse';
export type PlaybackSpeed = 0.25 | 0.5 | 0.75 | 1;

export interface PlaybackOptions {
  mode: PlaybackMode;
  speed: number;
  direction: PlaybackDirection;
  loopCount: number | null;
}

/** A pose is exactly one static keyframe and is the only selectable composer candidate. */
export interface PosePreset {
  kind: 'pose';
  id: string;
  name: string;
  source: 'builtin' | 'homepage' | 'local';
  positions?: number[];
  category?: DeviceControlQuickAction['category'];
  detail?: string;
}

/** A programmed action contains an ordered snapshot of poses plus its playback configuration. */
export interface ProgrammedAction {
  kind: 'sequence';
  id: string;
  name: string;
  source: 'local';
  poseIds: string[];
  poses: PosePreset[];
  playback: PlaybackOptions;
  createdAt: string;
  /** Optional legacy recording fields retained for migration displays. */
  frames?: ActionRecording['frames'];
  durationMs?: number;
  steps?: number;
  updatedAt?: string;
}

export type ActionCenterItem = PosePreset | ProgrammedAction;

export interface ActionControllerState {
  state: 'idle' | 'recording' | 'recordingPaused' | 'playing' | 'paused' | 'completed' | 'cancelled' | 'error';
  actionId?: string;
  progress: number;
  detail?: string;
}

/** Legacy loop DTO kept only for old adapters; new saves use ProgrammedAction. */
export interface LoopSequence {
  id: string;
  name: string;
  actionIds: string[];
  loopCount: number | null;
  createdAt: string;
  direction?: PlaybackDirection;
}

/** Feature-local runtime seam. New methods receive complete pose/keyframe data. */
export interface ActionController {
  playPose?: (pose: PosePreset, options: PlaybackOptions) => Promise<void>;
  playProgrammedAction?: (action: ProgrammedAction, options: PlaybackOptions) => Promise<void>;
  /** Optional explicit physical-device safety boundary for draft poses. */
  previewPose?: (pose: PosePreset) => Promise<void>;
  applyPose?: (pose: PosePreset, options: PlaybackOptions) => Promise<void>;
  /** Compatibility fallback only; adapters should implement the two complete-data methods above. */
  play: (actionId: string, options: { speed: number; loopCount: number | null; direction?: PlaybackDirection }) => Promise<void>;
  startRecording?: (name: string) => Promise<void>;
  pauseRecording?: () => Promise<void>;
  resumeRecording?: () => Promise<void>;
  finishRecording?: () => Promise<void>;
  cancelRecording?: () => Promise<void>;
  pausePlayback?: () => Promise<void>;
  resumePlayback?: () => Promise<void>;
  stop: () => Promise<void>;
  playLoop: (loop: LoopSequence, options: { speed: number; direction?: PlaybackDirection }) => Promise<void>;
  stopLoop: () => Promise<void>;
  getState: () => Promise<ActionControllerState>;
  subscribe: (listener: (state: ActionControllerState) => void) => () => void;
}

type Tab = 'all' | 'builtin' | 'custom';
type ComposerDraft = { name: string; order: string[]; playback: PlaybackOptions };
const idleState: ActionControllerState = { state: 'idle', progress: 0 };
const defaultPlayback = (): PlaybackOptions => ({ mode: 'loop', speed: 1, direction: 'forward', loopCount: 1 });
const PLAYBACK_SPEEDS: PlaybackSpeed[] = [0.25, 0.5, 0.75, 1];
const normalizeSpeed = (value: number): PlaybackSpeed => PLAYBACK_SPEEDS.reduce((closest, candidate) => Math.abs(candidate - value) < Math.abs(closest - value) ? candidate : closest, 1 as PlaybackSpeed);
const normalizePlayback = (options: PlaybackOptions): PlaybackOptions => ({ ...options, speed: normalizeSpeed(options.speed), loopCount: options.mode === 'single' ? 1 : options.loopCount });
const asPose = (action: DeviceControlQuickAction, source: PosePreset['source']): PosePreset => ({ kind: 'pose', id: action.id, name: action.label, source, positions: action.positions, category: action.category, detail: action.detail });
const asLegacyProgrammedAction = (recording: ActionRecording): ProgrammedAction => ({ kind: 'sequence', id: recording.id, name: recording.name, source: 'local', poseIds: [], poses: [], playback: defaultPlayback(), frames: recording.frames, durationMs: recording.durationMs, steps: recording.steps, createdAt: recording.updatedAt, updatedAt: recording.updatedAt });
const legacyOptions = (options: PlaybackOptions) => ({ speed: options.speed, loopCount: options.mode === 'single' ? 1 : options.loopCount, ...(options.direction === 'reverse' ? { direction: 'reverse' as const } : {}) });

export function ActionCenter({
  actions, motion: _motion, locked, controller, customPresets, localPresets, onLocalPresetsChange, programmedActions, onProgrammedActionsChange, capabilities, telemetry, debugMode, isPhysicalDevice, onVirtualPoseChange,
}: {
  actions: ActionPort;
  motion: MotionPort;
  locked: boolean;
  controller?: ActionController;
  /** Homepage-owned, one-way synchronized poses. */
  customPresets?: DeviceControlQuickAction[];
  /** Controlled action-center-owned poses. */
  localPresets?: DeviceControlQuickAction[];
  onLocalPresetsChange?: (presets: DeviceControlQuickAction[]) => void;
  /** Controlled programmed actions; omit for feature-local session persistence. */
  programmedActions?: ProgrammedAction[];
  onProgrammedActionsChange?: (actions: ProgrammedAction[]) => void;
  capabilities?: DeviceCapabilities;
  telemetry?: TelemetryPort;
  debugMode?: boolean;
  /** Explicitly identifies hardware; keeps preview/apply gating independent from debug mode. */
  isPhysicalDevice?: boolean;
  /** Lets the shell/virtual hand consume the unsaved editor draft in debug mode. */
  onVirtualPoseChange?: (positions: number[]) => void;
}) {
  const { t, locale } = useI18n();
  const [legacyRecordings, setLegacyRecordings] = useState<ActionRecording[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>();
  const [tab, setTab] = useState<Tab>('all');
  const [playback, setPlayback] = useState<PlaybackOptions>(defaultPlayback);
  const [controllerState, setControllerState] = useState<ActionControllerState>(idleState);
  const [localPoseState, setLocalPoseState] = useState<DeviceControlQuickAction[]>(() => localPresets ?? []);
  const [localActionState, setLocalActionState] = useState<ProgrammedAction[]>(() => programmedActions ?? []);
  const [selectionMode, setSelectionMode] = useState(false);
  const [selectedPoseIds, setSelectedPoseIds] = useState<string[]>([]);
  const [composer, setComposer] = useState<ComposerDraft | null>(null);
  const [poseDrafting, setPoseDrafting] = useState(false);
  const [poseName, setPoseName] = useState('');
  const [sliderValues, setSliderValues] = useState<number[]>([]);
  const [draftValues, setDraftValues] = useState<number[]>([]);
  const [draftBaseline, setDraftBaseline] = useState<number[]>([]);
  const [draftDirty, setDraftDirty] = useState(false);
  const [previewedPose, setPreviewedPose] = useState<PosePreset>();
  const [recordingDrafting, setRecordingDrafting] = useState(false);
  const [recordingName, setRecordingName] = useState('');

  const refreshLegacy = useCallback(async () => {
    setLoading(true); setError(undefined);
    try { setLegacyRecordings(await actions.list()); } catch { setError('动作列表暂时不可用，请稍后重试。'); } finally { setLoading(false); }
  }, [actions]);
  useEffect(() => { void refreshLegacy(); }, [refreshLegacy]);
  useEffect(() => { if (localPresets !== undefined) setLocalPoseState(localPresets); }, [localPresets]);
  useEffect(() => { if (programmedActions !== undefined) setLocalActionState(programmedActions); }, [programmedActions]);
  useEffect(() => {
    if (!controller) { setControllerState(idleState); return; }
    let mounted = true;
    void controller.getState().then(state => { if (mounted) setControllerState(state); }).catch(() => setError('动作控制器状态暂时不可用。'));
    return () => { mounted = false; };
  }, [controller]);
  useEffect(() => controller ? controller.subscribe(setControllerState) : undefined, [controller]);
  useEffect(() => {
    if (!telemetry || !capabilities || capabilities.jointCount <= 0) return;
    const { min, max } = capabilities.position.range;
    const normalize = (raw: number) => Math.max(0, Math.min(1, (raw - min) / Math.max(1, max - min)));
    const update = (snapshot: { rawPosition: number[] }) => {
      const next = Array.from({ length: capabilities.jointCount }, (_, index) => normalize(snapshot.rawPosition[index] ?? 0));
      setSliderValues(next);
      setDraftValues(previous => draftDirty ? previous : next);
      setDraftBaseline(previous => draftDirty ? previous : next);
    };
    let mounted = true;
    void telemetry.read().then(snapshot => { if (mounted) update(snapshot); }).catch(() => undefined);
    const unsubscribe = telemetry.subscribe(update);
    return () => { mounted = false; unsubscribe(); };
  }, [telemetry, capabilities, draftDirty]);

  useEffect(() => {
    if (debugMode) onVirtualPoseChange?.([...draftValues]);
  }, [debugMode, draftValues, onVirtualPoseChange]);

  const builtinPoses = useMemo(() => [...O6_BASIC_ACTIONS, ...O6_NUMBER_ACTIONS].map(action => asPose(action, 'builtin')), []);
  const homepagePoses = useMemo(() => (customPresets ?? []).map(action => asPose(action, 'homepage')), [customPresets]);
  const localPoses = useMemo(() => localPoseState.map(action => asPose(action, 'local')), [localPoseState]);
  const allPoses = useMemo(() => [...builtinPoses, ...homepagePoses, ...localPoses], [builtinPoses, homepagePoses, localPoses]);
  const customPoses = useMemo(() => [...homepagePoses, ...localPoses], [homepagePoses, localPoses]);
  const effectiveActions = programmedActions ?? localActionState;
  const poseById = useMemo(() => new Map(allPoses.map(pose => [pose.id, pose])), [allPoses]);
  const controllerReady = Boolean(controller);
  const canExecute = Boolean(debugMode || isPhysicalDevice === true || (debugMode === undefined && isPhysicalDevice === undefined));
  const physicalSafetyPath = Boolean(isPhysicalDevice === true && !debugMode);
  const recording = controllerState.state === 'recording' || controllerState.state === 'recordingPaused';
  const playing = controllerState.state === 'playing' || controllerState.state === 'paused';
  const active = controllerState.actionId ? [...allPoses, ...effectiveActions].find(item => item.id === controllerState.actionId) : undefined;
  const invoke = async (operation: () => Promise<void>, failure: string) => { try { await operation(); } catch { setError(failure); } };

  const runPose = (pose: PosePreset) => {
    if (!controller || locked || !canExecute) return;
    const options = normalizePlayback(playback);
    const operation = controller.applyPose ? () => controller.applyPose!(pose, options) : controller.playPose ? () => controller.playPose!(pose, options) : controller.play ? () => controller.play!(pose.id, legacyOptions(options)) : undefined;
    if (operation) void invoke(operation, '姿态未能启动，请确认设备已连接且控制未锁定。');
    else setError('运行时尚未提供 playPose，无法执行完整姿态目标。');
  };
  const runProgrammedAction = (action: ProgrammedAction) => {
    if (!controller || locked || !canExecute) return;
    const options = normalizePlayback(action.playback);
    const operation = controller.playProgrammedAction ? () => controller.playProgrammedAction!(action, options) : controller.play ? () => controller.play!(action.id, legacyOptions(options)) : undefined;
    if (operation) void invoke(operation, '动作未能启动，请确认设备已连接且控制未锁定。');
    else setError('运行时尚未提供 playProgrammedAction，无法执行完整动作序列。');
  };
  const togglePose = (id: string) => setSelectedPoseIds(previous => previous.includes(id) ? previous.filter(itemId => itemId !== id) : [...previous, id]);
  const openComposer = () => { setSelectionMode(true); setSelectedPoseIds([]); setComposer({ name: '', order: [], playback: { ...playback } }); };
  const openComposerDraft = () => { if (selectedPoseIds.length < 1) return; setComposer({ name: '', order: [...selectedPoseIds], playback: { ...playback } }); };
  const moveComposerItem = (index: number, delta: -1 | 1) => setComposer(previous => {
    if (!previous) return previous;
    const target = index + delta; if (target < 0 || target >= previous.order.length) return previous;
    const order = [...previous.order]; [order[index], order[target]] = [order[target], order[index]]; return { ...previous, order };
  });
  const saveProgrammedAction = () => {
    if (!composer || !composer.name.trim() || composer.order.length === 0) return;
    const poses = composer.order.map(id => poseById.get(id)).filter((pose): pose is PosePreset => Boolean(pose));
    if (poses.length !== composer.order.length) return;
    const action: ProgrammedAction = { kind: 'sequence', id: `action-center-action:${Date.now()}`, name: composer.name.trim(), source: 'local', poseIds: [...composer.order], poses, playback: normalizePlayback(composer.playback), createdAt: new Date().toISOString(), steps: poses.length };
    const next = [...localActionState, action];
    setLocalActionState(next); onProgrammedActionsChange?.(next);
    setComposer(null); setSelectionMode(false); setSelectedPoseIds([]);
  };
  const savePose = () => {
    if (!poseName.trim() || !capabilities || capabilities.jointCount <= 0) return;
    const preset: DeviceControlQuickAction = { id: `action-center-pose:${Date.now()}`, label: poseName.trim(), category: 'custom', positions: Array.from({ length: capabilities.jointCount }, (_, index) => draftValues[index] ?? sliderValues[index] ?? 0) };
    const next = [...localPoseState, preset]; setLocalPoseState(next); onLocalPresetsChange?.(next); setPoseName(''); setPoseDrafting(false);
  };
  const removePose = (pose: PosePreset) => {
    if (pose.source !== 'local') return;
    const next = localPoseState.filter(item => item.id !== pose.id); setLocalPoseState(next); onLocalPresetsChange?.(next);
  };
  const removeProgrammedAction = (action: ProgrammedAction) => {
    const next = localActionState.filter(item => item.id !== action.id); setLocalActionState(next); onProgrammedActionsChange?.(next);
  };
  const updateDraftValue = (index: number, value: number) => {
    setDraftDirty(true);
    setDraftValues(previous => { const next = [...previous]; next[index] = value; return next; });
  };
  const readCurrentPosition = async () => {
    if (!telemetry || !capabilities) return;
    try {
      const snapshot = await telemetry.read();
      const { min, max } = capabilities.position.range;
      const next = Array.from({ length: capabilities.jointCount }, (_, index) => Math.max(0, Math.min(1, ((snapshot.rawPosition[index] ?? 0) - min) / Math.max(1, max - min))));
      setSliderValues(next); setDraftValues(next); setDraftBaseline(next); setDraftDirty(false);
    } catch { setError('当前位置读取失败，请确认遥测已连接。'); }
  };
  const resetDraft = () => { const next = draftBaseline.length > 0 ? draftBaseline : sliderValues; setDraftValues([...next]); setDraftDirty(false); };
  const draftPose: PosePreset = { kind: 'pose', id: 'action-center-draft', name: '编辑中的姿态', source: 'local', positions: [...draftValues] };
  const previewDraft = () => {
    if (!canExecute) return;
    setPreviewedPose(draftPose);
    if (controller?.previewPose) void invoke(() => controller.previewPose!(draftPose), '姿态预览失败。');
  };
  const applyPreview = () => {
    if (!previewedPose || locked) return;
    runPose(previewedPose);
    setPreviewedPose(undefined);
  };
  const startRecording = () => { if (!canExecute || !controller?.startRecording || !recordingName.trim()) return; void invoke(() => controller.startRecording!(recordingName.trim()), '录制未启动，请确认运行时已连接。'); };
  const cancelRecording = () => { if (!controller?.cancelRecording) return; void invoke(() => controller.cancelRecording!().then(() => setRecordingDrafting(false)), '取消录制失败。'); };
  const finishRecording = () => { if (!controller?.finishRecording) return; void invoke(() => controller.finishRecording!().then(refreshLegacy), '完成录制失败。'); };
  const visiblePoses = tab === 'builtin' ? builtinPoses : tab === 'custom' ? customPoses : allPoses;
  const basicBuiltins = builtinPoses.filter(pose => pose.category === 'basic');
  const numberBuiltins = builtinPoses.filter(pose => pose.category === 'number');
  const showJointSliderCard = Boolean(capabilities && capabilities.jointCount > 0);
  const editorReady = draftValues.length === (capabilities?.jointCount ?? 0) && draftValues.length > 0;
  const builtInName = (pose: PosePreset) => locale === 'en' ? ({ open: 'Open', fist: 'Fist', ok: 'OK', 'thumbs-up': 'Thumbs up', one: 'One', two: 'Two', three: 'Three', four: 'Four', five: 'Five' } as Record<string, string>)[pose.id] ?? pose.name : pose.name;

  const requestPose = (pose: PosePreset) => { if (physicalSafetyPath) setPreviewedPose(pose); else runPose(pose); };
  const renderPoseButton = (pose: PosePreset) => <Button variant="secondary" className="preset-button" key={pose.id} disabled={!controller || locked || !canExecute} onClick={() => requestPose(pose)}>{pose.category === 'number' ? <Hash size={16} /> : <Hand size={16} />}<span>{builtInName(pose)}</span></Button>;
  const renderPoseRow = (pose: PosePreset) => <div className={`table-row actions-table-row ${selectionMode ? 'loop-mode' : ''}`} key={`${pose.source}:${pose.id}`}>
    {selectionMode && <Checkbox checked={selectedPoseIds.includes(pose.id)} onChange={() => togglePose(pose.id)} aria-label={`${locale === 'en' ? 'Select' : '选择'} ${builtInName(pose)}`} />}
    <strong>{builtInName(pose)}</strong><span><Badge tone={pose.source === 'builtin' ? 'blue' : pose.source === 'homepage' ? 'amber' : 'green'}>{pose.source === 'builtin' ? (locale === 'en' ? 'Built-in' : '内置') : pose.source === 'homepage' ? (locale === 'en' ? 'Homepage' : '首页') : (locale === 'en' ? 'Action center' : '动作中心')}</Badge></span><span>{locale === 'en' ? 'Static pose' : '静止姿态'}</span><span>{locale === 'en' ? 'Keyframe' : '关键帧'}</span>
     <div className="heading-actions"><Button variant="ghost" disabled={locked || !controllerReady || !canExecute || selectionMode} onClick={() => requestPose(pose)}>{physicalSafetyPath ? '预览' : t('common.button.play')}</Button>{pose.source === 'local' && <Button variant="ghost" disabled={locked} onClick={() => removePose(pose)}>{t('common.button.delete')}</Button>}</div>
  </div>;

  return <div className="stack">
    <div className="page-heading"><div><h1>{t('actions.title')}</h1><p className="muted">{t('actions.subtitle')}</p></div><div className="heading-actions">{selectionMode ? <><Button variant="ghost" onClick={() => { setSelectionMode(false); setSelectedPoseIds([]); setComposer(null); }}>{t('actions.select.cancel')}</Button>{selectedPoseIds.length > 0 && <Button variant="primary" onClick={openComposerDraft}><ListOrdered size={14} />{t('actions.compose')}</Button>}</> : <Button variant="primary" onClick={openComposer}>{t('actions.new')}</Button>}<Button variant="secondary" onClick={() => setRecordingDrafting(true)} disabled={!controllerReady || !canExecute || recording}>{t('actions.record.compatible')}</Button></div></div>
    {debugMode && <Badge tone="amber">{t('common.status.debug')}</Badge>}
    {showJointSliderCard && <Card className="joint-slider-card">
      <div className="card-header"><div><h2>姿态编辑器</h2><span className="muted">{capabilities!.jointCount} 个关节 · {debugMode ? '调试草稿不会发送到真实设备' : '先读取当前位置，再预览或应用'}</span></div><div className="heading-actions"><Badge tone={debugMode ? 'blue' : 'amber'}>{debugMode ? '虚拟机械手' : '安全预览'}</Badge><Button variant="ghost" onClick={() => void readCurrentPosition()}>读取当前位置</Button><Button variant="ghost" onClick={resetDraft} disabled={!editorReady}>重置草稿</Button></div></div>
      {debugMode && <div className="permission-note" role="status">调试模式：滑块与未保存姿态同步虚拟机械手，不会发送真实硬件命令。</div>}
      {poseDrafting && <div className="settings-row pose-draft"><TextField label="姿态名称" id="pose-name" value={poseName} onChange={event => setPoseName(event.target.value)} placeholder="例如：准备姿态" /><Button variant="ghost" onClick={() => setPoseDrafting(false)}>取消</Button><Button variant="primary" disabled={!poseName.trim() || !editorReady} onClick={savePose}>保存到动作中心</Button></div>}
      <div className="joint-slider-grid">{Array.from({ length: capabilities!.jointCount }, (_, index) => <div className="joint-slider-item" key={index}><JointSlider index={index} label={O6_JOINT_NAMES[index]} value={draftValues[index] ?? sliderValues[index] ?? 0} disabled={!debugMode || locked} onBegin={() => undefined} onInput={updateDraftValue} onFinish={() => undefined} /><span className="visually-hidden">{Math.round((draftValues[index] ?? sliderValues[index] ?? 0) * 100)}%</span></div>)}</div>
      <div className="heading-actions pose-editor-actions"><Button variant="ghost" disabled={!editorReady || locked || !canExecute} onClick={previewDraft}>预览当前姿态</Button>{previewedPose && <><span className="muted">已预览：{previewedPose.name}</span><Button variant="primary" disabled={!physicalSafetyPath || locked || !canExecute} onClick={applyPreview}>应用到设备</Button></>}</div>
      <div className="heading-actions"><Button variant="ghost" onClick={() => setPoseDrafting(true)}><Save size={14} />保存当前姿态为自定义姿态</Button></div>
    </Card>}
    {previewedPose && !showJointSliderCard && <Card className="pose-preview-card"><div className="card-header"><div><h2>姿态预览</h2><span className="muted">{previewedPose.name} 尚未发送到设备。</span></div><Button variant="primary" disabled={!physicalSafetyPath || locked} onClick={applyPreview}>应用到设备</Button></div></Card>}
    {!controllerReady && <div className="permission-note" role="status">{t('actions.controllerMissing')}</div>}
    {controllerReady && !canExecute && <div className="permission-note" role="status">未连接真实机械手：请先连接设备，或在设置中启用调试模式。</div>}
    {composer && <Card className="composer-card"><div className="card-header"><div><h2>编排动作</h2><span className="muted">候选仅包含静止姿态，按选择顺序形成 ProgrammedAction。</span></div><Button variant="ghost" onClick={() => setComposer(null)}>关闭</Button></div><div className="settings-row"><TextField label="动作名称" id="action-name" value={composer.name} onChange={event => setComposer(previous => previous ? { ...previous, name: event.target.value } : null)} placeholder="例如：迎宾动作" /></div><div className="loop-order-section"><div className="card-header"><span className="muted">关键帧顺序（{composer.order.length} 项）</span><Button variant="ghost" disabled={!composer.order.length} onClick={() => setComposer(previous => previous ? { ...previous, order: [] } : null)}>清空</Button></div>{composer.order.map((id, index) => { const pose = poseById.get(id); return <div className="loop-order-item" key={`${id}-${index}`}><span>{index + 1}. {pose?.name ?? id}</span><div className="heading-actions"><Button variant="ghost" aria-label={`上移 ${pose?.name ?? id}`} disabled={index === 0} onClick={() => moveComposerItem(index, -1)}>↑</Button><Button variant="ghost" aria-label={`下移 ${pose?.name ?? id}`} disabled={index === composer.order.length - 1} onClick={() => moveComposerItem(index, 1)}>↓</Button><Button variant="ghost" onClick={() => setComposer(previous => previous ? { ...previous, order: previous.order.filter((_, itemIndex) => itemIndex !== index) } : null)}>移除</Button></div></div>; })}</div><div className="settings-row"><Select label="播放模式" id="composer-mode" value={composer.playback.mode} onChange={event => setComposer(previous => previous ? { ...previous, playback: { ...previous.playback, mode: event.target.value as PlaybackMode } } : null)}><option value="single">单次</option><option value="loop">循环</option></Select><Select label="倍速" id="composer-speed" value={composer.playback.speed} onChange={event => setComposer(previous => previous ? { ...previous, playback: { ...previous.playback, speed: normalizeSpeed(Number(event.target.value)) } } : null)}><option value="0.25">0.25×</option><option value="0.5">0.5×</option><option value="0.75">0.75×</option><option value="1">1×</option></Select><Select label="方向" id="composer-direction" value={composer.playback.direction} onChange={event => setComposer(previous => previous ? { ...previous, playback: { ...previous.playback, direction: event.target.value as PlaybackDirection } } : null)}><option value="forward">正放</option><option value="reverse">倒放</option></Select>{composer.playback.mode === 'loop' && <Select label="循环次数" id="composer-loops" value={composer.playback.loopCount === null ? '0' : String(composer.playback.loopCount)} onChange={event => setComposer(previous => previous ? { ...previous, playback: { ...previous.playback, loopCount: event.target.value === '0' ? null : Number(event.target.value) } } : null)}><option value="1">1 次</option><option value="3">3 次</option><option value="5">5 次</option><option value="10">10 次</option><option value="0">无限</option></Select>}</div><div className="heading-actions" style={{ justifyContent: 'flex-end' }}><Button variant="ghost" onClick={() => setComposer(null)}>取消</Button><Button variant="primary" disabled={!composer.name.trim() || composer.order.length === 0} onClick={saveProgrammedAction}>保存动作</Button></div></Card>}
    {playing && <Card><div className="card-header"><div><h2>正在播放：{active?.name ?? controllerState.actionId ?? '动作'}</h2><span className="muted">{playback.direction === 'reverse' ? '倒放' : '正放'} · {playback.speed.toFixed(2)}× · {playback.mode === 'single' ? '单次' : playback.loopCount === null ? '无限循环' : `${playback.loopCount} 次循环`}</span></div><div className="heading-actions"><Badge tone={controllerState.state === 'paused' ? 'amber' : 'blue'}>{controllerState.state === 'paused' ? '已暂停' : '运行中'}</Badge><Button variant="ghost" onClick={() => void invoke(() => controller?.stop ? controller.stop() : Promise.reject(new Error('stop unavailable')), '停止失败。')}>停止</Button></div></div><Progress value={controllerState.progress} /><span className="muted">{Math.round(controllerState.progress)}% · {controllerState.detail ?? '等待运行时状态'}</span></Card>}
    <Card><div className="card-header"><div><div className="heading-actions"><Button variant={tab === 'all' ? 'secondary' : 'ghost'} onClick={() => setTab('all')}>{t('actions.tabs.all')}</Button><Button variant={tab === 'builtin' ? 'secondary' : 'ghost'} onClick={() => setTab('builtin')}>{t('actions.tabs.builtin')}</Button><Button variant={tab === 'custom' ? 'secondary' : 'ghost'} onClick={() => setTab('custom')}>{t('actions.tabs.custom')}</Button></div><span className="muted">{t('actions.tabs.summary')}</span></div><div className="heading-actions"><Select label={t('common.label.speed')} id="speed" value={playback.speed} onChange={event => setPlayback(previous => ({ ...previous, speed: normalizeSpeed(Number(event.target.value)) }))} disabled={!controllerReady}><option value="0.25">0.25×</option><option value="0.5">0.5×</option><option value="0.75">0.75×</option><option value="1">1×</option></Select><Select label={t('common.label.direction')} id="direction" value={playback.direction} onChange={event => setPlayback(previous => ({ ...previous, direction: event.target.value as PlaybackDirection }))} disabled={!controllerReady}><option value="forward">{t('common.label.forward')}</option><option value="reverse">{t('common.label.reverse')}</option></Select><Select label={locale === 'en' ? 'Playback mode' : '播放模式'} id="playback-mode" value={playback.mode} onChange={event => setPlayback(previous => ({ ...previous, mode: event.target.value as PlaybackMode }))} disabled={!controllerReady}><option value="single">{t('common.label.single')}</option><option value="loop">{t('common.label.loop')}</option></Select></div></div>{tab === 'builtin' ? <div><div className="preset-section"><strong>{t('actions.tabs.builtin')}</strong><div className="preset-grid preset-grid-basic">{basicBuiltins.map(renderPoseButton)}</div></div><div className="preset-section"><strong>{locale === 'en' ? 'Number presets' : '数字预设'}</strong><div className="preset-grid preset-grid-number">{numberBuiltins.map(renderPoseButton)}</div></div></div> : loading ? <div className="empty"><span>{t('common.status.loading')}</span></div> : error ? <div className="permission-note" role="alert">{error}</div> : visiblePoses.length === 0 ? <EmptyState title={t('actions.empty.title')} detail={t('actions.empty.detail')} /> : <><div className={`table-head actions-table-head ${selectionMode ? 'loop-mode' : ''}`}>{selectionMode && <span>{locale === 'en' ? 'Select' : '选择'}</span>}<span>{locale === 'en' ? 'Name' : '名称'}</span><span>{locale === 'en' ? 'Source' : '来源'}</span><span>{locale === 'en' ? 'Type' : '类型'}</span><span>{locale === 'en' ? 'Duration' : '时长'}</span><span /></div>{visiblePoses.map(renderPoseRow)}</>}</Card>
    {effectiveActions.length > 0 && <Card className="programmed-actions-card"><div className="card-header"><div><h2>动作</h2><span className="muted">已编排的 ProgrammedAction；不作为姿态候选。</span></div></div>{effectiveActions.map(action => <div className="table-row sequence-row" key={action.id}><strong>{action.name}</strong><span>{action.poseIds.length || action.steps || action.frames?.length || 0} 个姿态</span><span>{action.playback.mode === 'single' ? '单次' : action.playback.loopCount === null ? '无限循环' : `${action.playback.loopCount} 次循环`}</span><span>{action.playback.direction === 'reverse' ? '倒放' : '正放'} · {action.playback.speed}×</span><div className="heading-actions"><Button variant="ghost" className="button button-ghost" disabled={!controllerReady || !canExecute || locked} onClick={() => runProgrammedAction(action)}>播放</Button><Button variant="ghost" className="button button-ghost" disabled={locked} onClick={() => removeProgrammedAction(action)}>删除</Button></div></div>)}</Card>}
    {legacyRecordings.length > 0 && <Card className="legacy-actions-card"><details><summary className="card-header"><div><h2>录制兼容区</h2><span className="muted">旧版 ActionRecording 仅用于兼容回放，不参与姿态编排。</span></div><span className="button button-ghost">展开</span></summary><div className="heading-actions" style={{ justifyContent: 'flex-end', marginTop: 8 }}><Button variant="ghost" onClick={() => setRecordingDrafting(true)} disabled={!controllerReady || recording}>录制</Button></div>{legacyRecordings.map(recording => <div className="table-row sequence-row" key={recording.id}><strong>{recording.name}</strong><span>{recording.steps} 帧</span><span>{(recording.durationMs / 1000).toFixed(1)} 秒</span><div className="heading-actions"><Button variant="ghost" disabled={!controllerReady || locked || !controller?.play} onClick={() => void invoke(() => controller!.play!(recording.id, legacyOptions(playback)), '兼容动作播放失败。')}>播放</Button></div></div>)}</details></Card>}
    {recordingDrafting && <Card><div className="card-header"><div><h2>录制兼容动作</h2><span className="muted">录制结果仅进入兼容区，不会成为姿态候选。</span></div></div><div className="settings-row"><TextField label="动作名称" id="recording-name" value={recordingName} onChange={event => setRecordingName(event.target.value)} /><Button variant="ghost" onClick={() => setRecordingDrafting(false)}>取消</Button><Button variant="primary" disabled={!recordingName.trim() || !controller?.startRecording} onClick={startRecording}>开始录制</Button>{recording && <><Button variant="ghost" onClick={cancelRecording}>取消录制</Button><Button variant="primary" onClick={finishRecording}>完成录制</Button></>}</div></Card>}
    <Card className="tip-card"><Badge>操作提示</Badge><span>动作中心本地姿态和动作通过受控 props/onChange 保持；首页姿态始终只读单向同步。</span></Card>
  </div>;
}
