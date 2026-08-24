import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ChangeEvent, KeyboardEvent, ReactNode } from 'react';
import type { ConnectionSnapshot, DeviceCapabilities, DeviceConfig, DevicePort, JointTargetCommand, OperationSnapshot, TelemetryPort, TelemetrySnapshot } from '../../shared/contracts';
import { Badge, Card } from '../../shared/ui';
import { Pencil, Trash2, X } from 'lucide-react';
import * as THREE from 'three';
import { STLLoader } from 'three/examples/jsm/loaders/STLLoader.js';
import { HAND_MODEL, O6_DRIVE_RULES, sdkNormalizedToJointAngles } from './handModel';

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
export interface DeviceControlQuickAction { id: string; label: string; detail?: string; positions?: number[]; category?: 'basic' | 'number' | 'custom'; }
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
  debugMode?: boolean;
  isPhysicalDevice?: boolean;
  customPresets?: DeviceControlQuickAction[];
  onCustomPresetsChange?: (presets: DeviceControlQuickAction[]) => void;
}

const clamp = (value: number) => Math.max(0, Math.min(1, Number.isFinite(value) ? value : 0));
export const toVector = (values: number[], length: number) => Array.from({ length }, (_, index) => clamp(values[index] ?? 0));
const connectionLabels: Record<ConnectionSnapshot['state'], string> = { disconnected: '未连接', connecting: '连接中', connected: '已连接', reconnecting: '重连中', error: '连接错误' };
function statusTone(state: ConnectionSnapshot['state']): 'blue' | 'green' | 'amber' | 'red' { if (state === 'connected') return 'green'; if (state === 'error') return 'red'; if (state === 'disconnected') return 'amber'; return 'blue'; }
function errorText(error: unknown) { if (error instanceof Error) return error.message; return typeof error === 'string' ? error : '操作未完成，请查看诊断中心。'; }

/** O6 joint display names (order must match capabilities.jointCount). Fall back to J{n} for other models. */
export const O6_JOINT_NAMES = ['大拇指弯曲', '大拇指横摆', '食指弯曲', '中指弯曲', '无名指弯曲', '小拇指弯曲'];
const CURVE_COLORS = ['#3568f2', '#208c60', '#a9680f', '#b65144', '#7450a7', '#0f9ba8'];
const CURVE_MAX_POINTS = 160;
export const O6_BASIC_ACTIONS: DeviceControlQuickAction[] = [
  { id: 'open', label: '张开', category: 'basic', positions: Array(6).fill(250 / 255) },
  { id: 'fist', label: '握拳', category: 'basic', positions: [102 / 255, 18 / 255, 0, 0, 0, 0] },
  { id: 'ok', label: 'OK', category: 'basic', positions: [96 / 255, 100 / 255, 118 / 255, 250 / 255, 250 / 255, 250 / 255] },
  { id: 'thumbs-up', label: '点赞', category: 'basic', positions: [250 / 255, 79 / 255, 0, 0, 0, 0] },
];
export const O6_NUMBER_ACTIONS: DeviceControlQuickAction[] = [
  { id: 'one', label: '壹', category: 'number', positions: [125 / 255, 18 / 255, 1, 0, 0, 0] },
  { id: 'two', label: '贰', category: 'number', positions: [92 / 255, 87 / 255, 1, 1, 0, 0] },
  { id: 'three', label: '叁', category: 'number', positions: [92 / 255, 87 / 255, 1, 1, 1, 0] },
  { id: 'four', label: '肆', category: 'number', positions: [92 / 255, 87 / 255, 1, 1, 1, 1] },
  { id: 'five', label: '伍', category: 'number', positions: Array(6).fill(1) },
];

const BASIC_ICON_PATHS: Record<string, ReactNode> = {
  open: (
    <>
      <path d="M8 13V5.5a1.5 1.5 0 0 1 3 0V12" />
      <path d="M11 12V4.5a1.5 1.5 0 0 1 3 0V12" />
      <path d="M14 12V5.5a1.5 1.5 0 0 1 3 0V13" />
      <path d="M17 13.5V9a1.5 1.5 0 0 1 3 0v6a6 6 0 0 1-6 6h-2a6 6 0 0 1-5.2-3l-2.3-4a1.5 1.5 0 0 1 2.6-1.5L8 14" />
    </>
  ),
  fist: (
    <>
      <rect x="5" y="9" width="14" height="9" rx="3" />
      <path d="M7 9V7a1.5 1.5 0 0 1 3 0v2" />
      <path d="M10 9V6.5a1.5 1.5 0 0 1 3 0V9" />
      <path d="M13 9V7a1.5 1.5 0 0 1 3 0v2" />
      <path d="M16 9V8a1.5 1.5 0 0 1 3 0v1" />
    </>
  ),
  ok: (
    <>
      <circle cx="8" cy="9" r="3" />
      <path d="M12 9V6a1.5 1.5 0 0 1 3 0v3" />
      <path d="M15 12V8a1.5 1.5 0 0 1 3 0v5a5 5 0 0 1-5 5h-2a5 5 0 0 1-4-2" />
    </>
  ),
  'thumbs-up': (
    <>
      <path d="M7 11V20h9l2.5-6a1.5 1.5 0 0 0-1.4-2H14V8a2 2 0 0 0-2-2l-2.5 6z" />
      <path d="M7 11H4v9h3" />
    </>
  ),
};

export const BasicPresetIcon = ({ type }: { type: string }) => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {BASIC_ICON_PATHS[type] ?? null}
  </svg>
);

const NUMBER_ICON_BARS: Record<string, number[]> = {
  one: [10.5],
  two: [7, 14],
  three: [4.5, 10.5, 16.5],
  four: [3, 8.2, 13.4, 18.6],
  five: [2.6, 6.8, 11, 15.2, 19.4],
};
const NUMBER_ICON_WIDTH: Record<string, number> = { one: 3, two: 3, three: 3, four: 2.4, five: 2 };

export const NumberPresetIcon = ({ id }: { id: string }) => {
  const bars = NUMBER_ICON_BARS[id] ?? [];
  const width = NUMBER_ICON_WIDTH[id] ?? 3;
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      {bars.map(x => <rect key={x} x={x} y="2" width={width} height="20" rx={width / 2} fill="currentColor" />)}
    </svg>
  );
};

function jointName(index: number, count: number): string {
  return count > 0 && index < O6_JOINT_NAMES.length ? O6_JOINT_NAMES[index] : `J${index + 1}`;
}

// ---- Three.js STL 数字孪生机械手模型 ----
type StlRig = {
  group: THREE.Group;
  pivots: Record<string, THREE.Group>;
  loaded: boolean;
};

