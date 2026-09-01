import { useEffect, useMemo, useState } from 'react';
import type { GraspPort, TelemetryPort, TelemetrySnapshot } from '../../shared/contracts';
import { Badge, Banner, Button, Card, NumberValue } from '../../shared/ui';
import { useI18n } from '../../shared/i18n';
import './styles.css';

// ── Phase & joint state types ──

export type GraspPhase =
  | 'idle'
  | 'calibrating'
  | 'calibrated'
  | 'approaching'
  | 'closingCoarse'
  | 'closingFine'
  | 'preloading'
  | 'holding'
  | 'success'
  | 'releasing'
  | 'aborted'
  | 'failed';

export type GraspJointState =
  | 'idle'
  | 'closingCoarse'
  | 'closingFine'
  | 'contactCandidate'
  | 'contactConfirmed'
  | 'frozen'
  | 'limitReached'
  | 'error';

export interface GraspJointInfo {
  index: number;
  name: string;
  state: GraspJointState;
  contactScore: number;
  load: number;
  loadMax: number;
}

export interface GraspControllerState {
  phase: GraspPhase;
  failure?: { code: string; message: string };
  tactileAvailable: boolean;
  rawTouch?: number[] | null;
  degraded: boolean;
  calibrated: boolean;
  joints: GraspJointInfo[];
  jointCount: number;
}

export interface GraspController {
  calibrate(): Promise<void>;
  approach(): Promise<void>;
  startGrasp(presetId: string, degraded: boolean): Promise<void>;
  release(): Promise<void>;
  abort(): Promise<void>;
  getState(): Promise<GraspControllerState>;
  subscribe(listener: (state: GraspControllerState) => void): () => void;
}

// ── Joint name helpers ──

const O6_JOINT_NAMES = ['拇指弯曲', '拇指横摆', '食指弯曲', '中指弯曲', '无名指弯曲', '小指弯曲'];
function jointName(index: number, count: number): string {
  return count > 0 && index < O6_JOINT_NAMES.length ? O6_JOINT_NAMES[index] : `J${index + 1}`;
}

// ── Flow steps (6 stages, each maps to controller phases) ──

interface FlowStep {
  key: string;
  label: string;
  description: string;
  phases: GraspPhase[];
}

const FLOW_STAGES: FlowStep[] = [
  { key: 'calibrate', label: '空载标定', description: '全行程空载扫描', phases: ['calibrating', 'calibrated'] },
  { key: 'approach', label: '预抓取定位', description: '移动到预抓取姿态', phases: ['approaching'] },
  { key: 'coarse', label: '快速逼近', description: '大步长快速闭合', phases: ['closingCoarse'] },
  { key: 'fine', label: '精细逼近', description: '小步长微动接触', phases: ['closingFine'] },
  { key: 'preload', label: '预紧锁定', description: '施加预紧力锁定', phases: ['preloading'] },
  { key: 'done', label: '保持完成', description: '验证稳定，抓取成功', phases: ['holding', 'success'] },
];

const PHASE_LABEL: Record<GraspPhase, string> = {
  idle: '等待开始', calibrating: '空载标定中', calibrated: '标定完成',
  approaching: '预抓取定位', closingCoarse: '快速逼近', closingFine: '精细逼近',
  preloading: '预紧锁定', holding: '保持验证', success: '抓取成功',
  releasing: '释放中', aborted: '已中止', failed: '失败',
};

const JOINT_STATE_LABEL: Record<GraspJointState, { label: string; tone: 'blue' | 'green' | 'amber' | 'red' }> = {
  idle: { label: '待机', tone: 'blue' },
  closingCoarse: { label: '快速闭合', tone: 'blue' },
  closingFine: { label: '精细逼近', tone: 'blue' },
  contactCandidate: { label: '疑似接触', tone: 'amber' },
  contactConfirmed: { label: '已锁定', tone: 'green' },
  frozen: { label: '冻结', tone: 'blue' },
  limitReached: { label: '行程极限', tone: 'amber' },
  error: { label: '异常', tone: 'red' },
};

const JOINT_CURVE_COLORS = ['#3568f2', '#208c60', '#a9680f', '#b65144', '#7450a7', '#0f9ba8'];

// ── Default idle state ──

function idleState(jointCount: number): GraspControllerState {
  return {
    phase: 'idle',
    tactileAvailable: false,
    rawTouch: null,
    degraded: false,
    calibrated: false,
    joints: Array.from({ length: jointCount }, (_, i) => ({
      index: i,
      name: jointName(i, jointCount),
      state: 'idle' as GraspJointState,
      contactScore: 0,
      load: 0,
      loadMax: 255,
    })),
    jointCount,
  };
}

