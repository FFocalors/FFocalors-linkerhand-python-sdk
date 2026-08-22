import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ConnectionSnapshot, DeviceCapabilities, DeviceConfig, DevicePort, JointTargetCommand, OperationSnapshot, TelemetryPort, TelemetrySnapshot } from '../../shared/contracts';
import { Badge, Card } from '../../shared/ui';

/** Feature-local controller seam. The runtime adapter can implement this without changing shared contracts. */
export interface DeviceControlController {
  connect(): Promise<void>;
  disconnect(): Promise<void>;
  reconnect(): Promise<void>;
  subscribeConnection(listener: (snapshot: ConnectionSnapshot) => void): () => void;
  setJointTarget(command: JointTargetCommand): Promise<void>;
  setSpeed(command: DeviceControlVectorCommand): Promise<void>;
  setTorque(command: DeviceControlVectorCommand): Promise<void>;
  startQuickAction(actionId: string): Promise<void>;
  stopQuickAction(): Promise<void>;
  startLoop(loopId: string): Promise<void>;
  stopLoop(): Promise<void>;
  subscribeOperation?(listener: (snapshot: OperationSnapshot) => void): () => void;
}

export interface DeviceControlVectorCommand { values: number[]; finalCommand: boolean }
export interface DeviceControlQuickAction { id: string; label: string; detail?: string }
export interface DeviceControlLoop { id: string; label: string; detail?: string }
interface DeviceControlProps {
  device: DevicePort;
  telemetry: TelemetryPort;
  config: DeviceConfig;
  capabilities: DeviceCapabilities;
  locked?: boolean;
  controller?: DeviceControlController;
  quickActions?: DeviceControlQuickAction[];
  loops?: DeviceControlLoop[];
  onNavigateToDiagnostics?: () => void;
}

const clamp = (value: number) => Math.max(0, Math.min(1, Number.isFinite(value) ? value : 0));
const toVector = (values: number[], length: number) => Array.from({ length }, (_, index) => clamp(values[index] ?? 0));
const connectionLabels: Record<ConnectionSnapshot['state'], string> = { disconnected: '未连接', connecting: '连接中', connected: '已连接', reconnecting: '重连中', error: '连接错误' };
function statusTone(state: ConnectionSnapshot['state']): 'blue' | 'green' | 'amber' | 'red' { if (state === 'connected') return 'green'; if (state === 'error') return 'red'; if (state === 'disconnected') return 'amber'; return 'blue'; }
function errorText(error: unknown) { if (error instanceof Error) return error.message; return typeof error === 'string' ? error : '操作未完成，请查看诊断中心。'; }