/** 异步加载 STL 网格并按 URDF 关节层次组装场景图。 */
async function buildTwinHand(): Promise<StlRig> {
  const group = new THREE.Group();
  const loader = new STLLoader();
  const geometryMap = new Map<string, THREE.BufferGeometry>();
  await Promise.all(
    Object.entries(HAND_MODEL.links).map(([name, url]) =>
      loader.loadAsync(url).then((geometry) => {
        geometryMap.set(name, geometry);
      }).catch(() => undefined)
    )
  );

  const baseMat = new THREE.MeshStandardMaterial({ color: 0x9aa7bd, roughness: 0.55, metalness: 0.5 });
  const thumbMat = new THREE.MeshStandardMaterial({ color: 0xd0d8e8, roughness: 0.45, metalness: 0.35 });
  const fingerMat = new THREE.MeshStandardMaterial({ color: 0xdfe7f2, roughness: 0.45, metalness: 0.35 });

  const baseGeom = geometryMap.get(HAND_MODEL.baseLink);
  if (baseGeom) {
    group.add(new THREE.Mesh(baseGeom, baseMat));
  }

  const linkNode: Record<string, THREE.Object3D> = { [HAND_MODEL.baseLink]: group };
  const pivots: Record<string, THREE.Group> = {};

  for (const joint of HAND_MODEL.joints) {
    const pivot = new THREE.Group();
    pivot.name = joint.name;
    pivot.position.set(joint.origin[0], joint.origin[1], joint.origin[2]);
    pivot.rotation.set(joint.rpy[0], joint.rpy[1], joint.rpy[2], 'XYZ');
    pivot.userData.baseQuat = pivot.quaternion.clone();
    pivot.userData.axis = joint.axis.slice() as [number, number, number];

    const parent = joint.parent === HAND_MODEL.baseLink ? group : linkNode[joint.parent] ?? group;
    parent.add(pivot);

    const geom = geometryMap.get(joint.child);
    if (geom) {
      const material = joint.child.startsWith('thumb_') ? thumbMat : joint.child === HAND_MODEL.baseLink ? baseMat : fingerMat;
      pivot.add(new THREE.Mesh(geom, material));
    }

    linkNode[joint.child] = pivot;
    pivots[joint.name] = pivot;
  }

  return { group, pivots, loaded: true };
}

/** 用 SDK 归一化关节值更新 STL 机械手姿态。 */
function updateTwinHand(rig: StlRig, values: number[]): void {
  if (!rig.loaded) return;
  const angles = sdkNormalizedToJointAngles(values, O6_DRIVE_RULES, HAND_MODEL);
  const axisVec = new THREE.Vector3();
  const angleQ = new THREE.Quaternion();
  for (const [jointName, angle] of Object.entries(angles)) {
    const pivot = rig.pivots[jointName];
    if (!pivot) continue;
    const { baseQuat, axis } = pivot.userData as { baseQuat: THREE.Quaternion; axis: [number, number, number] };
    axisVec.set(axis[0], axis[1], axis[2]).normalize();
    angleQ.setFromAxisAngle(axisVec, angle);
    pivot.quaternion.copy(baseQuat.clone().multiply(angleQ));
  }
}


interface JointSliderProps {
  index: number;
  value: number;
  disabled: boolean;
  label?: string;
  onBegin: (index: number) => void;
  onInput: (index: number, value: number) => void;
  onFinish: (index: number, force?: boolean) => void;
}

/** Keeps pointer-move feedback local. The parent only receives a ref update and one RAF commit. */
export const JointSlider = memo(function JointSlider({ index, value, disabled, label, onBegin, onInput, onFinish }: JointSliderProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const outputRef = useRef<HTMLOutputElement>(null);
  const draggingRef = useRef(false);
  useEffect(() => {
    if (draggingRef.current) return;
    if (inputRef.current) inputRef.current.value = String(value);
    if (outputRef.current) outputRef.current.textContent = `${Math.round(value * 100)}%`;
  }, [value]);
  const handleChange = (event: ChangeEvent<HTMLInputElement>) => {
    const next = clamp(Number(event.currentTarget.value));
    if (inputRef.current) inputRef.current.value = String(next);
    if (outputRef.current) outputRef.current.textContent = `${Math.round(next * 100)}%`;
    onInput(index, next);
  };
  return <label className="joint-row"><span className="joint-name">{label ?? `J${index + 1}`}</span><input ref={inputRef} aria-label={`${label ?? `J${index + 1}`} 目标`} type="range" min="0" max="1" step="0.01" defaultValue={value} disabled={disabled} onPointerDown={() => { draggingRef.current = true; onBegin(index); }} onPointerUp={() => { draggingRef.current = false; onFinish(index); }} onPointerCancel={() => { draggingRef.current = false; onFinish(index); }} onBlur={() => { if (draggingRef.current) { draggingRef.current = false; onFinish(index); } }} onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); draggingRef.current = false; onFinish(index, true); } }} onChange={handleChange} /><output ref={outputRef}>{Math.round(value * 100)}%</output></label>;
});

