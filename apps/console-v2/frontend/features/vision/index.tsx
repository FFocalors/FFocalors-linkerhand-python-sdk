import { useEffect, useMemo, useRef, useState } from 'react';
import type { DeviceCapabilities, VisionPort } from '../../shared/contracts';
import type { VisionRuntimeSnapshot, Landmark } from '../../shared/vision-runtime';
import type { CameraDevice } from '../settings';
import { Badge, Card, Progress } from '../../shared/ui';
import { VisionFeatureController, type VisionProposalController, type VisionRuntimeLike } from './controller';
import { DEFAULT_MAPPER_SETTINGS, type MapperSettings, mapLandmarksToO6 } from './model';

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
  debugMode?: boolean;
  isPhysicalDevice?: boolean;
  preferredCameraDeviceId?: string | null;
}

function runtimeLabel(snapshot: VisionRuntimeSnapshot | undefined): string {
  const labels: Record<VisionRuntimeSnapshot['state'], string> = { idle: '未启动', loading: '正在加载模型', running: '运行中', suspended: '已暂停', stopping: '正在停止', error: '需要恢复', 'permission-denied': '摄像头权限被拒绝', 'device-lost': '摄像头已断开' };
  return labels[snapshot?.state ?? 'idle'];
}

type RecState = 'idle' | 'recording' | 'stopped';
type PlayState = 'idle' | 'playing' | 'paused';

interface RecordedFrame {
  t: number;
  positions: number[] | null;
  landmarks: Landmark[];
  gesture: string;
  confidence: number;
}

const C11_IDX = [0, 2, 4, 5, 8, 9, 12, 13, 16, 17, 20];
const C11_COLORS = [
  '#ffffff', '#ff00ff', '#ff00ff',
  '#00ff00', '#00ff00', '#00ffff', '#00ffff',
  '#ffff00', '#ffff00', '#0080ff', '#0080ff',
];
const HAND_CONNECTIONS: [number, number][] = [
  [0,1],[1,2],[2,3],[3,4],
  [0,5],[5,6],[6,7],[7,8],
  [5,9],[9,10],[10,11],[11,12],
  [9,13],[13,14],[14,15],[15,16],
  [13,17],[17,18],[18,19],[19,20],
  [0,17],
];
const FINGER_PROXIMAL = new Set([5,6,9,10,13,14,17,18]);
const FINGER_DISTAL = new Set([7,8,11,12,15,16,19,20]);

const drawHand = (ctx: CanvasRenderingContext2D, hand: { landmarks: Landmark[]; confidence: number }, width: number, height: number) => {
  ctx.clearRect(0, 0, width, height);
  const lm = hand.landmarks;
  if (!lm || lm.length !== 21) return;

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
      ctx.fillStyle = FINGER_PROXIMAL.has(idx) ? '#ff9f1c' : '#32a8ff';
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

  for (let i = 0; i < C11_IDX.length; i++) {
    const p = lm[C11_IDX[i]];
    const x = p.x * width;
    const y = p.y * height;
    const r = i === 0 ? 7 : 5;
    ctx.fillStyle = C11_COLORS[i];
    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = '#000';
    ctx.lineWidth = 1;
    ctx.stroke();
    ctx.fillStyle = '#000';
    ctx.font = '10px ui-monospace, SFMono-Regular, Consolas, monospace';
    ctx.fillText(String(i), x + 6, y - 6);
  }

  ctx.lineWidth = 2;
  for (const [b, t] of [[1,2],[3,4],[5,6],[7,8],[9,10]]) {
    const pb = lm[C11_IDX[b]];
    const pt = lm[C11_IDX[t]];
    ctx.strokeStyle = b === 1 ? '#d946ef' : '#20e070';
    ctx.beginPath();
    ctx.moveTo(pb.x * width, pb.y * height);
    ctx.lineTo(pt.x * width, pt.y * height);
    ctx.stroke();
  }
};

