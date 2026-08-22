import { useEffect, useMemo, useRef, useState } from 'react';
import type { DeviceCapabilities, DeviceConfig, DevicePort, TelemetryPort } from '../../shared/contracts';
import { Card, Badge, Progress } from '../../shared/ui';
import { createFrameCoalescer } from '../../shared/utilities';

export function DeviceControl({ device, telemetry, config, capabilities, locked }: { device: DevicePort; telemetry: TelemetryPort; config: DeviceConfig; capabilities: DeviceCapabilities; locked: boolean }) {
  const [values, setValues] = useState<Record<string, number>>({});
  const [live, setLive] = useState({ currentMa: 620, temperatureC: 31.4 });
  const dragging = useRef(false);
  const coalescers = useRef<Record<string, ReturnType<typeof createFrameCoalescer<number>>>>({});
  useEffect(() => { void telemetry.read().then(t => { setValues(t.joints); setLive(t); }); return telemetry.subscribe(t => { if (!dragging.current) { setValues(t.joints); setLive(t); } }); }, [telemetry]);
  const joints = useMemo(() => Object.entries(values), [values]);
  const setTarget = (joint: string, value: number) => { setValues(prev => ({ ...prev, [joint]: value })); coalescers.current[joint] ||= createFrameCoalescer(v => void device.setJointTarget({ joint, value: v })); coalescers.current[joint].push(value); };
  return <div className="stack">
    <div className="page-heading"><div><p className="eyebrow">控制台 / 设备控制</p><h1>设备控制</h1><p>实时调整关节目标，观察设备状态与反馈。</p></div><div className="heading-actions"><Badge tone={locked ? 'amber' : 'green'}>{locked ? '控制已锁定' : '在线 · 12 ms'}</Badge><button className="button button-primary" disabled={locked}>回到安全位</button></div></div>
    <div className="grid grid-3"><Card className="device-summary span-2"><div className="card-header"><div><h2>{config.name}</h2><span className="muted">{config.address} · 固件模拟通道</span></div><Badge>{capabilities.model} 型号</Badge></div><div className="device-visual"><div className="arm-orb"><span>LH</span></div><div className="device-lines"><div><span>连接状态</span><strong>稳定连接</strong></div><div><span>关节数量</span><strong>{capabilities.jointCount} 个</strong></div><div><span>温度</span><strong>{live.temperatureC.toFixed(1)}°C</strong></div></div></div></Card><Card><div className="card-header"><h2>当前负载</h2><span className="muted">实时</span></div><div className="metric-xl">{live.currentMa}<small>mA</small></div><Progress value={live.currentMa / 10} /><span className="muted">峰值保护阈值 1,000 mA</span></Card></div>
    <Card><div className="card-header"><div><h2>关节目标</h2><span className="muted">拖动调整，松开或按 Enter 提交</span></div><span className="muted">单位：度</span></div><div className="joint-list">{joints.map(([joint, value]) => <label className="joint-row" key={joint}><span className="joint-name">{joint}</span><input aria-label={`${joint} 目标`} type="range" min="-90" max="90" value={value} disabled={locked} onPointerDown={() => { dragging.current = true; }} onPointerUp={() => { dragging.current = false; coalescers.current[joint]?.flush(); }} onKeyUp={event => { if (event.key === 'Enter') void device.setJointTarget({ joint, value }); }} onChange={event => setTarget(joint, Number(event.target.value))} /><output>{value}°</output></label>)}</div></Card>
  </div>;
}

export const README = '设备控制：滑块使用局部状态与 requestAnimationFrame 合帧提交。';
