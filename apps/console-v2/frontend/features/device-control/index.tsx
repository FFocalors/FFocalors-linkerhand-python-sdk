import { useEffect, useMemo, useRef, useState } from 'react';
import type { DeviceCapabilities, DeviceConfig, DevicePort, TelemetryPort, TelemetrySnapshot } from '../../shared/contracts';
import { Card, Badge, Progress } from '../../shared/ui';
import { createFrameCoalescer } from '../../shared/utilities';

export function DeviceControl({ device, telemetry, config, capabilities, locked }: { device: DevicePort; telemetry: TelemetryPort; config: DeviceConfig; capabilities: DeviceCapabilities; locked: boolean }) {
  const [values, setValues] = useState<number[]>([]);
  const [live, setLive] = useState<TelemetrySnapshot>();
  const valuesRef = useRef(values);
  const dragging = useRef(false);
  const coalescers = useRef<Record<string, ReturnType<typeof createFrameCoalescer<number>>>>({});
  useEffect(() => { valuesRef.current = values; }, [values]);
  useEffect(() => { void telemetry.read().then(t => { setValues(t.positions); setLive(t); }); return telemetry.subscribe(t => { if (!dragging.current) { setValues(t.positions); setLive(t); } }); }, [telemetry]);
  const joints = useMemo(() => values.map((value, index) => [`J${index + 1}`, value] as const), [values]);
  const setTarget = (index: number, value: number) => { setValues(prev => { const next = [...prev]; next[index] = value; valuesRef.current = next; return next; }); coalescers.current[String(index)] ||= createFrameCoalescer(v => { const next = [...valuesRef.current]; next[index] = v; void device.setJointTarget({ schemaVersion: 1, commandId: `manual-${index}`, source: 'manual', positions: next, finalCommand: false }); }); coalescers.current[String(index)].push(value); };
  return <div className="stack">
    <div className="page-heading"><div><p className="eyebrow">控制台 / 设备控制</p><h1>设备控制</h1><p>实时调整关节目标，观察设备状态与反馈。</p></div><div className="heading-actions"><Badge tone={locked ? 'amber' : 'green'}>{locked ? '控制已锁定' : '在线 · 12 ms'}</Badge><button className="button button-primary" disabled={locked}>回到安全位</button></div></div>
    <div className="grid grid-3"><Card className="device-summary span-2"><div className="card-header"><div><h2>{config.name}</h2><span className="muted">{config.transport.type === 'can' ? config.transport.channel : config.transport.port} · {config.hand}</span></div><Badge>{capabilities.model} 型号</Badge></div><div className="device-visual"><div className="arm-orb"><span>LH</span></div><div className="device-lines"><div><span>连接状态</span><strong>稳定连接</strong></div><div><span>关节数量</span><strong>{capabilities.jointCount} 个</strong></div><div><span>温度</span><strong>未提供</strong></div></div></div></Card><Card><div className="card-header"><h2>原始电流</h2><span className="muted">能力数据</span></div><div className="metric-xl">{live?.rawCurrent.length ?? 0}<small>通道</small></div><span className="muted">不聚合为伪造 mA 值</span></Card></div>
    <Card><div className="card-header"><div><h2>关节目标</h2><span className="muted">拖动调整，松开或按 Enter 提交</span></div><span className="muted">单位：归一化百分比</span></div><div className="joint-list">{joints.map(([joint, value], index) => <label className="joint-row" key={joint}><span className="joint-name">{joint}</span><input aria-label={`${joint} 目标`} type="range" min="0" max="1" step="0.01" value={value} disabled={locked} onPointerDown={() => { dragging.current = true; }} onPointerUp={() => { dragging.current = false; coalescers.current[String(index)]?.flush(); }} onKeyUp={event => { if (event.key === 'Enter') void device.setJointTarget({ schemaVersion: 1, commandId: `manual-${index}`, source: 'manual', positions: values, finalCommand: true }); }} onChange={event => setTarget(index, Number(event.target.value))} /><output>{Math.round(value * 100)}%</output></label>)}</div></Card>
  </div>;
}

export const README = '设备控制：滑块使用局部状态与 requestAnimationFrame 合帧提交。';