export function DeviceControl({ device, telemetry, config, capabilities, locked = false, controller, quickActions = [{ id: 'safe-position', label: '回到安全位', detail: '由设备控制器执行' }], loops = [], onNavigateToDiagnostics }: DeviceControlProps) {
  const jointCount = Math.max(0, capabilities.jointCount);
  const [values, setValues] = useState<number[]>(() => toVector([], jointCount));
  const [live, setLive] = useState<TelemetrySnapshot>();
  const [connection, setConnection] = useState<ConnectionSnapshot>({ schemaVersion: capabilities.schemaVersion, deviceId: capabilities.deviceId, state: 'disconnected', attempt: 0, lastError: null });
  const [safetyLocked, setSafetyLocked] = useState(false);
  const [busy, setBusy] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [torque, setTorque] = useState(1);
  const [operation, setOperation] = useState<OperationSnapshot>();
  const [errorMessage, setErrorMessage] = useState('');
  const [rawOpen, setRawOpen] = useState(false);
  const [activeQuickAction, setActiveQuickAction] = useState<string>();
  const [activeLoop, setActiveLoop] = useState<string>();
  const valuesRef = useRef(values);
  const dragging = useRef(new Set<number>());
  const pendingVector = useRef<number[]>(values);
  const rafRef = useRef<number | undefined>(undefined);
  const commandNumber = useRef(0);
  const connectionRef = useRef(connection);
  const lockedRef = useRef(locked || safetyLocked);
  const isLocked = locked || safetyLocked;
  const applyConnection = useCallback((snapshot: ConnectionSnapshot) => { connectionRef.current = snapshot; setConnection(snapshot); }, []);

  useEffect(() => { valuesRef.current = values; }, [values]);
  useEffect(() => { connectionRef.current = connection; }, [connection]);
  useEffect(() => { lockedRef.current = isLocked; }, [isLocked]);
  useEffect(() => { let mounted = true; void device.getConnection().then(snapshot => { if (mounted) applyConnection(snapshot); }).catch(error => { if (mounted) setErrorMessage(errorText(error)); }); return () => { mounted = false; }; }, [applyConnection, device]);
  useEffect(() => {
    let mounted = true;
    void telemetry.read().then(snapshot => { if (!mounted) return; setLive(snapshot); const next = toVector(snapshot.positions, jointCount); if (dragging.current.size === 0) { valuesRef.current = next; pendingVector.current = next; setValues(next); } }).catch(error => { if (mounted) setErrorMessage(errorText(error)); });
    const unsubscribe = telemetry.subscribe(snapshot => { setLive(snapshot); const next = toVector(snapshot.positions, jointCount); if (dragging.current.size === 0) { valuesRef.current = next; pendingVector.current = next; setValues(next); } });
    return () => { mounted = false; unsubscribe(); };
  }, [jointCount, telemetry]);
  useEffect(() => { if (!controller) return undefined; const unsubscribeConnection = controller.subscribeConnection(applyConnection); const unsubscribeOperation = controller.subscribeOperation?.(snapshot => setOperation(snapshot)); return () => { unsubscribeConnection(); unsubscribeOperation?.(); }; }, [applyConnection, controller]);
  useEffect(() => () => { if (rafRef.current !== undefined) cancelAnimationFrame(rafRef.current); }, []);

  const submitJointVector = useCallback(async (vector: number[], finalCommand: boolean) => {
    if (!controller || lockedRef.current || connectionRef.current.state !== 'connected') return;
    try {
      await controller.setJointTarget({ schemaVersion: 1, commandId: `manual-${++commandNumber.current}`, source: 'manual', positions: toVector(vector, jointCount), finalCommand });
      if (finalCommand) setErrorMessage('');
    } catch (error) { setErrorMessage(`关节目标未送达：${errorText(error)}`); }
  }, [controller, jointCount]);
  const flushJointVector = useCallback((finalCommand: boolean) => { if (rafRef.current !== undefined) { cancelAnimationFrame(rafRef.current); rafRef.current = undefined; } const vector = toVector(pendingVector.current, jointCount); pendingVector.current = vector; void submitJointVector(vector, finalCommand); }, [jointCount, submitJointVector]);
  const scheduleJointVector = useCallback((vector: number[]) => { pendingVector.current = toVector(vector, jointCount); if (rafRef.current !== undefined) return; rafRef.current = requestAnimationFrame(() => { rafRef.current = undefined; void submitJointVector(pendingVector.current, false); }); }, [jointCount, submitJointVector]);
  const changeJoint = (index: number, value: number) => { const next = toVector(valuesRef.current, jointCount); next[index] = clamp(value); valuesRef.current = next; pendingVector.current = next; setValues(next); scheduleJointVector(next); };
  const finishJoint = (index: number) => { if (!dragging.current.has(index)) return; dragging.current.delete(index); flushJointVector(true); };
  const runController = async (action: () => Promise<void>, success?: () => void) => { setBusy(true); setErrorMessage(''); try { await action(); success?.(); } catch (error) { setErrorMessage(errorText(error)); } finally { setBusy(false); } };
  const connect = () => controller && runController(controller.connect);
  const disconnect = () => controller && runController(controller.disconnect);
  const reconnect = () => controller && runController(controller.reconnect);
  const stopAll = async () => { if (rafRef.current !== undefined) { cancelAnimationFrame(rafRef.current); rafRef.current = undefined; } dragging.current.clear(); pendingVector.current = valuesRef.current; setSafetyLocked(true); setActiveQuickAction(undefined); setActiveLoop(undefined); setErrorMessage(''); try { await device.stopAll(); } catch (error) { setErrorMessage(`停止命令未送达：${errorText(error)}`); } };
  const unlock = async () => { setBusy(true); setErrorMessage(''); try { await device.unlock(); if (connectionRef.current.state === 'connected') setSafetyLocked(false); else setErrorMessage('设备尚未回到可控状态，保持锁定；请先连接设备。'); } catch (error) { setErrorMessage(`恢复控制未完成：${errorText(error)}`); } finally { setBusy(false); } };
  const setVectorCapability = (kind: 'speed' | 'torque', value: number) => { const length = kind === 'speed' ? capabilities.speedCommandLength : capabilities.torqueCommandLength ?? 0; if (!controller || length <= 0 || isLocked || connection.state !== 'connected') return; const command = { values: Array.from({ length }, () => clamp(value)), finalCommand: true }; void runController(() => kind === 'speed' ? controller.setSpeed(command) : controller.setTorque(command)); };
  const groups = useMemo(() => Array.from({ length: Math.ceil(jointCount / 5) }, (_, groupIndex) => ({ start: groupIndex * 5, end: Math.min(jointCount, groupIndex * 5 + 5) })), [jointCount]);
  const operationLabel = operation?.state === 'running' ? '执行中' : operation?.state === 'completed' ? '已完成' : operation?.state === 'error' ? '失败' : operation?.state;
  const positionTrend = live && live.positions.length > 0 ? `${Math.round(live.positions.reduce((sum, value) => sum + value, 0) / live.positions.length * 100)}% 平均目标` : '等待遥测';

  return <div className="stack">
    <div className="page-heading"><div><p className="eyebrow">工作台 / 设备控制</p><h1>设备控制</h1><p>所有目标都通过设备控制器提交，硬件状态以实时遥测为准。</p></div><div className="heading-actions"><Badge tone={statusTone(connection.state)}>{connectionLabels[connection.state]}</Badge><button aria-label="设备安全锁" className={`button ${isLocked ? 'button-secondary' : 'button-primary'}`} onClick={isLocked ? unlock : stopAll} disabled={busy}>{isLocked ? '恢复控制' : '停止全部动作'}</button></div></div>
    {!controller && <div className="permission-note">未接入设备控制器：为避免伪造硬件执行，连接、关节、速度、扭矩和动作控制均已禁用。集成 runtime adapter 后可用。</div>}
    {errorMessage && <div className="lock-banner" role="alert"><span><strong>操作未完成</strong> {errorMessage}</span><button onClick={() => setErrorMessage('')}>关闭</button></div>}
    <div className="grid grid-3"><Card className="device-summary span-2"><div className="card-header"><div><h2>{config.name}</h2><span className="muted">{config.transport.type === 'can' ? config.transport.channel : `${config.transport.port} · ${config.transport.baudrate} baud`} · {config.hand}</span></div><Badge>{capabilities.model} · {jointCount} 关节</Badge></div><div className="device-visual"><div className="arm-orb"><span>LH</span></div><div className="device-lines"><div><span>连接状态</span><strong>{connectionLabels[connection.state]}</strong></div><div><span>遥测序号</span><strong>{live?.sequence ?? '—'}</strong></div><div><span>位置趋势</span><strong>{positionTrend}</strong></div></div></div></Card><Card><div className="card-header"><div><h2>连接管理</h2><span className="muted">第 {connection.attempt} 次尝试</span></div><Badge tone={controller ? statusTone(connection.state) : 'amber'}>{controller ? connectionLabels[connection.state] : '控制器未接入'}</Badge></div><div className="grid grid-2" style={{ marginTop: 24 }}><button className="button button-primary" disabled={!controller || busy || connection.state === 'connected'} onClick={connect}>连接</button><button className="button button-secondary" disabled={!controller || busy || connection.state === 'disconnected'} onClick={disconnect}>断开</button></div><button className="button button-ghost" disabled={!controller || busy} onClick={reconnect}>重新连接</button>{connection.lastError && <p className="permission-note">{connection.lastError.message}</p>}</Card></div>
    <Card><div className="card-header"><div><h2>关节目标</h2><span className="muted">拖动中保留本地目标；松开、失焦或 Enter / Space 提交最终完整向量。</span></div><span className="muted">归一化命令域 · 0–100%</span></div>{groups.length === 0 && <p className="muted">当前能力未报告关节，控制不可用。</p>}<div className="joint-groups">{groups.map((group, groupIndex) => <details key={group.start} open={jointCount <= 10 || groupIndex === 0}><summary>关节 {group.start + 1}–{group.end}<span className="muted">{group.end - group.start} 个</span></summary><div className="joint-list">{Array.from({ length: group.end - group.start }, (_, offset) => group.start + offset).map(index => <label className="joint-row" key={index}><span className="joint-name">J{index + 1}</span><input aria-label={`J${index + 1} 目标`} type="range" min="0" max="1" step="0.01" value={values[index] ?? 0} disabled={!controller || isLocked || connection.state !== 'connected'} onPointerDown={() => dragging.current.add(index)} onPointerUp={() => finishJoint(index)} onPointerCancel={() => finishJoint(index)} onBlur={() => finishJoint(index)} onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); dragging.current.add(index); finishJoint(index); } }} onChange={event => changeJoint(index, Number(event.target.value))} /><output>{Math.round((values[index] ?? 0) * 100)}%</output></label>)}</div></details>)}</div><details open={rawOpen} onToggle={event => setRawOpen(event.currentTarget.open)}><summary>高级诊断：原始值估算 <span className="muted">仅命令域换算，不代表设备当前原始反馈</span></summary><div className="grid grid-3" style={{ marginTop: 12 }}><span className="muted">position raw 估算：{values.map(value => Math.round(value * (capabilities.position.range.max - capabilities.position.range.min) + capabilities.position.range.min)).join(', ') || '—'}</span><span className="muted">范围：{capabilities.position.range.min}–{capabilities.position.range.max}</span><span className="muted">遥测 raw position：{live?.rawPosition.join(', ') || '—'}</span></div></details></Card>
    <div className="grid grid-3"><Card><div className="card-header"><div><h2>速度</h2><span className="muted">{capabilities.speed.available && capabilities.speedCommandLength > 0 ? `${capabilities.speedCommandLength} 通道` : '能力不可用'}</span></div></div><div className="metric-lg">{Math.round(speed * 100)}<small>%</small></div><input aria-label="速度" type="range" min="0" max="1" step="0.01" value={speed} disabled={!controller || isLocked || connection.state !== 'connected' || !capabilities.speed.available || capabilities.speedCommandLength <= 0} onChange={event => setSpeed(Number(event.target.value))} onPointerUp={() => setVectorCapability('speed', speed)} onBlur={() => setVectorCapability('speed', speed)} /><button className="button button-ghost" disabled={!controller || isLocked || connection.state !== 'connected' || !capabilities.speed.available || capabilities.speedCommandLength <= 0} onClick={() => setVectorCapability('speed', speed)}>应用速度</button></Card><Card><div className="card-header"><div><h2>扭矩</h2><span className="muted">{capabilities.torque.available && (capabilities.torqueCommandLength ?? 0) > 0 ? `${capabilities.torqueCommandLength} 通道` : '能力不可用'}</span></div></div><div className="metric-lg">{Math.round(torque * 100)}<small>%</small></div><input aria-label="扭矩" type="range" min="0" max="1" step="0.01" value={torque} disabled={!controller || isLocked || connection.state !== 'connected' || !capabilities.torque.available || (capabilities.torqueCommandLength ?? 0) <= 0} onChange={event => setTorque(Number(event.target.value))} onPointerUp={() => setVectorCapability('torque', torque)} onBlur={() => setVectorCapability('torque', torque)} /><button className="button button-ghost" disabled={!controller || isLocked || connection.state !== 'connected' || !capabilities.torque.available || (capabilities.torqueCommandLength ?? 0) <= 0} onClick={() => setVectorCapability('torque', torque)}>应用扭矩</button></Card><Card><div className="card-header"><div><h2>当前动作</h2><span className="muted">来自控制器状态订阅</span></div><Badge tone={operation?.state === 'error' ? 'red' : operation?.state === 'running' ? 'blue' : 'green'}>{operationLabel ?? '等待状态'}</Badge></div><p className="muted" style={{ margin: '24px 0 8px' }}>{operation?.detail ?? '等待控制器返回真实动作状态。'}</p>{operation && <div className="progress"><span style={{ width: `${Math.max(0, Math.min(100, operation.progress * 100))}%` }} /></div>}<button className="button button-ghost" onClick={onNavigateToDiagnostics}>查看完整曲线 / 诊断中心 ↗</button></Card></div>
    <div className="grid grid-2"><Card><div className="card-header"><div><h2>快速动作</h2><span className="muted">真实执行状态由 controller 返回</span></div></div><div className="grid grid-2" style={{ marginTop: 16 }}>{quickActions.map(action => <button className="button button-secondary" key={action.id} disabled={!controller || isLocked || busy || Boolean(activeQuickAction || activeLoop)} onClick={() => { void runController(() => controller!.startQuickAction(action.id), () => setActiveQuickAction(action.id)); }}>{activeQuickAction === action.id ? `${action.label} · 执行中` : action.label}</button>)}<button className="button button-ghost" disabled={!controller || !activeQuickAction} onClick={() => { void runController(controller!.stopQuickAction, () => setActiveQuickAction(undefined)); }}>停止快速动作</button></div></Card><Card><div className="card-header"><div><h2>动作循环</h2><span className="muted">循环不会在浏览器定时发送硬件命令</span></div></div>{loops.length === 0 ? <p className="muted" style={{ marginTop: 18 }}>控制器尚未提供循环方案。</p> : <div className="grid grid-2" style={{ marginTop: 16 }}>{loops.map(loop => <button className="button button-secondary" key={loop.id} disabled={!controller || isLocked || busy || Boolean(activeLoop || activeQuickAction)} onClick={() => { void runController(() => controller!.startLoop(loop.id), () => setActiveLoop(loop.id)); }}>{activeLoop === loop.id ? `${loop.label} · 循环中` : loop.label}</button>)}<button className="button button-ghost" disabled={!controller || !activeLoop} onClick={() => { void runController(controller!.stopLoop, () => setActiveLoop(undefined)); }}>停止循环</button></div>}</Card></div><p className="muted">停止全部动作是软件锁定，不是物理断电急停；危险场景请使用设备的物理急停装置。</p>
  </div>;
}

export const README = '设备控制：控制器驱动连接、动作与安全锁；关节滑块以完整归一化向量通过 requestAnimationFrame 合帧提交。';
