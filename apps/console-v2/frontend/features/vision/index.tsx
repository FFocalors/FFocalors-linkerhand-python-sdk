import { useEffect, useMemo, useRef, useState } from 'react';
import type { DeviceCapabilities, VisionPort } from '../../shared/contracts';
import type { VisionRuntimeSnapshot } from '../../shared/vision-runtime';
import { Badge, Card, Progress } from '../../shared/ui';
import { VisionFeatureController, type VisionProposalController, type VisionRuntimeLike } from './controller';
import { DEFAULT_MAPPER_SETTINGS, type MapperSettings } from './model';

export * from './controller';
export * from './model';

export interface VisionMimicProps {
  capabilities: DeviceCapabilities;
  locked: boolean;
  runtime?: VisionRuntimeLike;
  proposalController?: VisionProposalController;
  proposalSink?: VisionProposalController;
  /** Kept for the shell contract; synchronisation uses only proposalController. */
  vision?: VisionPort;
}

function runtimeLabel(snapshot: VisionRuntimeSnapshot): string {
  const labels: Record<VisionRuntimeSnapshot['state'], string> = { idle: '未启动', loading: '正在加载模型', running: '运行中', suspended: '已暂停', stopping: '正在停止', error: '需要恢复', 'permission-denied': '摄像头权限被拒绝', 'device-lost': '摄像头已断开' };
  return labels[snapshot.state];
}