export function VisionMimic({ capabilities, locked, runtime, proposalController, proposalSink, debugMode, isPhysicalDevice, preferredCameraDeviceId }: VisionMimicProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const [advanced, setAdvanced] = useState(false);
  const [mapperSettings, setMapperSettings] = useState<MapperSettings>(DEFAULT_MAPPER_SETTINGS);
  const [controllerVersion, setControllerVersion] = useState(0);
  const [actionError, setActionError] = useState<string | null>(null);

  const [recState, setRecState] = useState<RecState>('idle');
  const recordedFramesRef = useRef<RecordedFrame[]>([]);
  const recStartTimeRef = useRef<number>(0);
  const lastRecordTimeRef = useRef<number>(0);
  const lastRecordPoseRef = useRef<number[] | null>(null);
  const recFileNameRef = useRef<string>('');
  const [recTime, setRecTime] = useState(0);
  const recTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  interface SavedRecording {
    name: string;
    createdAt: string;
    duration: number;
    frames: RecordedFrame[];
  }
  const RECORDINGS_KEY = 'linkerhand-console-v2-recordings';
  const loadSavedRecordings = (): SavedRecording[] => {
    try {
      const raw = localStorage.getItem(RECORDINGS_KEY);
      return raw ? JSON.parse(raw) as SavedRecording[] : [];
    } catch { return []; }
  };
  const persistSavedRecordings = (list: SavedRecording[]) => {
    try { localStorage.setItem(RECORDINGS_KEY, JSON.stringify(list)); } catch {}
  };
  const [savedRecordings, setSavedRecordings] = useState<SavedRecording[]>([]);
  const savedRecordingsRef = useRef<SavedRecording[]>([]);
  const [activeRecordingIndex, setActiveRecordingIndex] = useState<number | null>(null);
  const [editingNameIndex, setEditingNameIndex] = useState<number | null>(null);
  const [editingName, setEditingName] = useState('');
  useEffect(() => {
    const list = loadSavedRecordings();
    savedRecordingsRef.current = list;
    setSavedRecordings(list);
  }, []);

  const [playState, setPlayState] = useState<PlayState>('idle');
  const [playSpeed, setPlaySpeed] = useState<number>(1);
  const [playLoop, setPlayLoop] = useState<boolean>(false);
  const playIdxRef = useRef<number>(0);
  const playbackFrameRef = useRef<RecordedFrame | null>(null);
  const playTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isPlayingRef = useRef(false);
  const [playInfo, setPlayInfo] = useState({ idx: 0, total: 0, percent: 0 });

  const disposeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const rafRef = useRef<number>(0);
  const canvasSizeRef = useRef({ width: 0, height: 0 });

  const [cameras, setCameras] = useState<CameraDevice[]>([]);
  const [selectedCameraId, setSelectedCameraId] = useState<string | null>(null);
  const preferredCameraIdRef = useRef<string | null>(null);

  useEffect(() => {
    const deviceId = preferredCameraDeviceId ?? localStorage.getItem('linkerhand-console-v2-camera-device-id');
    if (deviceId) {
      preferredCameraIdRef.current = deviceId;
      setSelectedCameraId(deviceId);
    }
    void enumerateCameras().then(setCameras).catch(() => {});
  }, [preferredCameraDeviceId]);

  const sink = proposalController ?? proposalSink;
  const controller = useMemo(() => runtime ? new VisionFeatureController(runtime, sink) : null, [runtime, sink]);

  useEffect(() => () => {
    if (rafRef.current) cancelAnimationFrame(rafRef.current);
    if (playTimerRef.current) clearTimeout(playTimerRef.current);
    if (disposeTimerRef.current) clearTimeout(disposeTimerRef.current);
    if (recTimerRef.current) clearInterval(recTimerRef.current);
    controller?.setPlaybackMode(false);
  }, [controller]);

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
  void controllerVersion;
  const canSyncModel = capabilities.model === 'O6';
  const canStart = Boolean(controller) && !locked && feature?.runtime.state !== 'loading' && feature?.runtime.state !== 'stopping';

  const enumerateCameras = async (): Promise<CameraDevice[]> => {
    if (!navigator.mediaDevices?.enumerateDevices) return [];
    try {
      const devices = await navigator.mediaDevices.enumerateDevices();
      return devices.filter(d => d.kind === 'videoinput').map(d => ({ deviceId: d.deviceId, label: d.label || `摄像头 ${d.deviceId.slice(0, 8)}`, kind: d.kind }));
    } catch {
      return [];
    }
  };

  const startOrStop = async () => {
    if (!controller || !videoRef.current) return;
    setActionError(null);
    try {
      if (feature?.runtime.state === 'running' || feature?.runtime.state === 'suspended') {
        await controller.stop();
        return;
      }

      let deviceId = selectedCameraId;
      if (!deviceId) {
        const cams = cameras.length ? cameras : await enumerateCameras();
        setCameras(cams);
        if (cams.length === 1) {
          deviceId = cams[0].deviceId;
          setSelectedCameraId(deviceId);
          localStorage.setItem('linkerhand-console-v2-camera-device-id', JSON.stringify(deviceId));
          preferredCameraIdRef.current = deviceId;
        } else if (cams.length > 1) {
          setActionError('检测到多个摄像头，请先在下方下拉列表选择要使用的摄像头');
          return;
        }
        // 0 个摄像头：仍尝试 getUserMedia 触发权限申请，而不是直接报错
      }

      await controller.start(videoRef.current, deviceId ?? undefined);
    } catch (error) {
      if (error instanceof DOMException && (error.name === 'NotAllowedError' || error.name === 'SecurityError')) {
        setActionError('摄像头权限被拒绝。请允许本应用访问摄像头后重试；如浏览器已记住拒绝，请在系统或浏览器设置中为本应用开启摄像头权限。');
      } else {
        setActionError(error instanceof Error ? error.message : '视觉输入操作失败，请重试。');
      }
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

  // Canvas drawing

  // Keep canvas pixel dimensions synced to the stage size
  useEffect(() => {
    const stage = stageRef.current;
    const canvas = canvasRef.current;
    if (!stage || !canvas) return;
    const resize = () => {
      const rect = stage.getBoundingClientRect();
      const w = Math.max(1, Math.floor(rect.width));
      const h = Math.max(1, Math.floor(rect.height));
      if (canvas.width !== w || canvas.height !== h) {
        canvas.width = w;
        canvas.height = h;
        canvasSizeRef.current = { width: w, height: h };
      }
    };
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(stage);
    return () => observer.disconnect();
  }, []);

  // Render loop: draw live hand or playback hand on the canvas
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const render = () => {
      const { width, height } = canvasSizeRef.current;
      if (width > 0 && height > 0) {
        ctx.clearRect(0, 0, width, height);

        const hand = feature?.lastResult?.hands[0];
        const playFrame = playbackFrameRef.current;
        const source = playFrame ?? (hand ? { landmarks: hand.landmarks, confidence: hand.confidence } : null);

        if (source) {
          drawHand(ctx, source, width, height);
        } else if (feature?.runtime.state === 'running' || feature?.runtime.state === 'suspended') {
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
      }
      rafRef.current = requestAnimationFrame(render);
    };
    rafRef.current = requestAnimationFrame(render);
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, [feature, controllerVersion]);

  // Recording timer display
  useEffect(() => {
    if (recState === 'recording') {
      recTimerRef.current = setInterval(() => {
        setRecTime(Number((performance.now() / 1000 - recStartTimeRef.current).toFixed(1)));
      }, 200);
    } else {
      if (recTimerRef.current) clearInterval(recTimerRef.current);
      recTimerRef.current = null;
    }
    return () => {
      if (recTimerRef.current) clearInterval(recTimerRef.current);
    };
  }, [recState]);

  // Record a single frame from the current vision snapshot
  const recordCurrentFrame = () => {
    if (!controller || recState !== 'recording' || playState !== 'idle') return;
    const snap = controller.snapshot();
    const hand = snap.lastResult?.hands[0];
    if (!hand) return;

    const now = performance.now() / 1000;
    if (recStartTimeRef.current === 0) {
      recStartTimeRef.current = now;
      lastRecordTimeRef.current = 0;
      lastRecordPoseRef.current = null;
    }

    const t = now - recStartTimeRef.current;
    if (now - lastRecordTimeRef.current < 0.12) return;

    let positions = snap.lastProposal?.positions ?? null;
    if (!positions && snap.calibration.complete) {
      positions = mapLandmarksToO6(hand.landmarks, snap.calibration);
    }
    if (!positions) return;

    const delta = lastRecordPoseRef.current
      ? Math.max(...positions.map((v, i) => Math.abs(v - (lastRecordPoseRef.current as number[])[i])))
      : 1;
    if (delta < 0.02 && (t - lastRecordTimeRef.current) < 0.6) return;

    recordedFramesRef.current.push({
      t: Number(t.toFixed(3)),
      positions,
      landmarks: hand.landmarks,
      gesture: snap.gesture,
      confidence: snap.confidence,
    });
    lastRecordTimeRef.current = t;
    lastRecordPoseRef.current = positions;
  };

  const startRecording = () => {
    if (!controller || playState !== 'idle') return;
    recordedFramesRef.current = [];
    recStartTimeRef.current = 0;
    lastRecordTimeRef.current = 0;
    lastRecordPoseRef.current = null;
    recFileNameRef.current = '';
    setRecTime(0);
    setRecState('recording');
  };

  const stopRecording = () => {
    if (recState !== 'recording') return;
    const frames = recordedFramesRef.current;
    if (frames.length >= 2) {
      const saved: SavedRecording = {
        name: `录制 ${new Date().toLocaleTimeString('zh-CN', { hour12: false })}`,
        createdAt: new Date().toISOString(),
        duration: frames[frames.length - 1].t,
        frames,
      };
      const next = [saved, ...savedRecordingsRef.current].slice(0, 20);
      savedRecordingsRef.current = next;
      setSavedRecordings(next);
      persistSavedRecordings(next);
      setActiveRecordingIndex(0);
    }
    setRecState('stopped');
  };

  const loadSavedRecording = (saved: SavedRecording, index: number) => {
    recordedFramesRef.current = saved.frames.map(frame => ({
      ...frame,
      positions: frame.positions ? [...frame.positions] : null,
      landmarks: frame.landmarks.map(p => ({ ...p })),
    }));
    recFileNameRef.current = saved.name;
    setRecState('stopped');
    setPlayState('idle');
    playIdxRef.current = 0;
    playbackFrameRef.current = null;
    setPlayInfo({ idx: 0, total: saved.frames.length, percent: 0 });
    setActiveRecordingIndex(index);
    setEditingNameIndex(null);
    setActionError(null);
  };

  const startRename = (index: number) => {
    setEditingNameIndex(index);
    setEditingName(savedRecordingsRef.current[index]?.name ?? '');
  };

  const confirmRename = (index: number) => {
    const name = editingName.trim();
    if (!name) return;
    const next = savedRecordingsRef.current.map((item, i) => (i === index ? { ...item, name } : item));
    savedRecordingsRef.current = next;
    setSavedRecordings(next);
    persistSavedRecordings(next);
    setEditingNameIndex(null);
    setEditingName('');
  };

  const deleteSavedRecording = (index: number) => {
    const next = savedRecordingsRef.current.filter((_, i) => i !== index);
    savedRecordingsRef.current = next;
    setSavedRecordings(next);
    persistSavedRecordings(next);
    if (activeRecordingIndex === index) setActiveRecordingIndex(null);
    else if (activeRecordingIndex !== null && activeRecordingIndex > index) setActiveRecordingIndex(activeRecordingIndex - 1);
    setEditingNameIndex(null);
  };

  const resetRecording = () => {
    recordedFramesRef.current = [];
    recStartTimeRef.current = 0;
    lastRecordTimeRef.current = 0;
    lastRecordPoseRef.current = null;
    recFileNameRef.current = '';
    setRecTime(0);
    setRecState('idle');
  };

  // Playback helpers
  const clearPlayback = () => {
    if (playTimerRef.current) clearTimeout(playTimerRef.current);
    playTimerRef.current = null;
    isPlayingRef.current = false;
    controller?.setPlaybackMode(false);
    setPlayState('idle');
    playIdxRef.current = 0;
    playbackFrameRef.current = null;
    setPlayInfo({ idx: 0, total: recordedFramesRef.current.length, percent: 0 });
  };

  const scheduleNext = (ms: number) => {
    if (playTimerRef.current) clearTimeout(playTimerRef.current);
    playTimerRef.current = setTimeout(playbackTick, ms);
  };

  const playbackTick = () => {
    if (!isPlayingRef.current) return;
    const frames = recordedFramesRef.current;
    if (!frames.length) {
      clearPlayback();
      return;
    }
    const idx = playIdxRef.current;
    if (idx >= frames.length) {
      if (playLoop) {
        playIdxRef.current = 0;
        playbackFrameRef.current = null;
        scheduleNext(0);
      } else {
        clearPlayback();
      }
      return;
    }
    const frame = frames[idx];
    if (frame.positions && proposalController) {
      proposalController.submit({
        schemaVersion: 1,
        id: `playback-${idx}`,
        label: '回放动作',
        confidence: frame.confidence,
        positions: frame.positions,
        expiresAtMonotonicMs: Date.now() + 500,
      });
    }
    playbackFrameRef.current = frame;
    const nextIdx = idx + 1;
    playIdxRef.current = nextIdx;
    setPlayInfo({ idx: nextIdx, total: frames.length, percent: Math.round((nextIdx / frames.length) * 100) });

    if (nextIdx >= frames.length) {
      if (playLoop) {
        playIdxRef.current = 0;
        playbackFrameRef.current = null;
        scheduleNext(0);
      } else {
        clearPlayback();
      }
      return;
    }

    const interval = Math.max(16, ((frames[nextIdx].t - frames[idx].t) / Math.max(0.1, playSpeed)) * 1000);
    scheduleNext(interval);
  };

  const startPlayback = async () => {
    const frames = recordedFramesRef.current;
    if (!frames.length || !proposalController) return;
    if (playState === 'playing') return;
    if (playState === 'paused') {
      if (playTimerRef.current) clearTimeout(playTimerRef.current);
      isPlayingRef.current = true;
      setPlayState('playing');
      scheduleNext(0);
      return;
    }
    if (!confirm('开始回放将暂停实时视觉同步，并将动作发送到机械手。是否继续？')) return;
    controller?.setPlaybackMode(true);
    playIdxRef.current = 0;
    playbackFrameRef.current = null;
    isPlayingRef.current = true;
    setPlayState('playing');
    setPlayInfo({ idx: 0, total: frames.length, percent: 0 });
    scheduleNext(0);
  };

  const pausePlayback = () => {
    if (playState !== 'playing') return;
    if (playTimerRef.current) clearTimeout(playTimerRef.current);
    playTimerRef.current = null;
    isPlayingRef.current = false;
    setPlayState('paused');
  };

  const stopPlayback = () => {
    if (playState === 'idle') return;
    isPlayingRef.current = false;
    clearPlayback();
  };

  // Record frame whenever controller updates during recording
  useEffect(() => {
    if (recState === 'recording') {
      recordCurrentFrame();
    }
  }, [recState, controllerVersion]);

  const isRecording = recState === 'recording';
  const hasRecording = recordedFramesRef.current.length > 0;
  const canRecord = canStart && playState === 'idle' && !isRecording;
  const canPlay = hasRecording && !isRecording;

  const hand = feature?.lastResult?.hands[0];

  return (
    <div className="stack">
      <div className="page-heading">
        <div>
          <h1>视觉模仿</h1>
          <p className="muted">左半屏为摄像头预览与手部骨架；右半屏为配置、校准、录制与回放。</p>
        </div>
        <Badge tone={canSyncModel ? 'green' : 'amber'}>{canSyncModel ? 'O6 可申请同步' : '仅预览 · 当前型号不支持同步'}</Badge>
      </div>

      <div className="vision-layout">
        {/* LEFT: preview + camera control */}
        <div className="vision-left">
          <div ref={stageRef} className="card vision-stage">
            <video ref={videoRef} muted playsInline aria-label="视觉摄像头预览" />
            <canvas ref={canvasRef} className="vision-canvas" />
            <div className="vision-stage-overlay">
              <span>{runtimeLabel(feature?.runtime)}</span>
              {isRecording && <span className="vision-recording-indicator">REC {recTime}s</span>}
              {playState !== 'idle' && <span>PLAYBACK {playInfo.idx}/{playInfo.total}</span>}
              {hand && playState === 'idle' && <span>HAND: YES · {Math.round((hand.confidence ?? 0) * 100)}%</span>}
              {!hand && (feature?.runtime.state === 'running' || feature?.runtime.state === 'suspended') && playState === 'idle' && <span>HAND: NO</span>}
            </div>
            <div className="vision-stage-status">
              <span>FPS {feature?.runtime.fps === null || feature?.runtime.fps === undefined ? '—' : feature.runtime.fps.toFixed(1)}</span>
              <span>DROP {feature?.runtime.droppedFrames ?? 0}</span>
            </div>
          </div>

          <Card>
            <div className="card-header">
              <div><h2>摄像头控制</h2></div>
              <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
                <select
                  value={selectedCameraId ?? ''}
                  disabled={!canStart}
                  onChange={async event => {
                    const value = event.target.value || null;
                    setSelectedCameraId(value);
                    localStorage.setItem('linkerhand-console-v2-camera-device-id', JSON.stringify(value));
                    preferredCameraIdRef.current = value;
                    if (value && (feature?.runtime.state === 'running' || feature?.runtime.state === 'suspended')) {
                      await controller?.stop();
                      setTimeout(() => void startOrStop(), 150);
                    }
                  }}
                  style={{ fontSize: 10 }}
                >
                  <option value="">自动选择摄像头</option>
                  {cameras.map(cam => <option key={cam.deviceId} value={cam.deviceId}>{cam.label || cam.deviceId}</option>)}
                </select>
                <button className="button button-secondary" disabled={!canStart} onClick={async () => { const cams = await enumerateCameras(); setCameras(cams); if (!cams.length) setActionError('未发现摄像头设备'); }}>刷新</button>
                <button className="button button-primary" disabled={!canStart} onClick={runStartOrStop}>
                  {feature?.runtime.state === 'running' || feature?.runtime.state === 'suspended' ? '停止预览' : feature?.runtime.state === 'error' || feature?.runtime.state === 'device-lost' || feature?.runtime.state === 'permission-denied' ? '重新连接摄像头' : '开始预览'}
                </button>
              </div>
            </div>
            {(feature?.lastError || feature?.runtime.lastError || actionError) && (
              <div role="alert" className="permission-note">
                {[feature?.lastError, feature?.runtime.lastError?.message, actionError].filter((m, i, arr): m is string => Boolean(m) && arr.indexOf(m) === i).map(m => <p key={m}>{m}</p>)}
                <span>请检查摄像头权限和视觉资源后重试。</span>
              </div>
            )}
          </Card>
        </div>

        {/* RIGHT: controls */}
        <div className="vision-controls">
          <Card>
            <div className="card-header">
              <div><h2>下发到机械手</h2><span className="muted">开启后实时将手部动作同步到 O6</span></div>
              <Badge tone={feature?.authorized ? 'green' : 'amber'}>{feature?.authorized ? '同步中' : '已关闭'}</Badge>
            </div>
            <label className="vision-toggle" style={{ marginTop: 10 }}>
              <input type="checkbox" checked={feature?.authorized ?? false} disabled={!controller || !canSyncModel || locked || feature?.runtime.state !== 'running' || !isPhysicalDevice} onChange={event => controller?.setAuthorized(event.target.checked)} />
              <span className="toggle-track"><span className="toggle-thumb" /></span>
              {feature?.authorized ? '正在将手部动作同步到机械手' : '打开后开始同步手部动作到机械手'}
            </label>
            {!canSyncModel && <p className="permission-note">当前型号 {capabilities.model} 可以预览和识别手势，但同步授权控件已禁用；只有 O6 支持完整六关节 VisionPoseProposal。</p>}
            {canSyncModel && !feature?.authorized && <p className="permission-note">开关关闭时仅进行识别预览，不会向机械手发送任何动作。</p>}
            {feature?.authorized && !feature.proposalAllowed && <p className="permission-note">开关已打开，等待运行和稳定置信度达到要求。</p>}
            {debugMode && !isPhysicalDevice && <p className="permission-note">调试模式：视觉识别正常运行，但不会下发到机械手。</p>}
          </Card>

          <Card>
            <div className="card-header">
              <div><h2>范围校准（可选）</h2><span className="muted">用于归一化张开/握拳区间；不校准也能直接同步连续姿态</span></div>
              <Badge tone={feature?.calibration.complete ? 'green' : 'amber'}>{feature?.calibration.complete ? '已完成' : feature?.calibration.phase === 'open' ? '请张开手掌' : feature?.calibration.phase === 'fist' ? '请握拳' : '未开始'}</Badge>
            </div>
            <p className="muted" style={{ lineHeight: 1.6 }}>保持手掌在画面中央，按当前提示保持姿势。每 0.5 秒自动采集一帧，共需 3 帧。校准会让张开/握拳的映射更贴合你的手部范围。</p>
            <button className="button button-secondary" disabled={!controller || feature?.runtime.state !== 'running' || locked} onClick={() => controller?.beginCalibration()}>{feature?.calibration.phase === 'idle' || feature?.calibration.phase === 'complete' ? '开始校准' : '重新校准'}</button>
            <p className="muted" aria-live="polite">{feature?.calibration.phase === 'open' ? `张开手掌：${feature.calibration.openSamples}/3` : feature?.calibration.phase === 'fist' ? `握拳：${feature.calibration.fistSamples}/3` : feature?.calibration.complete ? '手势范围已记录。' : '不校准也能直接同步连续姿态。'}</p>
            {feature?.calibration.complete && (() => {
              const names = ['拇指弯','拇指摆','食指','中指','无名','小指'];
              const openPose = feature.calibration.openPose ?? feature.lastPositions;
              const fistPose = feature.calibration.fistPose ?? feature.lastPositions;
              return (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 4, marginTop: 8 }}>
                  <div style={{ fontSize: 9, color: 'var(--muted)' }}>完全张开</div>
                  <div style={{ fontSize: 9, color: 'var(--muted)' }}>完全闭合</div>
                  <div style={{ fontSize: 9, color: 'var(--muted)' }}>关节</div>
                  {(openPose ?? []).map((value, index) => (
                    <div key={index} style={{ display: 'contents' }}>
                      <span style={{ fontFamily: 'ui-monospace, SFMono-Regular, Consolas, monospace', fontSize: 10 }}>{(Array.isArray(openPose) ? openPose[index] : 0).toFixed(2)}</span>
                      <span style={{ fontFamily: 'ui-monospace, SFMono-Regular, Consolas, monospace', fontSize: 10 }}>{(Array.isArray(fistPose) ? fistPose[index] : 0).toFixed(2)}</span>
                      <span style={{ color: 'var(--muted)', fontSize: 10 }}>{names[index]}</span>
                    </div>
                  ))}
                </div>
              );
            })()}
          </Card>

          <Card>
            <div className="card-header">
              <div><h2>识别状态</h2><span className="muted">21 点连续映射 · O6 六关节</span></div>
              <span className="muted">置信度 {Math.round((feature?.confidence ?? 0) * 100)}%</span>
            </div>
            <div style={{ marginTop: 10 }}>
              <Progress value={(feature?.confidence ?? 0) * 100} />
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 4, marginTop: 8 }}>
                {(feature?.lastPositions ?? [0,0,0,0,0,0]).map((value, index) => (
                  <div key={index} style={{ fontSize: 10, display: 'flex', justifyContent: 'space-between' }}>
                    <span style={{ color: 'var(--muted)' }}>{['拇指弯','拇指摆','食指','中指','无名','小指'][index]}</span>
                    <span style={{ fontFamily: 'ui-monospace, SFMono-Regular, Consolas, monospace' }}>{value.toFixed(2)}</span>
                  </div>
                ))}
              </div>
              <p className="muted" aria-live="polite">{feature?.proposalAllowed ? '满足同步条件' : '不会下发建议'}</p>
            </div>
          </Card>

          <details open={advanced} onToggle={event => setAdvanced(event.currentTarget.open)}>
            <summary className="button button-ghost" style={{ cursor: 'pointer' }}>高级映射参数（限幅 / 死区 / EMA）</summary>
            <Card>
              <div className="grid grid-3">
                {([['deadZone', '死区', 0.001, 0.2, 0.005], ['emaAlpha', 'EMA 平滑系数', 0.05, 1, 0.05], ['maxDeltaPerFrame', '单帧最大变化率', 0.01, 1, 0.01]] as const).map(([key, label, min, max, step]) => (
                  <label key={key} style={{ display: 'grid', gap: 5, fontSize: 10 }}>
                    {label}
                    <input type="number" min={min} max={max} step={step} value={mapperSettings[key]} onChange={event => updateSetting(key, Number(event.target.value))} />
                  </label>
                ))}
              </div>
              <p className="muted">输出始终为 0..1 的完整六关节向量；EMA、死区和单帧限幅仅影响建议，不改变共享视觉输入。</p>
            </Card>
          </details>

          <Card>
            <div className="card-header"><div><h2>动作录制</h2></div></div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 6, marginBottom: 8 }}>
              <button className="button button-secondary" disabled={!canRecord} onClick={startRecording}>{isRecording ? '录制中...' : '开始录制'}</button>
              <button className="button button-secondary" disabled={recState !== 'recording'} onClick={stopRecording}>停止录制</button>
              <button className="button button-secondary" disabled={recState === 'idle'} onClick={resetRecording}>清空录制</button>
            </div>
            <p className="muted" style={{ marginTop: 6 }}>
              {recState === 'recording' ? `正在录制 · 已记录 ${recordedFramesRef.current.length} 帧` : recState === 'stopped' ? `已停止 · ${recordedFramesRef.current.length} 帧 · ${recordedFramesRef.current[recordedFramesRef.current.length - 1]?.t?.toFixed(2) || 0}s` : '未录制'}
            </p>
            {savedRecordings.length > 0 && (
              <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 6 }}>
                <div style={{ fontSize: 9, color: 'var(--muted)', fontWeight: 700 }}>已保存录制</div>
                {savedRecordings.map((saved, index) => {
                  const active = activeRecordingIndex === index;
                  return (
                    <div key={`${saved.createdAt}-${index}`} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '6px 8px', border: `1px solid ${active ? 'var(--green)' : 'var(--line)'}`, borderRadius: 6, background: active ? 'var(--green-soft)' : 'var(--surface-2)' }}>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        {editingNameIndex === index ? (
                          <input
                            autoFocus
                            value={editingName}
                            onChange={e => setEditingName(e.target.value)}
                            onBlur={() => confirmRename(index)}
                            onKeyDown={e => { if (e.key === 'Enter') confirmRename(index); if (e.key === 'Escape') setEditingNameIndex(null); }}
                            style={{ width: '100%', fontSize: 10, padding: '2px 6px', border: '1px solid var(--blue)', borderRadius: 4, background: 'var(--surface)', color: 'var(--text)' }}
                          />
                        ) : (
                          <div style={{ fontSize: 10, fontWeight: 600, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', cursor: 'text' }} title="点击重命名" onClick={() => startRename(index)}>{saved.name}</div>
                        )}
                        <div style={{ fontSize: 9, color: 'var(--muted)' }}>{saved.frames.length} 帧 · {saved.duration.toFixed(2)}s</div>
                      </div>
                      <button className="button button-secondary" style={{ minHeight: 26, padding: '3px 8px', fontSize: 9 }} onClick={() => loadSavedRecording(saved, index)}>加载</button>
                      <button className="button button-secondary" style={{ minHeight: 26, padding: '3px 8px', fontSize: 9 }} onClick={() => deleteSavedRecording(index)}>删除</button>
                    </div>
                  );
                })}
              </div>
            )}
          </Card>

          <Card>
            <div className="card-header"><div><h2>动作回放</h2></div></div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 6, marginBottom: 8 }}>
              <button className="button button-primary" disabled={!canPlay} onClick={startPlayback}>{playState === 'paused' ? '继续回放' : '开始回放'}</button>
              <button className="button button-secondary" disabled={playState !== 'playing' && playState !== 'paused'} onClick={pausePlayback}>{playState === 'playing' ? '暂停回放' : '暂停回放'}</button>
              <button className="button button-secondary" disabled={playState === 'idle'} onClick={stopPlayback}>停止回放</button>
            </div>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
              <label style={{ fontSize: 10, display: 'flex', alignItems: 'center', gap: 4 }}>
                <input type="checkbox" checked={playLoop} onChange={e => setPlayLoop(e.target.checked)} />
                循环回放
              </label>
              <label style={{ fontSize: 10, display: 'flex', alignItems: 'center', gap: 4 }}>
                速度
                <select value={playSpeed} onChange={e => setPlaySpeed(Number(e.target.value))} style={{ fontSize: 10 }}>
                  <option value="0.5">0.5x</option>
                  <option value="1">1.0x</option>
                  <option value="1.5">1.5x</option>
                  <option value="2">2.0x</option>
                </select>
              </label>
              <span className="muted">{playState === 'idle' ? '未回放' : playState === 'playing' ? '回放中' : '已暂停'} · {playInfo.idx}/{playInfo.total} · {playInfo.percent}%</span>
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}
