import { useEffect, useMemo, useRef, useState } from 'react';
import type { DeviceCapabilities, VisionPort } from '../../shared/contracts';
import { Badge, Card } from '../../shared/ui';
import { RpsGameController } from './controller';
import { INVALID_LABELS, MOVE_LABELS, type RpsActionController, type RpsMove, type RpsScheduler, type RpsState, type RpsVisionRuntime } from './types';
import './styles.css';

const MOVE_ICONS: Record<RpsMove, string> = { rock: '●', paper: '▤', scissors: '✂' };
const outcomeLabels = { win: '你赢了', lose: '机械手赢了', draw: '平局' } as const;
const actionLabels = { disabled: '动作未接线', idle: '动作待命', authorizing: '等待本局授权', authorized: '本局已授权', dispatching: '动作请求中', executed: '动作控制器已返回执行结果', cancelled: '动作已撤销', error: '动作控制器返回错误' } as const;

export type RockPaperScissorsProps = {
  vision?: VisionPort;
  capabilities: DeviceCapabilities;
  locked: boolean;
  runtime?: RpsVisionRuntime;
  actionController?: RpsActionController;
  scheduler?: RpsScheduler;
  random?: () => number;
};

export function RockPaperScissors({ capabilities, locked, runtime, actionController, scheduler, random }: RockPaperScissorsProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [state, setState] = useState<RpsState | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const disposeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const controller = useMemo(() => runtime ? new RpsGameController({ runtime, capabilities, actionController, scheduler, random }) : null, [runtime, capabilities, actionController, scheduler, random]);

  useEffect(() => {
    if (!controller || !videoRef.current) return undefined;
    if (disposeTimerRef.current !== null) {
      clearTimeout(disposeTimerRef.current);
      disposeTimerRef.current = null;
    }
    const unsubscribe = controller.subscribe(setState);
    controller.attach(videoRef.current);
    return () => {
      unsubscribe();
      // Stop the session for both a real page leave and StrictMode's effect
      // replay, but defer permanent disposal until setup has had a chance to
      // reattach the same controller instance.
      void controller.stop('unmounted').catch(() => undefined);
      disposeTimerRef.current = setTimeout(() => {
        disposeTimerRef.current = null;
        void controller.dispose().catch(() => undefined);
      }, 0);
    };
  }, [controller]);
  useEffect(() => { if (locked) controller?.lock(); }, [locked, controller]);

  const hardwareEligible = capabilities.model === 'O6' && capabilities.supportedOperations.includes('setPosition');
  const hardwareConnected = hardwareEligible && Boolean(actionController);
  const hardwareReady = Boolean(state?.hardwareAuthorized);
  const cameraRunning = state?.cameraState === 'running';
  const canStart = Boolean(controller && cameraRunning && (state?.phase === 'cameraReady' || state?.phase === 'ready') && (!hardwareEligible || hardwareReady));
  const runAsync = (operation: () => Promise<unknown>) => {
    setActionError(null);
    void operation().catch(error => setActionError(error instanceof Error ? error.message : '猜拳操作失败，请重试。'));
  };
  const status = state?.cameraError ? `摄像头：${state.cameraError.message}` : !runtime ? '等待应用注入共享 VisionRuntime' : state?.phase === 'countdown' ? `倒计时 ${state.countdown ?? ''}` : state?.phase === 'capture' ? '请保持手势稳定' : state?.phase === 'recognized' ? '已识别，准备揭晓' : state?.phase === 'invalid' ? INVALID_LABELS[state.invalidReason ?? 'unknown'] : state?.phase === 'reveal' ? '揭晓结果' : state?.phase === 'score' ? '正在记分' : state?.phase === 'ready' ? '可以开始下一局' : cameraRunning ? '摄像头已就绪' : '请先开启摄像头';

  return <div className="stack rps-feature">
    <div className="page-heading"><div><h1>猜拳互动</h1><p className="muted">摄像头识别你的手势，机械手只在 O6 且获得本局授权后响应。</p></div><Badge tone={hardwareEligible ? 'green' : 'amber'}>{hardwareEligible ? 'O6 动作需授权' : '预览模式'}</Badge></div>
    <Card>
      <div className="rps-toolbar"><div><strong>一局流程</strong><span className="muted">开启摄像头 → 倒计时 → 稳定识别 → 揭晓与记分</span></div><span className={`rps-state rps-state-${state?.phase ?? 'idle'}`} aria-live="polite">{status}</span></div>
      <div className="rps-board">
        <div className="rps-camera-frame"><video ref={videoRef} muted playsInline aria-label="猜拳摄像头预览" /><div className={`rps-camera-placeholder ${cameraRunning ? 'is-hidden' : ''}`} aria-hidden={cameraRunning}>◎<small>{cameraRunning ? '' : '共享视觉输入'}</small></div>{state?.phase === 'countdown' && <div className="rps-countdown" aria-live="assertive">{state.countdown}</div>}</div>
        <div className="rps-panel">
          <div className="rps-status" role="status" aria-live="polite"><span className="eyebrow">识别状态</span><strong>{status}</strong>{state?.stableFrames ? <span className="muted">稳定帧 {state.stableFrames}/3</span> : null}{state && state.action.status !== 'disabled' && <span className="muted">{actionLabels[state.action.status]}{state.action.detail ? `：${state.action.detail}` : ''}</span>}</div>
          <div className="rps-results"><div><span className="muted">你的手势</span><strong>{state?.playerMove ? `${MOVE_ICONS[state.playerMove]} ${MOVE_LABELS[state.playerMove]}` : '—'}</strong></div><div><span className="muted">机械手</span><strong>{state?.machineMove ? `${MOVE_ICONS[state.machineMove]} ${MOVE_LABELS[state.machineMove]}` : '—'}</strong></div></div>
          <div className="rps-score"><span>你 <b>{state?.score.player ?? 0}</b></span><span>平局 <b>{state?.score.draws ?? 0}</b></span><span>机械手 <b>{state?.score.machine ?? 0}</b></span></div>
          {state?.outcome && <p className="rps-outcome" aria-live="assertive">{outcomeLabels[state.outcome]}</p>}
          <div className="rps-actions">
            {!cameraRunning ? <button className="button button-primary" disabled={!controller || locked} onClick={() => { if (controller) runAsync(() => controller.startCamera()); }}>开启摄像头</button> : <button className="button button-secondary" disabled={locked || state?.phase === 'countdown' || state?.phase === 'capture'} onClick={() => { if (controller) runAsync(() => controller.stop()); }}>停止摄像头</button>}
            {hardwareEligible && !hardwareReady && <button className="button button-secondary" disabled={!controller || !hardwareConnected || locked || !cameraRunning || state?.phase === 'countdown'} onClick={() => { if (controller) runAsync(() => controller.authorizeHardware()); }}>授权本局机械手</button>}
            <button className="button button-primary" disabled={!canStart || locked} onClick={() => controller?.beginRound()}>开始一局</button>
            {(state?.phase === 'invalid' || state?.phase === 'ready') && <button className="button button-ghost" disabled={locked} onClick={() => controller?.retry()}>重试</button>}
            <button className="button button-ghost" disabled={!controller || locked} onClick={() => controller?.reset()}>重置比分</button>
          </div>
          {hardwareEligible && hardwareConnected && <div className="rps-test-actions" aria-label="动作测试"><span className="muted">动作测试（不会改变比分）</span>{(['rock', 'paper', 'scissors'] as const).map(move => <button key={move} className="button button-ghost" disabled={!controller || !hardwareReady || locked || !cameraRunning || (state?.phase !== 'cameraReady' && state?.phase !== 'ready')} onClick={() => { if (controller) runAsync(() => controller.testAction(move)); }}>测试{MOVE_LABELS[move]}</button>)}</div>}
          {hardwareEligible && !hardwareConnected ? <p className="permission-note">O6 已支持动作，但动作控制器未接线；当前只能识别和记分。</p> : hardwareEligible ? <p className="permission-note">O6：点击“授权本局机械手”后，揭晓时才会向动作控制器请求回应；锁定、停止或离开页面会立即撤销。</p> : <p className="permission-note">当前型号仅进行摄像头识别与比分展示，不会下发机械手动作，也不提供动作测试。</p>}
          {!runtime && <p className="permission-note">集成提示：此页需要应用层注入同一个 VisionRuntime（owner 为 rps），页面不会自行创建摄像头或 Worker。</p>}
          {(state?.cameraError || actionError) && <div role="alert" className="permission-note">{[state?.cameraError?.message, actionError].filter((message, index, messages): message is string => Boolean(message) && messages.indexOf(message) === index).map(message => <p key={message}>{message}</p>)}<span>请检查摄像头权限、动作控制器连接后重试。</span></div>}
        </div>
      </div>
    </Card>
  </div>;
}