export function VisionMimic({ capabilities, locked, runtime, proposalController, proposalSink }: VisionMimicProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [advanced, setAdvanced] = useState(false);
  const [mapperSettings, setMapperSettings] = useState<MapperSettings>(DEFAULT_MAPPER_SETTINGS);
  const [controllerVersion, setControllerVersion] = useState(0);
  const [actionError, setActionError] = useState<string | null>(null);
  const disposeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const sink = proposalController ?? proposalSink;
  const controller = useMemo(() => runtime ? new VisionFeatureController(runtime, sink) : null, [runtime, sink]);

  useEffect(() => {
    if (!controller) return undefined;
    if (disposeTimerRef.current !== null) {
      clearTimeout(disposeTimerRef.current);
      disposeTimerRef.current = null;
    }
    const unsubscribe = controller.subscribe(() => setControllerVersion(version => version + 1));
    setMapperSettings(controller.mapperSettings());
    return () => {
      unsubscribe();
      // StrictMode replays effect cleanup/setup immediately. Stop is safe for
      // both the replay and a real page leave; defer permanent disposal until
      // the replay window has elapsed so the controller can be reattached.
      void controller.stop().catch(() => undefined);
      disposeTimerRef.current = setTimeout(() => {
        disposeTimerRef.current = null;
        void controller.dispose().catch(() => undefined);
      }, 0);
    };
  }, [controller]);
  useEffect(() => {
    if (!controller) return;
    controller.setModel(capabilities.model);
    controller.setLocked(locked);
  }, [controller, capabilities.model, locked]);

  const feature = controller?.snapshot();
  // This read makes state updates explicit without creating a timer or synthetic progress.
  void controllerVersion;
  const canSyncModel = capabilities.model === 'O6';
  const canStart = Boolean(controller) && !locked && feature?.runtime.state !== 'loading' && feature?.runtime.state !== 'stopping';
  const startOrStop = async () => {
    if (!controller || !videoRef.current) return;
    setActionError(null);
    try {
      if (feature?.runtime.state === 'running' || feature?.runtime.state === 'suspended') await controller.stop();
      else await controller.start(videoRef.current);
    } catch (error) {
      // The controller records the runtime failure in feature.lastError. Keep
      // an operation-level message as well for unexpected adapter failures.
      setActionError(error instanceof Error ? error.message : '视觉输入操作失败，请重试。');
    }
  };
  const runStartOrStop = () => {
    void startOrStop().catch(error => {
      setActionError(error instanceof Error ? error.message : '视觉输入操作失败，请重试。');
    });
  };
  const updateSetting = (key: keyof MapperSettings, value: number) => {
    const next = { ...mapperSettings, [key]: value };
    setMapperSettings(next);
    controller?.updateMapperSettings({ [key]: value });
  };

  return <div className="stack">
    <div className="page-heading"><div><p className="eyebrow">共享视觉 / 视觉模仿</p><h1>视觉模仿</h1><p>默认只预览；完成校准并明确允许后，才会生成 O6 动作建议。</p></div><Badge tone={canSyncModel ? 'green' : 'amber'}>{canSyncModel ? 'O6 可申请同步' : '仅预览 · 当前型号不支持同步'}</Badge></div>
    <div className="grid grid-2">
      <Card className="camera-placeholder">
        <video ref={videoRef} muted playsInline aria-label="视觉摄像头预览" style={{ width: '100%', maxHeight: 250, objectFit: 'contain', background: 'var(--camera-bg)', borderRadius: 10 }} />
        {!runtime && <p className="permission-note">视觉运行时尚未注入：当前页面仅显示配置状态，不会自行创建摄像头或 Worker。</p>}
        {runtime && <><div className="card-header" style={{ width: '100%', marginTop: 14 }}><div><h2>摄像头预览</h2><span className="muted">{feature ? runtimeLabel(feature.runtime) : '准备中'}</span></div><span className="muted">FPS {feature?.runtime.fps === null || feature?.runtime.fps === undefined ? '—' : feature.runtime.fps.toFixed(1)} · 丢帧 {feature?.runtime.droppedFrames ?? 0}</span></div><button className="button button-primary" disabled={!canStart} onClick={runStartOrStop}>{feature?.runtime.state === 'running' || feature?.runtime.state === 'suspended' ? '停止预览' : feature?.runtime.state === 'error' || feature?.runtime.state === 'device-lost' || feature?.runtime.state === 'permission-denied' ? '重新连接摄像头' : '开始预览'}</button></>}
        {(feature?.lastError || feature?.runtime.lastError || actionError) && <div role="alert" className="permission-note">{[feature?.lastError, feature?.runtime.lastError?.message, actionError].filter((message, index, messages): message is string => Boolean(message) && messages.indexOf(message) === index).map(message => <p key={message}>{message}</p>)}<span>请检查摄像头权限和视觉资源后重试。</span></div>}
      </Card>
      {!runtime && <Card><div className="card-header"><h2>动作建议</h2><button className="button button-secondary" disabled>同步动作</button></div><p className="permission-note">当前型号支持预览，但当前能力不允许同步下发动作。请注入共享 VisionRuntime 和 feature-local proposal controller 后再使用。</p></Card>}
      <Card><div className="card-header"><div><h2>张开 / 握拳校准</h2><span className="muted">本次会话有效，离开页面后清除</span></div><Badge tone={feature?.calibration.complete ? 'green' : 'amber'}>{feature?.calibration.complete ? '已完成' : feature?.calibration.phase === 'open' ? '请张开手掌' : feature?.calibration.phase === 'fist' ? '请握拳' : '未开始'}</Badge></div><p className="muted" style={{ lineHeight: 1.7 }}>保持手掌在画面中央，按提示保持姿势约三帧。校准只记录当前会话的手势范围。</p><button className="button button-secondary" disabled={!controller || feature?.runtime.state !== 'running' || locked} onClick={() => controller?.beginCalibration()}>{feature?.calibration.phase === 'idle' || feature?.calibration.phase === 'complete' ? '开始校准' : '重新校准'}</button><p className="muted" aria-live="polite">{feature?.calibration.phase === 'open' ? `张开手掌：${feature.calibration.openSamples}/3` : feature?.calibration.phase === 'fist' ? `握拳：${feature.calibration.fistSamples}/3` : feature?.calibration.complete ? '手势范围已记录，可以申请同步。' : '先开始预览，再开始校准。'}</p></Card>
    </div>
    <Card><div className="card-header"><div><h2>同步授权</h2><span className="muted">授权是一次明确的操作员确认，默认关闭</span></div><Badge tone={feature?.authorized ? 'green' : 'amber'}>{feature?.authorized ? '已允许' : '仅预览'}</Badge></div><label style={{ display: 'flex', alignItems: 'center', gap: 9, marginTop: 15, fontSize: 12 }}><input type="checkbox" checked={feature?.authorized ?? false} disabled={!controller || !canSyncModel || locked || feature?.runtime.state !== 'running' || !feature.calibration.complete} onChange={event => controller?.setAuthorized(event.target.checked)} />允许将稳定手势同步为 O6 动作建议</label>{!canSyncModel && <p className="permission-note">当前型号 {capabilities.model} 可以预览和识别手势，但同步授权控件已禁用；只有 O6 支持完整六关节 VisionPoseProposal。</p>}{canSyncModel && !feature?.authorized && <p className="permission-note">未允许同步时不会提交任何 proposal，也不会触碰设备控制。</p>}{feature?.authorized && !feature.proposalAllowed && <p className="permission-note">授权已打开，等待运行、校准和稳定置信度达到要求。</p>}</Card>
    <Card><div className="card-header"><div><h2>识别状态</h2><span className="muted">状态和结果均来自共享 VisionRuntime</span></div><span className="muted">置信度 {Math.round((feature?.confidence ?? 0) * 100)}%</span></div><div style={{ marginTop: 17 }}><Progress value={(feature?.confidence ?? 0) * 100} /><p className="muted" aria-live="polite">{feature?.gesture === 'open' ? '张开手掌' : feature?.gesture === 'fist' ? '握拳' : '等待稳定手势'} · {feature?.proposalAllowed ? '满足同步条件' : '不会下发建议'}</p></div></Card>
    <details open={advanced} onToggle={event => setAdvanced(event.currentTarget.open)}><summary className="button button-ghost" style={{ cursor: 'pointer' }}>高级映射参数（限幅 / 死区 / EMA）</summary><Card><div className="grid grid-3">{([['deadZone', '死区', 0.001, 0.2, 0.005], ['emaAlpha', 'EMA 平滑系数', 0.05, 1, 0.05], ['maxDeltaPerFrame', '单帧最大变化率', 0.01, 1, 0.01] ] as const).map(([key, label, min, max, step]) => <label key={key} style={{ display: 'grid', gap: 7, fontSize: 11 }}>{label}<input type="number" min={min} max={max} step={step} value={mapperSettings[key]} onChange={event => updateSetting(key, Number(event.target.value))} /></label>)}</div><p className="muted">输出始终为 0..1 的完整六关节向量；EMA、死区和单帧限幅仅影响建议，不改变共享视觉输入。</p></Card></details>
  </div>;
}