/** Live 6-joint position curve on a canvas, styled after the legacy console waveform. */
function JointCurveChart({ telemetry, jointCount }: { telemetry?: TelemetryPort; jointCount: number }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const samplesRef = useRef<TelemetrySnapshot[]>([]);
  const rafRef = useRef<number | undefined>(undefined);
  const pausedRef = useRef(false);
  const [paused, setPaused] = useState(false);
  const [visibleJoints, setVisibleJoints] = useState<Set<number>>(() => new Set(Array.from({ length: jointCount }, (_, i) => i)));
  useEffect(() => { pausedRef.current = paused; }, [paused]);
  useEffect(() => { setVisibleJoints(new Set(Array.from({ length: jointCount }, (_, i) => i))); }, [jointCount]);

  const toggleJoint = useCallback((index: number) => {
    setVisibleJoints(prev => {
      const next = new Set(prev);
      if (next.has(index)) {
        if (next.size <= 1) return prev; // keep at least one visible
        next.delete(index);
      } else {
        next.add(index);
      }
      return next;
    });
  }, []);

  const draw = useCallback(() => {
    rafRef.current = undefined;
    const canvas = canvasRef.current;
    if (!canvas || document.visibilityState === 'hidden') return;
    const context = canvas.getContext('2d');
    if (!context) return;
    const width = canvas.clientWidth || 560;
    const height = canvas.clientHeight || 180;
    const ratio = window.devicePixelRatio || 1;
    if (canvas.width !== Math.round(width * ratio) || canvas.height !== Math.round(height * ratio)) { canvas.width = Math.round(width * ratio); canvas.height = Math.round(height * ratio); }
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    context.clearRect(0, 0, width, height);
    const tokens = getComputedStyle(canvas);
    const grid = tokens.getPropertyValue('--line').trim() || '#e2e8f0';
    const muted = tokens.getPropertyValue('--muted').trim() || '#6f7d91';
    const left = 34;
    const plotW = width - left - 8;
    const plotH = height - 28;
    const top = 8;
    context.font = '9px ui-monospace, SFMono-Regular, Consolas, monospace';
    context.lineWidth = 1;
    context.strokeStyle = grid;
    context.fillStyle = muted;
    context.textAlign = 'right';
    context.textBaseline = 'middle';
    for (let i = 0; i <= 4; i += 1) {
      const y = top + plotH * i / 4;
      context.beginPath(); context.moveTo(left, y); context.lineTo(left + plotW, y); context.stroke();
      context.fillText(String(Math.round(255 * (1 - i / 4))), left - 5, y);
    }
    context.textAlign = 'left';
    context.fillText('采样 →', left, height - 6);
    const samples = samplesRef.current;
    const count = samples.length;
    context.textAlign = 'center';
    if (count < 2) {
      context.fillStyle = muted;
      context.fillText('等待遥测…', width / 2, height / 2);
      return;
    }
    for (let j = 0; j < jointCount; j += 1) {
      if (!visibleJoints.has(j)) continue;
      context.strokeStyle = CURVE_COLORS[j % CURVE_COLORS.length];
      context.lineWidth = 1.6;
      context.beginPath();
      for (let s = 0; s < count; s += 1) {
        const v = Math.max(0, Math.min(255, samples[s].rawPosition[j] ?? 0));
        const x = left + plotW * (s / Math.max(1, count - 1));
        const y = top + plotH - v / 255 * plotH;
        if (s === 0) context.moveTo(x, y); else context.lineTo(x, y);
      }
      context.stroke();
    }
  }, [jointCount, visibleJoints]);

  const scheduleDraw = useCallback(() => {
    if (rafRef.current === undefined && document.visibilityState !== 'hidden') rafRef.current = requestAnimationFrame(draw);
  }, [draw]);

  useEffect(() => {
    if (!telemetry) return;
    const unsubscribe = telemetry.subscribe(value => {
      if (pausedRef.current) return;
      samplesRef.current.push(value);
      if (samplesRef.current.length > CURVE_MAX_POINTS) samplesRef.current.splice(0, samplesRef.current.length - CURVE_MAX_POINTS);
      scheduleDraw();
    });
    return unsubscribe;
  }, [scheduleDraw, telemetry]);
  useEffect(() => {
    const onVisibility = () => { if (document.visibilityState === 'hidden' && rafRef.current !== undefined) { cancelAnimationFrame(rafRef.current); rafRef.current = undefined; } else scheduleDraw(); };
    document.addEventListener('visibilitychange', onVisibility);
    return () => { document.removeEventListener('visibilitychange', onVisibility); if (rafRef.current !== undefined) cancelAnimationFrame(rafRef.current); };
  }, [scheduleDraw]);

  return <Card className="joint-curve-card">
    <div className="card-header"><div><h2>实时关节曲线</h2><span className="muted">最近 {CURVE_MAX_POINTS} 个采样点 · 0–255</span></div><div className="heading-actions"><Badge tone={telemetry ? 'green' : 'amber'}>{telemetry ? '实时采样' : '遥测未接入'}</Badge><button className="button button-ghost" onClick={() => { samplesRef.current = []; scheduleDraw(); }}>清空</button></div></div>
    <div className="joint-curve-legend">{Array.from({ length: jointCount }, (_, index) => <button key={index} className={`curve-legend-item ${visibleJoints.has(index) ? '' : 'curve-legend-hidden'}`} onClick={() => toggleJoint(index)} title={visibleJoints.has(index) ? `点击隐藏 ${jointName(index, jointCount)}` : `点击显示 ${jointName(index, jointCount)}`}><i style={{ background: visibleJoints.has(index) ? CURVE_COLORS[index % CURVE_COLORS.length] : 'transparent' }} />{jointName(index, jointCount)}</button>)}</div>
    <div className="joint-curve-plot"><canvas ref={canvasRef} className="joint-curve-canvas" aria-label="6 关节实时位置曲线" /></div>
  </Card>;
}

