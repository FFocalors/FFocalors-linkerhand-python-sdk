import { useEffect, useMemo, useRef, useState } from 'react';
import type { DeviceCapabilities, VisionPort } from '../../shared/contracts';
import type { VisionRuntimeSnapshot } from '../../shared/vision-runtime';
import { enumerateCameraDevices, readPreferredCameraDeviceId, writePreferredCameraDeviceId } from '../../shared/vision-runtime/cameras';
import type { CameraDeviceInfo } from '../../shared/vision-runtime/cameras';
import { Badge, Banner, Button, Card, Checkbox, NumberValue, Select } from '../../shared/ui';
import { useI18n } from '../../shared/i18n';
import { RpsGameController } from './controller';
import { STRATEGY_LABELS, STRATEGY_ORDER, ROUND_MODE_LABELS, ROUND_MODE_ORDER, MOVE_LABELS, MOVE_ICONS, INVALID_LABELS, type RpsActionController, type RpsMove, type RpsRoundMode, type RpsState, type RpsStrategy, type RpsVisionRuntime, type RpsScheduler } from './types';
import './styles.css';

const HAND_CONNECTIONS: [number, number][] = [
  [0,1],[1,2],[2,3],[3,4],
  [0,5],[5,6],[6,7],[7,8],
  [5,9],[9,10],[10,11],[11,12],
  [9,13],[13,14],[14,15],[15,16],
  [13,17],[17,18],[18,19],[19,20],
  [0,17],
];