// ── Component ──

type Model = 'O6' | 'L6' | 'L7' | 'L10' | 'L20' | 'G20' | 'L21' | 'L25';
const supportedModels: Model[] = ['O6', 'L6', 'L7', 'L10', 'L20'];

export function SmartGrasp({
  grasp,
  telemetry,
  locked,
  tactileAvailable: _tactileAvailable,
  model = 'O6',
  controller,
  jointCount = 6,
  debugMode,
  isPhysicalDevice,
}: {
  grasp: GraspPort;
  telemetry?: TelemetryPort;
  locked: boolean;
  tactileAvailable: boolean;
  model?: Model;
  controller?: GraspController;
  jointCount?: number;
  debugMode?: boolean;
  isPhysicalDevice?: boolean;
}) {
  const { t, locale } = useI18n();
  const [presets, setPresets] = useState<{ id: string; name: string; description: string }[]>([]);
  const [selected, setSelected] = useState<string>();
  const [degraded] = useState(false);
  const [state, setState] = useState<GraspControllerState>(() => idleState(jointCount));
  const [error, setError] = useState<string>();
  const [liveLoads, setLiveLoads] = useState<number[]>(() => Array(jointCount).fill(0));

  const available = supportedModels.includes(model);
  const canOperate = (isPhysicalDevice ?? false) || (debugMode ?? false);

  useEffect(() => {
    void grasp.listPresets().then(setPresets).catch(() => setError('抓取预设暂时不可用，请检查运行时接线。'));
  }, [grasp]);

  useEffect(() => {
    if (!controller) { setState(idleState(jointCount)); return; }
    let mounted = true;
    void controller.getState().then(next => { if (mounted) setState(next); }).catch(() => setError('抓取控制器状态暂时不可用。'));
    const unsub = controller.subscribe(s => { if (mounted) setState(s); });
    return () => { mounted = false; unsub(); };
  }, [controller, jointCount]);

  useEffect(() => {
    if (!telemetry) return;
    const unsub = telemetry.subscribe((snapshot: TelemetrySnapshot) => {
      if (snapshot.rawCurrent && snapshot.rawCurrent.length > 0) {
        setLiveLoads(snapshot.rawCurrent.slice(0, jointCount));
      }
    });
    return unsub;
  }, [telemetry, jointCount]);

  const controllerReady = Boolean(controller);
  // 空载标定：可随时重新标定（含失败/中止后的恢复，标定会复位状态机）
  const canCalibrate = controllerReady && available && canOperate && !locked && (state.phase === 'idle' || state.phase === 'calibrated' || state.phase === 'failed' || state.phase === 'aborted');
  // 预抓取定位：必须先完成标定（会话缓存）
  const canApproach = controllerReady && available && canOperate && !locked && state.calibrated && (state.phase === 'idle' || state.phase === 'calibrated');
  // 开始抓取：首次必须标定，之后缓存标定可直接开始
  const canGrasp = controllerReady && available && canOperate && !locked && state.calibrated && Boolean(selected) && (state.phase === 'approaching' || state.phase === 'calibrated' || state.phase === 'idle');
  const isRunning = state.phase !== 'idle' && state.phase !== 'calibrated' && state.phase !== 'success' && state.phase !== 'aborted' && state.phase !== 'failed';
  const canAbort = controllerReady && canOperate && isRunning;
  // 释放 = 急停：任何运行/保持/成功/失败/中止状态均可立即回到张开姿态
  const canRelease = controllerReady && canOperate && (isRunning || state.phase === 'holding' || state.phase === 'success' || state.phase === 'failed' || state.phase === 'aborted');

  const invoke = async (operation: () => Promise<void>, failure: string) => {
    setError(undefined);
    try { await operation(); } catch { setError(failure); }
  };

  const failureMessage = state.failure?.message ?? error;

  // Determine active flow stage
  const activeStageIndex = useMemo(() => {
    if (state.phase === 'idle' || state.phase === 'aborted' || state.phase === 'failed') return -1;
    if (state.phase === 'releasing') return FLOW_STAGES.findIndex(s => s.phases.includes('approaching'));
    return FLOW_STAGES.findIndex(s => s.phases.includes(state.phase));
  }, [state.phase]);

  const displayJoints = useMemo(() => {
    return state.joints.map(j => ({
      ...j,
      load: liveLoads[j.index] ?? j.load,
    }));
  }, [state.joints, liveLoads]);

  return (
    <div className="stack smart-grasp">
      <div className="page-heading">
        <div>
          <h1>{t('grasp.title')}</h1>
          <p className="muted">{locale === 'en' ? 'Adaptive grasping uses joint load analysis for compliant contact locking.' : '自适应抓取通过关节负载分析实现柔性接触锁定。'}</p>
        </div>
        <div className="heading-actions">
          <Badge tone={!available ? 'red' : state.calibrated ? 'green' : 'amber'}>
            {!available ? `${model} 暂不可用` : state.calibrated ? '已标定 · 会话缓存' : '未标定 · 需先标定'}
          </Badge>
        </div>
      </div>

      {!state.calibrated && controllerReady && available && (
        <Banner tone="warn" className="permission-note">
          {locale === 'en' ? 'Complete no-load calibration before the first grasp. Results are cached for this session only and cleared on exit.' : '首次抓取需先完成空载标定；标定结果仅在本次会话内缓存，应用关闭后自动清除，不占用磁盘空间。'}
        </Banner>
      )}

      {!controllerReady && (
        <Banner tone="warn" className="permission-note">
          {locale === 'en' ? 'The grasp controller is not wired; calibration, approach, grasp, and abort are disabled.' : '抓取控制器尚未接线；标定、逼近、抓取和中止已禁用。'}
        </Banner>
      )}
      {controllerReady && !canOperate && (
        <Banner tone="warn" className="permission-note">
          {locale === 'en' ? 'The hand is not connected; smart grasp is unavailable.' : '未连接机械手，智能抓取不可用。'}
        </Banner>
      )}
      {!available && (
        <Banner tone="danger" className="permission-note" title={locale === 'en' ? `${model} does not support adaptive grasping.` : `${model} 不支持智能自适应抓取。`}>
          {locale === 'en' ? 'Supported models: O6, L6, L7, L10, L20.' : '当前支持 O6、L6、L7、L10、L20。'}
        </Banner>
      )}

      {/* ── Flow visualization (compact) ── */}
      <Card className="grasp-flow-card">
        <div className="card-header">
          <div>
            <h2>{t('grasp.flow.title')}</h2>
            <span className="muted">当前：{PHASE_LABEL[state.phase]}{state.calibrated ? ' · 基线已就绪' : ''}</span>
          </div>
          <div className="heading-actions">
            <Badge tone={
              state.phase === 'failed' || state.phase === 'aborted' ? 'red' :
              state.phase === 'success' || state.phase === 'holding' ? 'green' : 'blue'
            }>
              {PHASE_LABEL[state.phase]}
            </Badge>
            {canAbort && (
              <Button variant="ghost" size="sm" onClick={() => invoke(() => controller!.abort(), '中止请求失败')}>
                {t('grasp.abort')}
              </Button>
            )}
          </div>
        </div>

        <div className="grasp-flow-stages">
          {FLOW_STAGES.map((stage, i) => {
            const isCurrent = i === activeStageIndex;
            const isPast = activeStageIndex >= 0 && i < activeStageIndex;
            const isActive = isCurrent || isPast;
            return (
              <div key={stage.key} className={`grasp-flow-stage ${isActive ? 'active' : ''} ${isCurrent ? 'current' : ''} ${isPast ? 'past' : ''}`}>
                <div className="grasp-flow-stage-dot">
                  {isPast ? '\u2713' : i + 1}
                </div>
                <div className="grasp-flow-stage-text">
                  <strong>{stage.label}</strong>
                  <span>{stage.description}</span>
                </div>
                {i < FLOW_STAGES.length - 1 && (
                  <div className={`grasp-flow-stage-line ${isPast ? 'past' : ''}`} />
                )}
              </div>
            );
          })}
        </div>

        <div className="progress" style={{ marginTop: 8 }}>
          <span style={{ width: `${Math.max(3, activeStageIndex >= 0 ? ((activeStageIndex + 1) / FLOW_STAGES.length) * 100 : 0)}%` }} />
        </div>

        <div className="grid grid-4" style={{ marginTop: 10 }}>
          <Button type="button" variant="secondary" className="button-calibrate" size="sm" disabled={!canCalibrate}
            onClick={() => invoke(() => controller!.calibrate(), '标定启动失败')}>
            1. {t('grasp.calibrate')}
          </Button>
          <Button type="button" variant="secondary" className="button-approach" size="sm" disabled={!canApproach}
            onClick={() => invoke(() => controller!.approach(), '逼近启动失败')}>
            2. {t('grasp.approach')}
          </Button>
          <Button type="button" variant="primary" className="button-grasp-start" size="sm" disabled={!canGrasp || !selected}
            onClick={() => { if (!controller || !selected) return; void invoke(() => controller.startGrasp(selected, degraded), '抓取未启动'); }}>
            3. {t('grasp.start')}
          </Button>
          <Button type="button" variant="danger" className="button-release" size="sm" disabled={!canRelease}
            onClick={() => invoke(() => controller!.release(), '释放请求失败')}>
            {t('grasp.release')}
          </Button>
        </div>
        <p className="muted" style={{ marginTop: 6, fontSize: '9px' }}>
          释放为急停操作：点击后立即回到张开姿态，无需等待分步回退。
        </p>
      </Card>

      {/* ── Bottom: presets + tactile (left) | joint loads (right) ── */}
      <div className="grasp-bottom-grid">
        <div className="grasp-left-col">
          <Card className="grasp-preset-card">
            <div className="card-header">
              <div><h2>{t('grasp.presets.title')}</h2><span className="muted">{t('grasp.presets.subtitle')}</span></div>
            </div>
            {presets.length === 0 ? (
              <p className="muted" style={{ padding: '12px 0', textAlign: 'center' }}>运行时通过 GraspPort 提供预设后会显示在这里。</p>
            ) : (
              <div className="grasp-preset-grid">
                {presets.map(p => (
                  <Button type="button" key={p.id} variant="ghost" size="sm" className={`grasp-preset-btn ${selected === p.id ? 'selected' : ''}`}
                    disabled={locked || !available || !controllerReady || !canOperate}
                    onClick={() => setSelected(p.id)} aria-pressed={selected === p.id}>
                    <span className="grasp-preset-icon">{p.id.includes('soft') ? '\u25cc' : p.id.includes('cube') ? '\u25c7' : '\u2301'}</span>
                    <div className="grasp-preset-info">
                      <strong>{p.name}</strong>
                      <span>{p.description}</span>
                    </div>
                    {selected === p.id && <Badge tone="green">已选</Badge>}
                  </Button>
                ))}
              </div>
            )}
          </Card>
          <Card className="grasp-tactile-notice">
            <div className="card-header">
              <div><h2>{t('grasp.tactile.title')}</h2><span className="muted">{t('grasp.tactile.unsupported', { model })}</span></div>
              <Badge tone="amber">不可用</Badge>
            </div>
            <p className="muted" style={{ margin: '4px 0 0', fontSize: '9px' }}>自适应抓取通过关节负载（电流）分析实现接触检测，无需触觉传感器。</p>
          </Card>
        </div>

        <Card className="grasp-load-card">
          <div className="card-header">
            <div><h2>{t('grasp.load.title')}</h2><span className="muted">{t('grasp.load.raw')}</span></div>
            <Badge tone={telemetry ? 'green' : 'amber'}>{telemetry ? '实时' : '无遥测'}</Badge>
          </div>
          <div className="grasp-load-list">
            {displayJoints.map((joint, i) => (
              <div key={joint.index} className="grasp-load-row">
                <div className="grasp-load-header">
                  <span className="grasp-load-name">
                    <i style={{ background: JOINT_CURVE_COLORS[i % JOINT_CURVE_COLORS.length] }} />
                    {joint.name}
                  </span>
                  <span className="grasp-load-state">
                    <Badge tone={JOINT_STATE_LABEL[joint.state].tone}>{JOINT_STATE_LABEL[joint.state].label}</Badge>
                  </span>
                </div>
                <div className="grasp-load-bar-wrap">
                  <div className="grasp-load-bar">
                    <span className="grasp-load-fill" style={{
                      width: `${Math.min(100, (joint.load / joint.loadMax) * 100)}%`,
                      background: joint.state === 'contactConfirmed' ? 'var(--green)'
                        : joint.state === 'contactCandidate' ? 'var(--amber)'
                        : joint.state === 'error' ? 'var(--danger)'
                        : JOINT_CURVE_COLORS[i % JOINT_CURVE_COLORS.length],
                    }} />
                  </div>
                  <NumberValue value={joint.load} className="grasp-load-value telemetry-value" ariaLabel={`${joint.name} 当前负载`} />
                </div>
                {joint.contactScore > 0 && (
                  <div className="grasp-contact-score">
                    <span className="muted">接触评分</span>
                    <div className="grasp-score-bar"><span style={{ width: `${joint.contactScore * 100}%` }} /></div>
                    <span>{Math.round(joint.contactScore * 100)}%</span>
                  </div>
                )}
              </div>
            ))}
          </div>
        </Card>
      </div>

      {failureMessage && (
        <Banner tone="danger" className="lock-banner">
          <span><strong>操作未完成</strong> {failureMessage}</span>
          <Button variant="quiet" size="sm" onClick={() => setError(undefined)}>关闭</Button>
        </Banner>
      )}
    </div>
  );
}

export const README = '智能抓取：空载标定 → 快速逼近 → 精细逼近 → 锁定保持，通过关节负载分析实现自适应柔性抓取。';