export function DeviceControl({ device, telemetry, config, capabilities, locked = false, controller, quickActions = [{ id: 'safe-position', label: '回到安全位', detail: '由设备控制器执行' }], loops = [], onNavigateToDiagnostics, debugMode, isPhysicalDevice, customPresets: customPresetsProp, onCustomPresetsChange }: DeviceControlProps) {
  const jointCount = Math.max(0, capabilities.jointCount);
  const [values, setValues] = useState<number[]>(() => Array.from({ length: jointCount }, () => 250 / 255));
  const [live, setLive] = useState<TelemetrySnapshot>();
  const [connection, setConnection] = useState<ConnectionSnapshot>({ schemaVersion: capabilities.schemaVersion, deviceId: capabilities.deviceId, state: 'disconnected', attempt: 0, lastError: null });
  const [safetyLocked, setSafetyLocked] = useState(false);
  const [busy, setBusy] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [torque, setTorque] = useState(1);
  const [operation, setOperation] = useState<OperationSnapshot>();
  const [errorMessage, setErrorMessage] = useState('');
  const [rawOpen, setRawOpen] = useState(false);
  const [submittingQuickAction, setSubmittingQuickAction] = useState<string>();
  const [submittingLoop, setSubmittingLoop] = useState<string>();
  const [customPresets, setCustomPresets] = useState<DeviceControlQuickAction[]>(() => customPresetsProp ?? []);
  const [presetName, setPresetName] = useState('');
  const [editingPresetId, setEditingPresetId] = useState<string>();
  const [editingPresetName, setEditingPresetName] = useState('');
  const valuesRef = useRef(values);
  const dragging = useRef(new Set<number>());
  useEffect(() => { if (customPresetsProp !== undefined) setCustomPresets(customPresetsProp); }, [customPresetsProp]);
  const pendingVector = useRef<number[]>(values);
  const rafRef = useRef<number | undefined>(undefined);
  const commandNumber = useRef(0);
  const connectionRef = useRef(connection);
  const lockedRef = useRef(locked || safetyLocked);
  const isLocked = locked || safetyLocked;
  const canOperate = (isPhysicalDevice ?? false) || (debugMode ?? false);
  const virtualHand = Boolean(debugMode) && !(isPhysicalDevice ?? false);
  const twinCanvasRef = useRef<HTMLCanvasElement>(null);
  const [twinReady, setTwinReady] = useState(false);
  const [autoSpinOn, setAutoSpinOn] = useState(false);
  const fittedDistRef = useRef(0);
  const centerRef = useRef(new THREE.Vector3());
  const yawRef = useRef(0);
  const tiltRef = useRef(-Math.PI / 2);
  const distanceRef = useRef(0);
  const draggingRef = useRef(false);
  const lastPointerRef = useRef<{ x: number; y: number } | null>(null);
  const twinControlsRef = useRef<{ reset(): void } | null>(null);
  const applyConnection = useCallback((snapshot: ConnectionSnapshot) => { connectionRef.current = snapshot; setConnection(snapshot); }, []);
  lockedRef.current = isLocked;

  // 数字孪生：Three.js STL 机械手随关节值（遥测或滑块）实时运动
  useEffect(() => {
    const canvas = twinCanvasRef.current;
    if (!canvas) return;
    let disposed = false;
    let raf = 0;

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(40, 1, 0.001, 10);
    camera.position.set(0, 0.02, 0.42);
    let renderer: THREE.WebGLRenderer | null = null;
    try {
      renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
      renderer.setPixelRatio(window.devicePixelRatio || 1);
      renderer.setClearColor(0x000000, 0);
    } catch (error) {
      // WebGL 不可用（如测试环境/旧浏览器）：静默降级，不阻塞页面
      renderer = null;
    }

    const resize = () => {
      if (disposed || !renderer || canvas.clientWidth === 0 || canvas.clientHeight === 0) return;
      renderer.setSize(canvas.clientWidth, canvas.clientHeight, false);
      camera.aspect = canvas.clientWidth / canvas.clientHeight;
      camera.updateProjectionMatrix();
    };
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(canvas);

    scene.add(new THREE.AmbientLight(0xffffff, 0.75));
    const key = new THREE.DirectionalLight(0xffffff, 1.1);
    key.position.set(0.6, 0.9, 0.8);
    scene.add(key);
    const fill = new THREE.DirectionalLight(0x9eb5ff, 0.45);
    fill.position.set(-0.6, -0.2, 0.4);
    scene.add(fill);

    let rig: StlRig | null = null;
    let autoSpin = false;
    let lastClickTime = 0;

    const animate = () => {
      if (disposed || !renderer) return;
      if (rig) {
        updateTwinHand(rig, valuesRef.current);
      }
      if (autoSpin && rig) {
        yawRef.current += 0.005;
        rig.group.rotation.set(tiltRef.current, yawRef.current, 0, 'YXZ');
      }
      renderer.render(scene, camera);
      raf = requestAnimationFrame(animate);
    };

    setTwinReady(false);
    void buildTwinHand().then(loadedRig => {
      if (disposed) return;
      rig = loadedRig;
      scene.add(rig.group);

      // 1) Apply the upright orientation FIRST so the bounding box matches the visible model
      yawRef.current = 0;
      tiltRef.current = -Math.PI / 2;
      rig.group.rotation.set(tiltRef.current, yawRef.current, 0, 'YXZ');

      // 2) Now compute the box over the rotated model
      const box = new THREE.Box3().setFromObject(rig.group);
      const size = box.getSize(new THREE.Vector3());
      const maxDim = Math.max(size.x, size.y, size.z);
      // 防御：若网格未加载/包围盒为空，退回已知良好的相机位置，避免 NaN
      if (!Number.isFinite(maxDim) || maxDim <= 0) {
        camera.position.set(0, 0.02, 0.42);
        camera.lookAt(0, 0.01, 0);
        centerRef.current.set(0, 0.01, 0);
        setTwinReady(true);
        return;
      }
      const center = box.getCenter(new THREE.Vector3());
      centerRef.current.copy(center);
      const fovRad = THREE.MathUtils.degToRad(40);
      const fittedDist = maxDim / (2 * Math.tan(fovRad / 2)) * 1.5;

      camera.position.set(center.x, center.y, center.z + fittedDist);
      camera.lookAt(center);

      fittedDistRef.current = fittedDist;
      distanceRef.current = fittedDist;

      twinControlsRef.current = {
        reset: () => {
          const dist = fittedDistRef.current;
          const c = centerRef.current;
          if (dist <= 0) return;
          yawRef.current = 0;
          tiltRef.current = -Math.PI / 2;
          distanceRef.current = dist;
          autoSpin = false;
          setAutoSpinOn(false);
          if (rig) {
            rig.group.rotation.set(tiltRef.current, yawRef.current, 0, 'YXZ');
          }
          camera.position.set(c.x, c.y, c.z + dist);
          camera.lookAt(c);
        },
      };
      setTwinReady(true);
    }).catch(error => {
      console.error('Failed to load STL hand model:', error);
      setTwinReady(true);
    });

    const onPointerMove = (event: PointerEvent) => {
      if (!draggingRef.current || !rig) return;
      const last = lastPointerRef.current;
      if (!last) return;
      const dx = event.clientX - last.x;
      const dy = event.clientY - last.y;
      lastPointerRef.current = { x: event.clientX, y: event.clientY };
      yawRef.current += dx * 0.01;
      tiltRef.current = Math.max(-Math.PI / 2 - 0.9, Math.min(-Math.PI / 2 + 0.9, tiltRef.current + dy * 0.01));
      rig.group.rotation.set(tiltRef.current, yawRef.current, 0, 'YXZ');
    };

    const onPointerUp = () => {
      draggingRef.current = false;
      lastPointerRef.current = null;
    };

    const onPointerCancel = () => {
      draggingRef.current = false;
      lastPointerRef.current = null;
    };

    function onWheel(event: Event) {
      if (!rig) return;
      event.preventDefault();
      const wheelEvent = event as WheelEvent;
      const fitted = fittedDistRef.current;
      if (fitted <= 0) return;
      const minDist = fitted * 0.5;
      const maxDist = fitted * 2;
      const nextDist = Math.max(minDist, Math.min(maxDist, distanceRef.current * (wheelEvent.deltaY > 0 ? 1.1 : 0.9)));
      distanceRef.current = nextDist;
      const c = centerRef.current;
      camera.position.set(c.x, c.y, c.z + nextDist);
      camera.lookAt(c);
    }

    canvas.addEventListener('pointerdown', (event: PointerEvent) => {
      if (!rig) return;
      const now = Date.now();
      const isDoubleClick = now - lastClickTime < 400;
      lastClickTime = isDoubleClick ? 0 : now;
      if (isDoubleClick) {
        autoSpin = true;
        setAutoSpinOn(true);
        draggingRef.current = false;
        lastPointerRef.current = null;
        return;
      }
      autoSpin = false;
      setAutoSpinOn(false);
      draggingRef.current = true;
      lastPointerRef.current = { x: event.clientX, y: event.clientY };
    });
    canvas.addEventListener('wheel', onWheel, { passive: false } as any);
    window.addEventListener('pointermove', onPointerMove as EventListener);
    window.addEventListener('pointerup', onPointerUp as EventListener);
    window.addEventListener('pointercancel', onPointerCancel as EventListener);

    raf = requestAnimationFrame(animate);

    return () => {
      disposed = true;
      window.removeEventListener('pointermove', onPointerMove);
      window.removeEventListener('pointerup', onPointerUp);
      window.removeEventListener('pointercancel', onPointerCancel);
      canvas.removeEventListener('wheel', onWheel, { passive: false } as any);
      cancelAnimationFrame(raf);
      observer.disconnect();
      renderer?.dispose();
      scene.traverse(obj => {
        if (obj instanceof THREE.Mesh) {
          obj.geometry.dispose();
          const material = obj.material;
          if (Array.isArray(material)) material.forEach(m => m.dispose());
          else material.dispose();
        }
      });
    };
  }, []);

  useEffect(() => { valuesRef.current = values; }, [values]);
  useEffect(() => { connectionRef.current = connection; }, [connection]);
  useEffect(() => { lockedRef.current = isLocked; }, [isLocked]);
  useEffect(() => {
    let mounted = true;
    if (virtualHand) {
      applyConnection({ schemaVersion: capabilities.schemaVersion, deviceId: 'virtual-hand', state: 'connected', attempt: 1, lastError: null });
      return () => { mounted = false; };
    }
    void device.getConnection().then(snapshot => { if (mounted) applyConnection(snapshot); }).catch(error => { if (mounted && canOperate && !debugMode) setErrorMessage('未连接机械手，无法读取连接状态。'); else if (mounted && canOperate) setErrorMessage(errorText(error)); });
    return () => { mounted = false; };
  }, [applyConnection, capabilities, device, virtualHand, debugMode, canOperate]);
  useEffect(() => {
    let mounted = true;
    const mergeTelemetry = (snapshot: TelemetrySnapshot) => { setLive(snapshot); const next = toVector(pendingVector.current, jointCount); snapshot.positions.forEach((position, index) => { if (index < jointCount && !dragging.current.has(index)) next[index] = clamp(position); }); valuesRef.current = next; pendingVector.current = next; setValues(next); };
    if (virtualHand) {
      let sequence = 0;
      const timer = window.setInterval(() => {
        if (!mounted) return;
        const values = toVector(pendingVector.current, jointCount);
        mergeTelemetry({ schemaVersion: capabilities.schemaVersion, deviceId: 'virtual-hand', sequence: ++sequence, monotonicTimeMs: performance.now(), positions: values, rawPosition: values.map(v => Math.round(v * 255)), rawCurrent: [], rawSpeed: [], rawTouch: [], connected: true });
      }, 400);
      return () => { mounted = false; clearInterval(timer); };
    }
    void telemetry.read().then(snapshot => { if (mounted) mergeTelemetry(snapshot); }).catch(error => { if (mounted && canOperate && !debugMode) setErrorMessage('未连接机械手，无法读取遥测。'); else if (mounted && canOperate) setErrorMessage(errorText(error)); });
    const unsubscribe = telemetry.subscribe(mergeTelemetry);
    return () => { mounted = false; unsubscribe(); };
  }, [jointCount, telemetry, virtualHand, capabilities, canOperate, debugMode]);
  useEffect(() => { if (!controller || virtualHand) return undefined; const unsubscribeConnection = controller.subscribeConnection(applyConnection); const unsubscribeOperation = controller.subscribeOperation?.(snapshot => setOperation(snapshot)); return () => { unsubscribeConnection(); unsubscribeOperation?.(); }; }, [applyConnection, controller, virtualHand]);
  useEffect(() => () => { if (rafRef.current !== undefined) cancelAnimationFrame(rafRef.current); }, []);

  const submitJointVector = useCallback(async (vector: number[], finalCommand: boolean) => {
    if (!controller || lockedRef.current || connectionRef.current.state !== 'connected' || !canOperate) return;
    if (virtualHand) { if (finalCommand) setErrorMessage(''); return; }
    try {
      await controller.setJointTarget({ schemaVersion: 1, commandId: `manual-${++commandNumber.current}`, source: 'manual', positions: toVector(vector, jointCount), finalCommand });
      if (finalCommand) setErrorMessage('');
    } catch (error) { setErrorMessage(`关节目标未送达：${errorText(error)}`); }
  }, [controller, jointCount, canOperate, virtualHand]);
  const commitJointFrame = useCallback((finalCommand: boolean) => { if (rafRef.current !== undefined) { cancelAnimationFrame(rafRef.current); rafRef.current = undefined; } const vector = toVector(pendingVector.current, jointCount); valuesRef.current = vector; pendingVector.current = vector; setValues(vector); void submitJointVector(vector, finalCommand); }, [jointCount, submitJointVector]);
  const scheduleJointVector = useCallback((vector: number[]) => { pendingVector.current = toVector(vector, jointCount); if (rafRef.current !== undefined) return; rafRef.current = requestAnimationFrame(() => { rafRef.current = undefined; commitJointFrame(false); }); }, [commitJointFrame, jointCount]);
  const beginJoint = (index: number) => { dragging.current.add(index); };
  const changeJoint = (index: number, value: number) => { const next = toVector(pendingVector.current, jointCount); next[index] = clamp(value); pendingVector.current = next; scheduleJointVector(next); };
  const finishJoint = (index: number, force = false) => { if (!dragging.current.has(index) && !force) return; dragging.current.delete(index); commitJointFrame(true); };
  const runController = async (action: () => Promise<void>, success?: () => void) => { setBusy(true); setErrorMessage(''); try { await action(); success?.(); } catch (error) { setErrorMessage(errorText(error)); } finally { setBusy(false); } };
  const applyPreset = async (action: DeviceControlQuickAction) => {
    if (!controller || isLocked || connection.state !== 'connected' || !canOperate) return;
    try {
      if (action.positions && action.positions.length === jointCount) {
        const vector = toVector(action.positions, jointCount);
        if (!virtualHand) await controller.setJointTarget({ schemaVersion: 1, commandId: `preset-${action.id}-${Date.now()}`, source: 'manual', positions: vector, finalCommand: true });
        // Optimistic local update so the sliders/readouts move immediately instead of waiting for telemetry round-trip.
        valuesRef.current = vector;
        pendingVector.current = vector;
        setValues(vector);
      }
      if (!virtualHand) await controller.startQuickAction(action.id);
    } catch (error) { setErrorMessage(`预设未送达：${errorText(error)}`); }
  };
  const saveCustomPreset = useCallback(() => {
    if (!presetName.trim() || !controller || isLocked || connection.state !== 'connected') return;
    const newPreset: DeviceControlQuickAction = {
      id: `custom-${Date.now()}`,
      label: presetName.trim(),
      positions: toVector(values, jointCount),
      category: 'custom',
    };
    setCustomPresets(prev => [...prev, newPreset]);
    if (onCustomPresetsChange) onCustomPresetsChange([...customPresets, newPreset]);
    setPresetName('');
  }, [presetName, controller, isLocked, connection.state, values, jointCount, customPresets, onCustomPresetsChange]);
  const startEditPreset = useCallback((preset: DeviceControlQuickAction) => {
    setEditingPresetId(preset.id);
    setEditingPresetName(preset.label);
  }, []);
  const saveEditPreset = useCallback((presetId: string) => {
    if (!editingPresetName.trim()) return;
    const next = customPresets.map(p => p.id === presetId ? { ...p, label: editingPresetName.trim(), positions: toVector(values, jointCount) } : p);
    setCustomPresets(next);
    if (onCustomPresetsChange) onCustomPresetsChange(next);
    setEditingPresetId(undefined);
    setEditingPresetName('');
  }, [editingPresetName, values, jointCount, customPresets, onCustomPresetsChange]);
  const cancelEditPreset = useCallback(() => {
    setEditingPresetId(undefined);
    setEditingPresetName('');
  }, []);
  const deletePreset = useCallback((presetId: string) => {
    if (submittingQuickAction === presetId) return;
    const next = customPresets.filter(p => p.id !== presetId);
    setCustomPresets(next);
    if (onCustomPresetsChange) onCustomPresetsChange(next);
  }, [submittingQuickAction, customPresets, onCustomPresetsChange]);
  const connect = () => { if (!controller) return; if (virtualHand) { applyConnection({ schemaVersion: capabilities.schemaVersion, deviceId: 'virtual-hand', state: 'connected', attempt: 1, lastError: null }); return; } runController(controller.connect); };
  const disconnect = () => { if (!controller) return; if (virtualHand) { applyConnection({ schemaVersion: capabilities.schemaVersion, deviceId: 'virtual-hand', state: 'disconnected', attempt: 1, lastError: null }); return; } runController(controller.disconnect); };
  const reconnect = () => { if (!controller) return; if (virtualHand) { applyConnection({ schemaVersion: capabilities.schemaVersion, deviceId: 'virtual-hand', state: 'connected', attempt: 1, lastError: null }); return; } runController(controller.reconnect); };
  const stopAll = async () => { lockedRef.current = true; if (rafRef.current !== undefined) { cancelAnimationFrame(rafRef.current); rafRef.current = undefined; } dragging.current.clear(); pendingVector.current = valuesRef.current; setSafetyLocked(true); setSubmittingQuickAction(undefined); setSubmittingLoop(undefined); setErrorMessage(''); if (virtualHand) return; try { await device.stopAll(); } catch (error) { setErrorMessage(`停止命令未送达：${errorText(error)}`); } };
  const unlock = async () => { setBusy(true); setErrorMessage(''); if (virtualHand) { setSafetyLocked(false); setBusy(false); return; } try { await device.unlock(); if (connectionRef.current.state === 'connected') setSafetyLocked(false); else setErrorMessage('设备尚未回到可控状态，保持锁定；请先连接设备。'); } catch (error) { setErrorMessage(`恢复控制未完成：${errorText(error)}`); } finally { setBusy(false); } };
  const setVectorCapability = (kind: 'speed' | 'torque', value: number) => { const length = kind === 'speed' ? capabilities.speedCommandLength : capabilities.torqueCommandLength ?? 0; if (!controller || length <= 0 || isLocked || connection.state !== 'connected' || !canOperate) return; if (virtualHand) return; const command = { values: Array.from({ length }, () => clamp(value)), finalCommand: true }; void runController(() => kind === 'speed' ? controller.setSpeed(command) : controller.setTorque(command)); };
  const operationLabel = operation?.state === 'running' ? '执行中' : operation?.state === 'completed' ? '已完成' : operation?.state === 'error' ? '失败' : operation?.state;
  const operationActive = operation?.state === 'running' || operation?.state === 'stopping' || operation?.state === 'paused';
  const operationKind = operation?.kind.toLowerCase() ?? '';
  const quickOperationActive = Boolean(operationActive && (operationKind.includes('quick') || operationKind.includes('action')));
  const loopOperationActive = Boolean(operationActive && operationKind.includes('loop'));
  const resolvedQuickActions = quickActions.length > 1 || !quickActions.find(q => q.id === 'safe-position') ? quickActions : capabilities.model === 'O6' ? [...O6_BASIC_ACTIONS, ...O6_NUMBER_ACTIONS] : quickActions;
  const singleQuickOperation = quickOperationActive && resolvedQuickActions.length === 1;
  const singleLoopOperation = loopOperationActive && loops.length === 1;
  const isQuickActionRunning = (action: DeviceControlQuickAction) => {
    if (submittingQuickAction === action.id) return true;
    if (!quickOperationActive) return false;
    if (singleQuickOperation) return true;
    return operation?.operationId === action.id;
  };
  const basicActions = resolvedQuickActions.filter(action => action.category === 'basic');
  const numberActions = resolvedQuickActions.filter(action => action.category === 'number');
  const otherQuickActions = resolvedQuickActions.filter(action => !action.category || (action.category !== 'basic' && action.category !== 'number' && action.category !== 'custom'));
  const positionTrend = live && live.positions.length > 0 ? `${Math.round(live.positions.reduce((sum, value) => sum + value, 0) / live.positions.length * 100)}% 平均目标` : '等待遥测';

  return <div className="stack device-control-page">
    <div className="page-heading"><div><h1>设备控制</h1><p className="muted">所有目标都通过设备控制器提交，硬件状态以实时遥测为准。</p></div><div className="heading-actions"><Badge tone={statusTone(connection.state)}>{connectionLabels[connection.state]}</Badge><button aria-label="设备安全锁" className={`button ${isLocked ? 'button-secondary' : 'button-primary'}`} onClick={isLocked ? unlock : stopAll} disabled={busy}>{isLocked ? '恢复控制' : '停止全部动作'}</button></div></div>
    {!controller && <div className="permission-note">未接入设备控制器：为避免伪造硬件执行，连接、关节、速度、扭矩和动作控制均已禁用。集成 runtime adapter 后可用。</div>}
    {controller && !canOperate && <div className="permission-note">未连接机械手，设备控制不可用。请在设置中连接设备，或启用调试模式以使用虚拟机械手。</div>}
    {controller && virtualHand && <div className="permission-note" role="status">调试模式：当前操作作用于虚拟调试机械手，不会发送到真实硬件。</div>}
    {errorMessage && <div className="lock-banner" role="alert"><span><strong>操作未完成</strong> {errorMessage}</span><button onClick={() => setErrorMessage('')}>关闭</button></div>}
    <div className="device-control-layout">
      <div className="device-twin-column">
        <Card className="device-twin-stage">
          <canvas ref={twinCanvasRef} className="device-twin-canvas" aria-label="数字孪生视图" />
          {!twinReady && (
            <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', pointerEvents: 'none', zIndex: 1 }}>
              <span style={{ background: 'rgba(15,23,42,0.7)', color: '#e2e8f0', padding: '6px 14px', borderRadius: 6, fontSize: 13 }}>加载模型…</span>
            </div>
          )}
          <div className="device-twin-overlay">
            <span className="device-twin-badge">DIGITAL TWIN · {config.model}</span>
          </div>
          <button
            className="device-twin-reset"
            onClick={() => twinControlsRef.current?.reset()}
            aria-label="复位视角"
            title="复位视角"
          >
            复位视角
          </button>
          {autoSpinOn && (
            <span className="device-twin-spin-badge">⟳ 自动旋转</span>
          )}
          <div className="device-twin-status">
            <span className="status-dot" />
            <span>{connectionLabels[connection.state]}</span>
            <span className="muted">·</span>
            <span>{config.name}</span>
            <span className="muted">·</span>
            <span>J{jointCount}</span>
          </div>
        </Card>
        <JointCurveChart telemetry={telemetry} jointCount={jointCount} />
      </div>
      <div className="control-panel">
        <Card>
          <div className="card-header"><div><h2>连接管理</h2><span className="muted">第 {connection.attempt} 次尝试</span></div><Badge tone={controller ? statusTone(connection.state) : 'amber'}>{controller ? connectionLabels[connection.state] : '控制器未接入'}</Badge></div>
          <div className="grid grid-3" style={{ marginTop: 10 }}>
            <button className="button button-primary" disabled={!controller || busy || connection.state === 'connected' || !canOperate} onClick={connect}>连接</button>
            <button className="button button-secondary" disabled={!controller || busy || connection.state === 'disconnected' || !canOperate} onClick={disconnect}>断开</button>
            <button className="button button-ghost" disabled={!controller || busy || !canOperate} onClick={reconnect}>重连</button>
          </div>
          {connection.lastError && <p className="permission-note" style={{ marginTop: 8 }}>{connection.lastError.message}</p>}
        </Card>
        <div className="control-twin">
          <div className="joint-target-column">
            <Card className="joint-target-card">
              <div className="card-header"><div><h2>关节目标</h2><span className="muted">归一化 · 0–100%</span></div><Badge>{jointCount} 关节</Badge></div>
              {jointCount === 0 && <p className="muted">当前能力未报告关节，控制不可用。</p>}
              <div className="joint-list joint-list-single">{Array.from({ length: jointCount }, (_, index) => <JointSlider key={index} index={index} label={jointName(index, jointCount)} value={values[index] ?? 0} disabled={!controller || isLocked || connection.state !== 'connected' || !canOperate} onBegin={beginJoint} onInput={changeJoint} onFinish={finishJoint} />)}</div>
              <details open={rawOpen} onToggle={event => setRawOpen(event.currentTarget.open)}><summary className="button button-ghost" style={{ cursor: 'pointer' }}>高级诊断：原始值估算</summary><div className="grid grid-3" style={{ marginTop: 8 }}><span className="muted">raw 估算：{values.map(value => Math.round(value * (capabilities.position.range.max - capabilities.position.range.min) + capabilities.position.range.min)).join(', ') || '—'}</span><span className="muted">范围：{capabilities.position.range.min}–{capabilities.position.range.max}</span><span className="muted">遥测 raw：{live?.rawPosition.join(', ') || '—'}</span></div></details>
            </Card>
            <div className="device-twin-readouts">
              {Array.from({ length: jointCount }, (_, index) => <div className="twin-readout" key={index}><span>{jointName(index, jointCount)}</span><strong>{live?.rawPosition[index] ?? '--'}</strong></div>)}
            </div>
          </div>
        <Card className="preset-actions-card">
          <div className="card-header"><div><h2>快捷动作</h2><span className="muted">内置预设由设备控制器执行</span></div></div>
          <div className="preset-actions-scroll">
            <div className="preset-row">
              <span className="preset-row-label">基本预设</span>
              <div className="grid grid-4">
                {basicActions.map(action => (
                  <button className="button button-preset-basic" key={action.id} disabled={!controller || isLocked || busy || !canOperate || Boolean(submittingQuickAction || submittingLoop || quickOperationActive || loopOperationActive)} onClick={() => { setSubmittingQuickAction(action.id); void applyPreset(action).finally(() => setSubmittingQuickAction(undefined)); }}>
                    <BasicPresetIcon type={action.id} />
                    {isQuickActionRunning(action) ? `${action.label} · 执行中` : action.label}
                  </button>
                ))}
              </div>
            </div>
            <div className="preset-row">
              <span className="preset-row-label">数字预设</span>
              <div className="grid grid-5">
                {numberActions.map(action => (
                  <button className="button button-preset-number" key={action.id} disabled={!controller || isLocked || busy || !canOperate || Boolean(submittingQuickAction || submittingLoop || quickOperationActive || loopOperationActive)} onClick={() => { setSubmittingQuickAction(action.id); void applyPreset(action).finally(() => setSubmittingQuickAction(undefined)); }}>
                    <NumberPresetIcon id={action.id} />
                    {isQuickActionRunning(action) ? `${action.label} · 执行中` : action.label}
                  </button>
                ))}
              </div>
            </div>
            {otherQuickActions.length > 0 && (
              <div className="preset-row">
                <span className="preset-row-label">其他动作</span>
                <div className="grid grid-3">
                  {otherQuickActions.map(action => (
                    <button className="button button-secondary" key={action.id} disabled={!controller || isLocked || busy || !canOperate || Boolean(submittingQuickAction || submittingLoop || quickOperationActive || loopOperationActive)} onClick={() => { setSubmittingQuickAction(action.id); void runController(() => controller!.startQuickAction(action.id)).finally(() => setSubmittingQuickAction(undefined)); }}>
                      {isQuickActionRunning(action) ? `${action.label} · 执行中` : action.label}
                    </button>
                  ))}
                </div>
              </div>
            )}
            <div className="preset-row">
              <span className="preset-row-label">自定义预设</span>
              <div className="custom-preset-bar">
                <input className="input" value={presetName} onChange={event => setPresetName(event.target.value)} placeholder="输入预设名称" disabled={!controller || isLocked || connection.state !== 'connected' || !canOperate} onKeyDown={event => { if (event.key === 'Enter') { event.preventDefault(); void saveCustomPreset(); } }} />
                <button className="button button-secondary" onClick={saveCustomPreset} disabled={!presetName.trim() || !controller || isLocked || connection.state !== 'connected' || !canOperate}>保存当前为预设</button>
              </div>
              {customPresets.length === 0 && <p className="muted" style={{ marginTop: 4 }}>暂无自定义预设，调整关节后点击\u201c保存当前为预设\u201d</p>}
              <div className="custom-preset-list" style={{ marginTop: 8 }}>
                {customPresets.map(preset => (
                  <div className={`custom-preset-chip ${editingPresetId === preset.id ? 'custom-preset-editing' : ''}`} key={preset.id}>
                    {editingPresetId === preset.id ? (
                      <>
                        <input
                          className="input preset-edit-input"
                          value={editingPresetName}
                          onChange={event => setEditingPresetName(event.target.value)}
                          onKeyDown={(event: KeyboardEvent<HTMLInputElement>) => {
                            if (event.key === 'Enter') { event.preventDefault(); saveEditPreset(preset.id); }
                            if (event.key === 'Escape') { event.preventDefault(); cancelEditPreset(); }
                          }}
                          autoFocus
                        />
                        <button className="icon-button preset-action-btn" onClick={() => saveEditPreset(preset.id)} title="保存" aria-label="保存"><Pencil size={12} /></button>
                        <button className="icon-button preset-action-btn" onClick={cancelEditPreset} title="取消" aria-label="取消"><X size={12} /></button>
                      </>
                    ) : (
                      <>
                        <button
                          className="button button-preset-custom"
                          disabled={!controller || isLocked || busy || !canOperate || Boolean(submittingQuickAction || submittingLoop || quickOperationActive || loopOperationActive)}
                          onClick={() => { setSubmittingQuickAction(preset.id); void applyPreset(preset).finally(() => setSubmittingQuickAction(undefined)); }}
                        >
                          {isQuickActionRunning(preset) ? `${preset.label} \u00b7 执行中` : preset.label}
                        </button>
                        <button className="icon-button preset-action-btn" onClick={() => startEditPreset(preset)} title="编辑名称并覆盖当前位置" aria-label="编辑"><Pencil size={12} /></button>
                        <button className="icon-button preset-action-btn preset-action-delete" onClick={() => deletePreset(preset.id)} title="删除预设" aria-label="删除"><Trash2 size={12} /></button>
                      </>
                    )}
                  </div>
                ))}
              </div>
            </div>
          </div>
          </Card>
        </div>
        <div className="control-strip">
          <Card>
            <div className="card-header"><div><h2>速度</h2><span className="muted">{capabilities.speed.available && capabilities.speedCommandLength > 0 ? `${capabilities.speedCommandLength} 通道` : '能力不可用'}</span></div></div>
            <div className="metric-lg" style={{ margin: '8px 0' }}>{Math.round(speed * 100)}<small>%</small></div>
            <input aria-label="速度" type="range" min="0" max="1" step="0.01" value={speed} disabled={!controller || isLocked || connection.state !== 'connected' || !capabilities.speed.available || capabilities.speedCommandLength <= 0 || !canOperate} onChange={event => setSpeed(Number(event.target.value))} onPointerUp={() => setVectorCapability('speed', speed)} onBlur={() => setVectorCapability('speed', speed)} />
            <button className="button button-ghost" style={{ marginTop: 6 }} disabled={!controller || isLocked || connection.state !== 'connected' || !capabilities.speed.available || capabilities.speedCommandLength <= 0 || !canOperate} onClick={() => setVectorCapability('speed', speed)}>应用</button>
          </Card>
          <Card>
            <div className="card-header"><div><h2>扭矩</h2><span className="muted">{capabilities.torque.available && (capabilities.torqueCommandLength ?? 0) > 0 ? `${capabilities.torqueCommandLength ?? 0} 通道` : '能力不可用'}</span></div></div>
            <div className="metric-lg" style={{ margin: '8px 0' }}>{Math.round(torque * 100)}<small>%</small></div>
            <input aria-label="扭矩" type="range" min="0" max="1" step="0.01" value={torque} disabled={!controller || isLocked || connection.state !== 'connected' || !capabilities.torque.available || (capabilities.torqueCommandLength ?? 0) <= 0 || !canOperate} onChange={event => setTorque(Number(event.target.value))} onPointerUp={() => setVectorCapability('torque', torque)} onBlur={() => setVectorCapability('torque', torque)} />
            <button className="button button-ghost" style={{ marginTop: 6 }} disabled={!controller || isLocked || connection.state !== 'connected' || !capabilities.torque.available || (capabilities.torqueCommandLength ?? 0) <= 0 || !canOperate} onClick={() => setVectorCapability('torque', torque)}>应用</button>
          </Card>
          <Card>
            <div className="card-header"><div><h2>操作</h2><span className="muted">{operationLabel ?? '等待状态'}</span></div><Badge tone={operation?.state === 'error' ? 'red' : operation?.state === 'running' ? 'blue' : 'green'}>{operationLabel ?? '空闲'}</Badge></div>
            <p className="muted" style={{ margin: '8px 0' }}>{operation?.detail ?? '等待控制器返回真实动作状态。'}</p>
            {operation && <div className="progress"><span style={{ width: `${Math.max(0, Math.min(100, operation.progress * 100))}%` }} /></div>}
            <button className="button button-ghost" style={{ marginTop: 6 }} onClick={onNavigateToDiagnostics}>诊断中心 ↗</button>
          </Card>
        </div>
      </div>
    </div>
    <p className="muted">停止全部动作是软件锁定，不是物理断电急停；危险场景请使用设备的物理急停装置。</p>
  </div>;
}

export const README = '设备控制：控制器驱动连接、动作与安全锁；关节滑块以完整归一化向量通过 requestAnimationFrame 合帧提交。';