function drawHandSkeleton(ctx: CanvasRenderingContext2D, landmarks: { x: number; y: number; z: number }[], width: number, height: number): void {
  ctx.clearRect(0, 0, width, height);
  if (!landmarks || landmarks.length !== 21) return;
  const lm = landmarks;

  ctx.lineWidth = 1;
  ctx.strokeStyle = 'rgba(200,200,200,0.35)';
  for (const [a, b] of HAND_CONNECTIONS) {
    ctx.beginPath();
    ctx.moveTo(lm[a].x * width, lm[a].y * height);
    ctx.lineTo(lm[b].x * width, lm[b].y * height);
    ctx.stroke();
  }

  for (const [mcp, pip, dip, tip] of [[5,6,7,8],[9,10,11,12],[13,14,15,16],[17,18,19,20]]) {
    ctx.lineWidth = 3;
    ctx.strokeStyle = '#ff9f1c';
    ctx.beginPath();
    ctx.moveTo(lm[mcp].x * width, lm[mcp].y * height);
    ctx.lineTo(lm[pip].x * width, lm[pip].y * height);
    ctx.stroke();

    ctx.strokeStyle = '#32a8ff';
    ctx.beginPath();
    ctx.moveTo(lm[pip].x * width, lm[pip].y * height);
    ctx.lineTo(lm[dip].x * width, lm[dip].y * height);
    ctx.lineTo(lm[tip].x * width, lm[tip].y * height);
    ctx.stroke();

    for (const idx of [mcp, pip, dip, tip]) {
      ctx.fillStyle = '#000';
      ctx.beginPath();
      ctx.arc(lm[idx].x * width, lm[idx].y * height, 4, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = idx === mcp || idx === pip ? '#ff9f1c' : '#32a8ff';
      ctx.beginPath();
      ctx.arc(lm[idx].x * width, lm[idx].y * height, 3, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  ctx.lineWidth = 3;
  ctx.strokeStyle = '#d946ef';
  for (const [a, b] of [[1,2],[2,3],[3,4]]) {
    ctx.beginPath();
    ctx.moveTo(lm[a].x * width, lm[a].y * height);
    ctx.lineTo(lm[b].x * width, lm[b].y * height);
    ctx.stroke();
  }
  for (const idx of [0, 1, 2, 3, 4]) {
    ctx.fillStyle = '#000';
    ctx.beginPath();
    ctx.arc(lm[idx].x * width, lm[idx].y * height, 4, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = idx === 0 ? '#ffffff' : '#d946ef';
    ctx.beginPath();
    ctx.arc(lm[idx].x * width, lm[idx].y * height, 3, 0, Math.PI * 2);
    ctx.fill();
  }
}

export type RockPaperScissorsProps = {
  vision?: VisionPort;
  capabilities: DeviceCapabilities;
  locked: boolean;
  runtime?: RpsVisionRuntime;
  actionController?: RpsActionController;
  scheduler?: RpsScheduler;
  random?: () => number;
  debugMode?: boolean;
  isPhysicalDevice?: boolean;
  preferredCameraDeviceId?: string | null;
};

function runtimeLabel(snapshot: VisionRuntimeSnapshot | undefined): string {
  const labels: Record<VisionRuntimeSnapshot['state'], string> = { idle: '未启动', loading: '正在加载模型', running: '运行中', suspended: '已暂停', stopping: '正在停止', error: '需要恢复', 'permission-denied': '摄像头权限被拒绝', 'device-lost': '摄像头已断开' };
  return labels[snapshot?.state ?? 'idle'];
}

export function RockPaperScissors({ capabilities, locked, runtime, actionController, scheduler, random, debugMode, isPhysicalDevice, preferredCameraDeviceId }: RockPaperScissorsProps) {
  const { t, locale } = useI18n();
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const [controllerVersion, setControllerVersion] = useState(0);
  const [actionError, setActionError] = useState<string | null>(null);
  const [cameras, setCameras] = useState<CameraDeviceInfo[]>([]);
  const [selectedCameraId, setSelectedCameraId] = useState<string | null>(null);
  const [showAdvanced, setShowAdvanced] = useState(false);

  const controller = useMemo(() => {
    if (!runtime) return null;
    // Type assertion needed because our runtime interface differs slightly from the legacy contract;
    // the app injects a runtime that satisfies both.
    return new RpsGameController({
      runtime: runtime as RpsGameController['runtime'],
      capabilities,
      actionController,
      scheduler,
      random,
    });
  }, [runtime, capabilities, actionController, scheduler, random]);

  useEffect(() => {
    if (!controller) return undefined;
    const unsubscribe = controller.subscribe(() => setControllerVersion(v => v + 1));
    return () => {
      unsubscribe();
      void controller.stop().catch(() => undefined);
    };
  }, [controller]);

  useEffect(() => { if (locked) controller?.lock(); }, [locked, controller]);

  useEffect(() => {
    const deviceId = preferredCameraDeviceId ?? readPreferredCameraDeviceId();
    if (deviceId) {
      try {
        setSelectedCameraId(deviceId);
      } catch {}
    }
    void enumerateCameraDevices().then(setCameras).catch(() => {});
  }, [preferredCameraDeviceId]);

  useEffect(() => {
    const stage = stageRef.current;
    const canvas = canvasRef.current;
    const video = videoRef.current;
    if (!stage || !canvas || !controller || !video) return;
    const resize = () => {
      const rect = stage.getBoundingClientRect();
      const w = Math.max(1, Math.floor(rect.width));
      const h = Math.max(1, Math.floor(rect.height));
      if (canvas.width !== w || canvas.height !== h) {
        canvas.width = w;
        canvas.height = h;
      }
    };
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(stage);
    controller.attach(video);
    return () => {
      observer.disconnect();
      controller.attach(null);
    };
  }, [controller]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !controller) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    let raf = 0;
    const render = () => {
      const state = controller.snapshot();
      const width = canvas.width;
      const height = canvas.height;
      ctx.clearRect(0, 0, width, height);
      const hand = state.lastHand;
      if (hand && hand.landmarks.length === 21) {
        drawHandSkeleton(ctx, hand.landmarks, width, height);
      } else if (state.cameraState === 'running') {
        ctx.font = '600 14px ui-monospace, SFMono-Regular, Consolas, monospace';
        ctx.fillStyle = '#f87171';
        ctx.textAlign = 'left';
        ctx.fillText('HAND: NO', 14, 26);
      } else {
        ctx.font = '600 14px ui-monospace, SFMono-Regular, Consolas, monospace';
        ctx.fillStyle = '#94a3b8';
        ctx.textAlign = 'left';
        ctx.fillText('CAMERA OFF', 14, 26);
      }
      raf = requestAnimationFrame(render);
    };
    raf = requestAnimationFrame(render);
    return () => cancelAnimationFrame(raf);
  }, [controller]);

  const hardwareEligible = capabilities.model === 'O6' && capabilities.supportedOperations.includes('setPosition');
  const hardwareConnected = hardwareEligible && Boolean(actionController) && (isPhysicalDevice ?? true);
  const hardwareReady = Boolean(controller?.snapshot().hardwareAuthorized);
  const cameraRunning = controller?.snapshot().cameraState === 'running';
  const canControl = Boolean(controller && !locked);
  const hardwareAvailable = (controller?.snapshot().action.status ?? 'disabled') !== 'disabled';
  const canStartRound = cameraRunning && (controller.snapshot().phase === 'cameraReady' || controller.snapshot().phase === 'ready');
  const phaseNow = controller?.snapshot().phase;
  const gameActive = Boolean(phaseNow && phaseNow !== 'idle' && phaseNow !== 'cameraReady');
  const runAsync = (operation: () => Promise<unknown>) => {
    setActionError(null);
    void operation().catch(error => {
      if (error instanceof DOMException && (error.name === 'NotAllowedError' || error.name === 'SecurityError')) {
        setActionError('摄像头权限被拒绝。请允许本应用访问摄像头后重试；如浏览器已记住拒绝，请在系统或浏览器设置中为本应用开启摄像头权限。');
      } else {
        setActionError(error instanceof Error ? error.message : '猜拳操作失败，请重试。');
      }
    });
  };

  const state = controller?.snapshot();
  const showMachineMove = Boolean(state && (state.phase === 'reveal' || state.phase === 'score' || state.phase === 'ready' || state.phase === 'matchOver'));
  const status = state?.cameraError ? `摄像头：${state.cameraError.message}` : !runtime ? '等待应用注入共享 VisionRuntime' : state?.phase === 'countdown' ? `倒计时 ${state.countdown ?? ''}` : state?.phase === 'capture' ? '请保持手势稳定' : state?.phase === 'recognized' ? '已识别，准备揭晓' : state?.phase === 'invalid' ? INVALID_LABELS[state.invalidReason ?? 'unknown'] : state?.phase === 'reveal' ? '揭晓结果' : state?.phase === 'score' ? '正在记分' : state?.phase === 'ready' ? '即将开始下一局' : state?.phase === 'matchOver' ? (state.matchWinner === 'player' ? '🎉 你赢得本场！' : state.matchWinner === 'machine' ? '🤖 机械手赢得本场！' : '本场结束') : cameraRunning ? '摄像头已就绪' : '请先开启摄像头';

  const strategy = state?.strategy ?? 'personalized_adaptive';
  const profile = state?.profile;
  const chain = state?.chain;
  const machineMove = state?.machineMove;
  const playerMove = state?.playerMove;
  const outcome = state?.outcome;
  const score = state?.score;
  const round = state?.round ?? 0;
  const stableFrames = state?.stableFrames ?? 0;

  const totalDecided = (score?.machine ?? 0) + (score?.player ?? 0) + (score?.draws ?? 0);
  const machineWinRate = totalDecided > 0 ? Math.round((score?.machine ?? 0) / totalDecided * 100) : 0;

  const predictionDistribution = (() => {
    if (!chain || chain.experts.length === 0) return null;
    const totals = { rock: 0, paper: 0, scissors: 0 };
    for (const expert of chain.experts) totals[expert.prediction] += expert.baseConfidence;
    const sum = totals.rock + totals.paper + totals.scissors;
    if (sum <= 0) return null;
    return {
      rock: Math.round(totals.rock / sum * 100),
      paper: Math.round(totals.paper / sum * 100),
      scissors: Math.round(totals.scissors / sum * 100),
    };
  })();

  const recentWindow = profile?.recentWindow ?? [];
  const transitionLabel = (() => {
    const last = profile?.lastHuman;
    if (!last || !profile) return '--';
    const row = profile.transitionCounts[last];
    const total = row.rock + row.paper + row.scissors;
    if (total === 0) return '--';
    const top = row.rock >= row.paper && row.rock >= row.scissors ? '石头' : row.paper >= row.rock && row.paper >= row.scissors ? '布' : '剪刀';
    return `${MOVE_LABELS[last]} 后常转 ${top}`;
  })();

  const reactionLabel = (() => {
    if (!profile) return '--';
    const loseTop = profile.afterLoseCounts.rock >= profile.afterLoseCounts.paper && profile.afterLoseCounts.rock >= profile.afterLoseCounts.scissors ? '石头' : profile.afterLoseCounts.paper >= profile.afterLoseCounts.rock && profile.afterLoseCounts.paper >= profile.afterLoseCounts.scissors ? '布' : '剪刀';
    const winTop = profile.afterWinCounts.rock >= profile.afterWinCounts.paper && profile.afterWinCounts.rock >= profile.afterWinCounts.scissors ? '石头' : profile.afterWinCounts.paper >= profile.afterWinCounts.rock && profile.afterWinCounts.paper >= profile.afterWinCounts.scissors ? '布' : '剪刀';
    const drawTop = profile.afterDrawCounts.rock >= profile.afterDrawCounts.paper && profile.afterDrawCounts.rock >= profile.afterDrawCounts.scissors ? '石头' : profile.afterDrawCounts.paper >= profile.afterDrawCounts.rock && profile.afterDrawCounts.paper >= profile.afterDrawCounts.scissors ? '布' : '剪刀';
    return `输:${loseTop} 赢:${winTop} 平:${drawTop}`;
  })();

  return (
    <div className="stack rps-feature">
      <div className="page-heading">
        <div>
          <h1>{t('rps.title')}</h1>
          <p className="muted">{locale === 'en' ? 'The left half shows camera preview and hand skeleton; the right half contains match state, strategy, and game controls.' : '左半屏为摄像头预览与手部骨架；右半屏为对局状态、策略面板与游戏控制。'}</p>
        </div>
        <Badge tone={hardwareEligible ? 'green' : 'amber'}>{hardwareEligible ? 'O6 动作需授权' : '预览模式'}</Badge>
      </div>

      <div className="rps-layout">
        {/* LEFT: preview + camera control */}
        <div className="rps-left">
          <div ref={stageRef} className="card rps-stage">
            <video ref={videoRef} muted playsInline aria-label="猜拳摄像头预览" />
            <canvas ref={canvasRef} className="rps-canvas" />
            <div className="rps-stage-overlay">
              <span>{runtimeLabel(runtime?.snapshot?.())}</span>
              {state?.phase === 'countdown' && <span className="rps-countdown" aria-live="assertive">{state.countdown}</span>}
              {state && state.phase !== 'countdown' && state.phase !== 'idle' && <span>HAND: {state.playerMove ? 'YES' : 'NO'}</span>}
            </div>
            <div className="rps-stage-status">
              {runtime ? (() => { const snap = runtime.snapshot(); return (<><span>FPS <NumberValue value={snap.fps == null ? '—' : snap.fps.toFixed(1)} className="telemetry-value" /></span><span>DROP <NumberValue value={snap.droppedFrames ?? 0} className="telemetry-value" /></span></>); })() : (<><span>FPS <NumberValue value="—" className="telemetry-value" /></span><span>DROP <NumberValue value={0} className="telemetry-value" /></span></>)}
            </div>
          </div>

          <Card>
            <div className="card-header">
              <div><h2>{t('rps.camera.title')}</h2></div>
              <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
                <Select
                  aria-label={t('rps.camera.title')}
                  value={selectedCameraId ?? ''}
                  disabled={!canControl}
                  onChange={async event => {
                    const value = event.target.value || null;
                    setSelectedCameraId(value);
                    writePreferredCameraDeviceId(value);
                    if (value && (state?.cameraState === 'running' || state?.cameraState === 'suspended')) {
                      await controller?.stop();
                      setTimeout(() => { if (controller) runAsync(() => controller.startCamera(value ?? undefined)); }, 150);
                    }
                  }}
                >
                  <option value="">{t('common.camera.autoSelect')}</option>
                  {cameras.map(cam => <option key={cam.deviceId} value={cam.deviceId}>{cam.label || cam.deviceId}</option>)}
                </Select>
                <Button variant="secondary" size="sm" disabled={!canControl} onClick={async () => { const cams = await enumerateCameraDevices(); setCameras(cams); if (!cams.length) setActionError('未发现摄像头设备'); }}>{t('common.button.refresh')}</Button>
                <Button variant="primary" size="sm" disabled={!canControl || locked} onClick={() => { if (controller) runAsync(() => (cameraRunning ? controller.stop() : controller.startCamera(selectedCameraId ?? undefined))); }}>
                  {cameraRunning ? t('common.camera.stopPreview') : state?.cameraState === 'error' || state?.cameraState === 'device-lost' || state?.cameraState === 'permission-denied' ? t('common.camera.reconnect') : t('common.camera.startPreview')}
                </Button>
              </div>
            </div>
            {(state?.cameraError || actionError) && (
              <Banner tone="danger" className="permission-note">
                {[state?.cameraError?.message, actionError].filter((m, i, arr): m is string => Boolean(m) && arr.indexOf(m) === i).map(m => <p key={m}>{m}</p>)}
                <span>{locale === 'en' ? 'Check camera permission and vision assets, then retry.' : '请检查摄像头权限和视觉资源后重试。'}</span>
              </Banner>
            )}
          </Card>
        </div>

        {/* RIGHT: controls */}
        <div className="rps-controls">
          <Card>
            <div className="card-header">
              <div><h2>{t('rps.output.title')}</h2><span className="muted">{t('rps.output.subtitle')}</span></div>
              <Badge tone={hardwareReady ? 'green' : state?.action.status === 'disabled' ? 'amber' : 'amber'}>{hardwareReady ? '已授权' : state?.action.status === 'disabled' ? '预览模式' : '未授权'}</Badge>
            </div>
            <Checkbox
              className="vision-toggle"
              aria-label={locale === 'en' ? 'Authorize hand action' : '授权机械手动作'}
              checked={hardwareReady}
              disabled={!controller || state?.action.status === 'disabled' || locked || !cameraRunning || !isPhysicalDevice}
              onChange={event => { if (controller) runAsync(() => (event.target.checked ? controller.authorizeHardware() : controller.revokeHardware())); }}
              label={hardwareReady ? (locale === 'en' ? 'The hand will mirror the move at reveal' : '揭晓后机械手将同步出拳姿态') : state?.action.status === 'disabled' ? (locale === 'en' ? 'No action controller; recognition and scoring only' : '当前无可用动作控制器，仅进行识别与记分') : (locale === 'en' ? 'Turn on to have the hand respond at reveal' : '打开后机械手将在揭晓时回应出拳')}
            />
            {debugMode && !isPhysicalDevice && <p className="permission-note">{locale === 'en' ? 'Debug mode: vision recognition is running, but no commands are sent to the hand.' : '调试模式：视觉识别正常运行，但不会下发到机械手。'}</p>}
          </Card>

          <Card>
            <div className="card-header"><div><h2>{t('rps.game.title')}</h2><span className="muted">{t('rps.game.subtitle')}</span></div></div>
            <div className="rps-field">
              <Select label="轮次预设"
                value={state?.roundMode ?? 'unlimited'}
                disabled={!controller || locked}
                onChange={event => controller?.setRoundMode(event.target.value as RpsRoundMode)}
              >
                {ROUND_MODE_ORDER.map(mode => <option key={mode} value={mode}>{ROUND_MODE_LABELS[mode]}</option>)}
              </Select>
            </div>
            <div className="rps-actions">
              {state?.phase === 'matchOver' ? (
                <Button variant="primary" size="sm" disabled={!controller || locked} onClick={() => { if (controller) controller.reset(); }}>{t('rps.game.newRound')}</Button>
              ) : (
                <Button variant="primary" size="sm" disabled={!canStartRound || locked} onClick={() => { if (controller) controller.beginRound(); }}>{t('rps.game.start')}</Button>
              )}
              {gameActive && (
                <Button variant="secondary" size="sm" disabled={locked} onClick={() => { if (controller) controller.stopRound(); }}>{t('rps.game.stop')}</Button>
              )}
              {state?.phase === 'invalid' && (
                <Button variant="ghost" size="sm" disabled={locked} onClick={() => { if (controller) controller.retry(); }}>重试</Button>
              )}
              <Button variant="ghost" size="sm" disabled={!controller || locked} onClick={() => { if (controller) controller.reset(); }}>{t('rps.game.resetScore')}</Button>
            </div>
            {state?.phase === 'matchOver' && (
              <p className="permission-note">{state.matchWinner === 'player' ? '🎉 你赢得本场！' : state.matchWinner === 'machine' ? '🤖 机械手赢得本场！' : '本场结束'} 点击“再来一局”重置比分重新开始。</p>
            )}
            <p className="permission-note">未连接机械手时同样可以完整游玩：机器按历史习惯预测并记分，仅不发送动作。</p>
            {(state?.cameraError || actionError) && (
              <div role="alert" className="permission-note">
                {[state?.cameraError?.message, actionError].filter((m, i, arr): m is string => Boolean(m) && arr.indexOf(m) === i).map(message => <p key={message}>{message}</p>)}
                <span>请检查摄像头权限、动作控制器连接后重试。</span>
              </div>
            )}
          </Card>

          <Card>
            <div className="card-header">
              <div><h2>{t('rps.match.title')}</h2><span className="muted">{t('rps.match.subtitle')}</span></div>
              <span className="muted">锁定 {stableFrames}/1</span>
            </div>
            <div className="rps-status" role="status" aria-live="polite">
              <span className="eyebrow">当前状态</span>
              <strong>{status}</strong>
              <span className="muted">{state && state.action.status !== 'disabled' ? (state.action.status === 'authorized' ? '本局已授权，揭晓后将请求机械手动作' : state.action.detail ?? '') : (hardwareEligible ? 'O6 已支持动作，但动作控制器未接线' : '当前型号仅进行摄像头识别与比分展示')}</span>
            </div>
            <div className="rps-results">
              <div>
                <span className="muted">你的手势</span>
                <strong>{playerMove ? `${MOVE_ICONS[playerMove]} ${MOVE_LABELS[playerMove]}` : '—'}</strong>
              </div>
              <div>
                <span className="muted">机械手</span>
                <strong>{showMachineMove && machineMove ? `${MOVE_ICONS[machineMove]} ${MOVE_LABELS[machineMove]}` : '—'}</strong>
              </div>
            </div>
            <div className="rps-score">
              <span>你 <b>{score?.player ?? 0}</b></span>
              <span>平局 <b>{score?.draws ?? 0}</b></span>
              <span>机械手 <b>{score?.machine ?? 0}</b></span>
            </div>
            {outcome && <p className={`rps-outcome rps-outcome-${outcome}`} aria-live="assertive">
              {outcome === 'win' ? '🎉 你赢啦！' : outcome === 'lose' ? '🤖 机械手赢啦！' : '🤝 平局，再来一轮！'}
            </p>}
          </Card>

          <Card>
            <div className="card-header">
              <div><h2>{t('rps.strategy.title')}</h2><span className="muted">{t('rps.strategy.subtitle')}</span></div>
            </div>
            <div className="rps-strategy-grid">
              <div className="rps-field">
                <Select label="当前策略"
                  value={strategy}
                  onChange={event => controller?.setStrategy(event.target.value as RpsStrategy)}
                  disabled={!controller}
                >
                  {STRATEGY_ORDER.map(mode => <option key={mode} value={mode}>{STRATEGY_LABELS[mode]}</option>)}
                </Select>
              </div>
              <div className="rps-field">
                <span className="muted">有效学习局数</span>
                <strong>{profile?.validRounds ?? 0}</strong>
              </div>
              <div className="rps-field">
                <span className="muted">当前预测</span>
                <strong>{chain ? `${MOVE_ICONS[chain.prediction]} ${MOVE_LABELS[chain.prediction]}` : '--'}</strong>
              </div>
              <div className="rps-field">
                <span className="muted">预测置信度</span>
                <strong>{chain ? `${Math.round(chain.confidence * 100)}%` : '0%'}</strong>
              </div>
              <div className="rps-field">
                <span className="muted">预测依据</span>
                <strong className="rps-reason">{chain?.reason ?? 'history_empty'}</strong>
              </div>
              <div className="rps-field">
                <span className="muted">预测概率</span>
                <strong>{predictionDistribution ? `石头${predictionDistribution.rock}% 剪刀${predictionDistribution.scissors}% 布${predictionDistribution.paper}%` : '--'}</strong>
              </div>
              <div className="rps-field">
                <span className="muted">历史偏好</span>
                <strong>{profile ? `石头${profile.humanCounts.rock} 剪刀${profile.humanCounts.scissors} 布${profile.humanCounts.paper}` : '--'}</strong>
              </div>
              <div className="rps-field">
                <span className="muted">最近窗口</span>
                <strong>{recentWindow.length ? recentWindow.map(m => MOVE_LABELS[m]).join(' → ') : '--'}</strong>
              </div>
              <div className="rps-field">
                <span className="muted">上一手转移</span>
                <strong>{transitionLabel}</strong>
              </div>
              <div className="rps-field">
                <span className="muted">输赢后习惯</span>
                <strong>{reactionLabel}</strong>
              </div>
              <div className="rps-field">
                <span className="muted">机器策略胜率</span>
                <strong>{machineWinRate}%</strong>
              </div>
            </div>
            {chain && chain.experts.length > 0 && (
              <div className="rps-experts">
                <span className="muted">活跃专家</span>
                <div className="rps-experts-list">
                  {chain.experts.map(expert => (
                    <span key={expert.name} className="rps-expert-tag" title={`${expert.detail} base=${expert.baseConfidence.toFixed(2)}`}>
                      {expert.name}: {MOVE_LABELS[expert.prediction]} ({Math.round(expert.baseConfidence * 100)}%)
                    </span>
                  ))}
                </div>
              </div>
            )}
            <div className="rps-strategy-actions">
              <Button variant="secondary" size="sm" disabled={!controller} onClick={() => controller?.resetProfile()}>重置当前玩家策略</Button>
            </div>
          </Card>

          <details open={showAdvanced} onToggle={event => setShowAdvanced(event.currentTarget.open)}>
            <summary className="button button-ghost" style={{ cursor: 'pointer' }}>专家评分详情</summary>
            <Card>
              {profile && Object.entries(profile.expertScores).map(([name, score]) => (
                <div key={name} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, padding: '2px 0' }}>
                  <span>{name}</span>
                  <span style={{ fontFamily: 'ui-monospace, SFMono-Regular, Consolas, monospace' }}>{score.toFixed(2)}</span>
                </div>
              ))}
            </Card>
          </details>

          {hardwareEligible && hardwareConnected && (
            <Card>
              <div className="card-header"><div><h2>{t('rps.actionTest.title')}</h2><span className="muted">{t('rps.actionTest.subtitle')}</span></div></div>
              <div className="rps-test-actions">
                {(['rock', 'paper', 'scissors'] as const).map(move => (
                  <Button
                    key={move}
                    variant="ghost"
                    size="sm"
                    disabled={!controller || !hardwareReady || locked || !cameraRunning || (state?.phase !== 'cameraReady' && state?.phase !== 'ready')}
                    onClick={() => { if (controller) runAsync(() => controller.testAction(move)); }}
                  >
                    测试{MOVE_LABELS[move]}
                  </Button>
                ))}
              </div>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
