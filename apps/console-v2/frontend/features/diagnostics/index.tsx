import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AlertTriangle, Check, ChevronDown, Download, Pause, Play, RotateCcw, Shield, SlidersHorizontal } from 'lucide-react';
import type { ConnectionSnapshot, DeviceCapabilities, DeviceConfig, DevicePort, LogLevel, LogPort, StructuredLogEntry, TelemetryPort, TelemetrySnapshot } from '../../shared/contracts';
import { Badge, Button, Card, NumberValue, Select, TextField } from '../../shared/ui';
import { useI18n } from '../../shared/i18n';
import type { VirtualTelemetryPort } from '../../shared/telemetry/virtual';
import './diagnostics.css';

const CURVE_COLORS = ['#3568f2', '#208c60', '#a9680f', '#b65144', '#7450a7', '#0f9ba8'];
const O6_JOINT_NAMES = ['大拇指弯曲', '大拇指横摆', '食指弯曲', '中指弯曲', '无名指弯曲', '小拇指弯曲'];
function jointName(index: number, count: number): string {
  return count > 0 && index < O6_JOINT_NAMES.length ? O6_JOINT_NAMES[index] : `J${index + 1}`;
}
const MAX_POINTS = 240;
const MAX_SELECTABLE_JOINTS = 25;
const LOG_LIMIT = 512;
const LOG_ROW_HEIGHT = 42;
export type CheckTone = 'ok' | 'warn' | 'error' | 'unknown';
export interface DiagnosticCheck { id: string; title: string; tone: CheckTone; detail: string; action?: string }

export function buildConnectionChecks(input: { config?: DeviceConfig; capabilities?: DeviceCapabilities; connection?: ConnectionSnapshot; telemetry?: TelemetrySnapshot; logs?: StructuredLogEntry[]; nowMs?: number }): DiagnosticCheck[] {
  const checks: DiagnosticCheck[] = [];
  checks.push(input.config ? { id: 'config', title: '设备配置', tone: input.config.deviceId ? 'ok' : 'error', detail: input.config.deviceId ? `${input.config.name} · ${input.config.model}` : '缺少设备 ID', action: input.config.deviceId ? undefined : '打开设置，保存设备配置' } : { id: 'config', title: '设备配置', tone: 'unknown', detail: '诊断端口尚未提供配置', action: '连接运行时后重试' });
  checks.push(input.capabilities ? { id: 'capabilities', title: '能力声明', tone: input.capabilities.jointCount > 0 ? 'ok' : 'error', detail: input.capabilities.jointCount > 0 ? `${input.capabilities.jointCount} 个关节` : '未声明关节', action: input.capabilities.jointCount > 0 ? undefined : '检查设备型号或能力响应' } : { id: 'capabilities', title: '能力声明', tone: 'unknown', detail: '等待能力信息', action: '连接设备后重试' });
  const state = input.connection?.state;
  checks.push(state === 'connected' ? { id: 'connection', title: '连接状态', tone: 'ok', detail: '设备已连接' } : state ? { id: 'connection', title: '连接状态', tone: state === 'error' ? 'error' : 'warn', detail: `当前状态：${state}`, action: state === 'error' ? '检查连接错误并重新连接' : '等待连接完成' } : { id: 'connection', title: '连接状态', tone: 'unknown', detail: '尚未读取连接状态', action: '连接运行时后重试' });
  if (input.telemetry) { const age = Math.max(0, (input.nowMs ?? input.telemetry.monotonicTimeMs) - input.telemetry.monotonicTimeMs); checks.push(input.telemetry.connected && age <= 5_000 ? { id: 'telemetry', title: '遥测流', tone: 'ok', detail: `序列 ${input.telemetry.sequence} · ${age} ms 前` } : { id: 'telemetry', title: '遥测流', tone: 'warn', detail: input.telemetry.connected ? `数据延迟 ${age} ms` : '设备未报告遥测连接', action: '确认设备在线并检查采样日志' }); } else checks.push({ id: 'telemetry', title: '遥测流', tone: 'unknown', detail: '尚未读取遥测', action: '打开遥测端口后重试' });
  const errors = input.logs?.filter(entry => entry.level === 'error').length ?? 0;
  checks.push(input.logs ? errors === 0 ? { id: 'logs', title: '日志健康', tone: 'ok', detail: `${input.logs.length} 条记录，无错误事件` } : { id: 'logs', title: '日志健康', tone: 'warn', detail: `${errors} 条错误事件`, action: '按 error 级别筛选并查看建议' } : { id: 'logs', title: '日志健康', tone: 'unknown', detail: '尚未读取日志' });
  return checks;
}

function useTelemetryRead(telemetry?: TelemetryPort) {
  const [snapshot, setSnapshot] = useState<TelemetrySnapshot | undefined>(undefined);
  useEffect(() => { if (!telemetry) return; let active = true; void telemetry.read().then(value => { if (active) setSnapshot(value); }).catch(() => undefined); return () => { active = false; }; }, [telemetry]);
  return snapshot;
}

function visibilityAllowsDrawing(canvas: HTMLCanvasElement | null) {
  return Boolean(canvas && (document.visibilityState === 'visible' || document.visibilityState === undefined));
}

/** Draw the currently visible sample window and return the number of curves drawn. */
export function drawTelemetryCurve(context: CanvasRenderingContext2D, input: { samples: TelemetrySnapshot[]; jointCount: number; visibleJoints: Set<number>; windowMs: number; width: number; height: number }): number {
  const latestTime = input.samples.at(-1)?.monotonicTimeMs ?? 0;
  const visible = input.samples.filter(sample => latestTime - sample.monotonicTimeMs <= input.windowMs).slice(-MAX_POINTS);
  if (visible.length < 2) return 0;
  const joints = Array.from(input.visibleJoints).filter(index => index < input.jointCount).sort((a, b) => a - b);
  let drawn = 0;
  for (const jointIndex of joints) {
    const values = visible.map(sample => sample.positions[jointIndex] ?? 0);
    if (values.length < 2) continue;
    context.strokeStyle = CURVE_COLORS[jointIndex % CURVE_COLORS.length];
    context.lineWidth = 2;
    context.beginPath();
    values.forEach((value, index) => {
      const x = index / Math.max(1, values.length - 1) * input.width;
      const y = input.height - Math.max(0, Math.min(1, value)) * input.height;
      if (index === 0) context.moveTo(x, y);
      else context.lineTo(x, y);
    });
    context.stroke();
    drawn += 1;
  }
  return drawn;
}

export function TelemetryChart({ telemetry, jointCount = 0, virtual = false }: { telemetry?: TelemetryPort; jointCount?: number; virtual?: boolean }) {
  const { t } = useI18n();
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const samplesRef = useRef<TelemetrySnapshot[]>([]);
  const rafRef = useRef<number | undefined>(undefined);
  const pausedRef = useRef(false);
  const [paused, setPaused] = useState(false);
  const [windowMs, setWindowMs] = useState(30_000);
  const effectiveJointCount = Math.min(Math.max(jointCount, 0), MAX_SELECTABLE_JOINTS);
  const [visibleJoints, setVisibleJoints] = useState<Set<number>>(() => new Set(Array.from({ length: effectiveJointCount }, (_, i) => i)));

  useEffect(() => {
    setVisibleJoints(new Set(Array.from({ length: effectiveJointCount }, (_, i) => i)));
  }, [effectiveJointCount]);

  const toggleJoint = useCallback((index: number) => {
    setVisibleJoints(prev => {
      const next = new Set(prev);
      if (next.has(index)) {
        if (next.size <= 1) return prev;
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
    if (!canvas || !visibilityAllowsDrawing(canvas)) return;
    const context = canvas.getContext('2d');
    if (!context) return;
    const width = canvas.clientWidth || 640;
    const height = canvas.clientHeight || 220;
    const ratio = window.devicePixelRatio || 1;
    if (canvas.width !== Math.round(width * ratio) || canvas.height !== Math.round(height * ratio)) {
      canvas.width = Math.round(width * ratio);
      canvas.height = Math.round(height * ratio);
    }
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    context.clearRect(0, 0, width, height);
    const tokens = getComputedStyle(canvas);
    context.strokeStyle = tokens.getPropertyValue('--line').trim() || 'currentColor';
    context.lineWidth = 1;
    for (let i = 1; i < 4; i += 1) {
      const y = height * i / 4;
      context.beginPath();
      context.moveTo(0, y);
      context.lineTo(width, y);
      context.stroke();
    }
    drawTelemetryCurve(context, { samples: samplesRef.current, jointCount: effectiveJointCount, visibleJoints, windowMs, width, height });
  }, [windowMs, visibleJoints]);

  const scheduleDraw = useCallback(() => {
    if (rafRef.current === undefined && visibilityAllowsDrawing(canvasRef.current)) {
      rafRef.current = requestAnimationFrame(draw);
    }
  }, [draw]);

  useEffect(() => { pausedRef.current = paused; }, [paused]);
  useEffect(() => {
    if (!telemetry) return;
    const unsubscribe = telemetry.subscribe(value => {
      if (pausedRef.current) return;
      samplesRef.current.push(value);
      if (samplesRef.current.length > MAX_POINTS) samplesRef.current.splice(0, samplesRef.current.length - MAX_POINTS);
      scheduleDraw();
    });
    return unsubscribe;
  }, [scheduleDraw, telemetry]);
  useEffect(() => {
    const onVisibility = () => {
      if (document.visibilityState === 'hidden' && rafRef.current !== undefined) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = undefined;
      } else scheduleDraw();
    };
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      document.removeEventListener('visibilitychange', onVisibility);
      if (rafRef.current !== undefined) cancelAnimationFrame(rafRef.current);
    };
  }, [scheduleDraw]);

  return (
    <Card className="diagnostic-chart">
      <div className="card-header">
        <div>
          <h2>{t('diagnostics.curve.title')}</h2>
          <span className="muted">固定 {MAX_POINTS} 点 · 仅绘制可见窗口</span>
        </div>
        <div className="chart-controls">
          <Button variant="ghost" size="sm" onClick={() => { samplesRef.current = []; scheduleDraw(); }}>
            <RotateCcw size={14} />{t('common.button.clear')}
          </Button>
          <Button variant="ghost" size="sm" onClick={() => setPaused(value => !value)}>
            {paused ? <Play size={14} /> : <Pause size={14} />}
            {paused ? t('common.button.resume') : t('common.button.pause')}
          </Button>
        </div>
      </div>
      <div className="chart-toolbar">
        <Select label="时间窗" value={windowMs} onChange={event => setWindowMs(Number(event.target.value))}>
            <option value={10_000}>10 秒</option>
            <option value={30_000}>30 秒</option>
            <option value={60_000}>60 秒</option>
        </Select>
        <span className="muted">{virtual ? '调试虚拟遥测' : telemetry ? (paused ? '已暂停采样' : '实时采样') : '遥测端口未注入，等待运行时'}</span>
      </div>
      <div className="curve-legend">
        {Array.from({ length: effectiveJointCount }, (_, index) => (
          <Button
            key={index}
            type="button"
            className={`curve-legend-item ${visibleJoints.has(index) ? '' : 'curve-legend-hidden'}`}
            onClick={() => toggleJoint(index)}
            title={visibleJoints.has(index) ? `点击隐藏 ${jointName(index, effectiveJointCount)}` : `点击显示 ${jointName(index, effectiveJointCount)}`}
          >
            <i style={{ background: visibleJoints.has(index) ? CURVE_COLORS[index % CURVE_COLORS.length] : 'transparent' }} />
            {jointName(index, effectiveJointCount)}
          </Button>
        ))}
      </div>
      <canvas ref={canvasRef} className="telemetry-canvas" aria-label="关节遥测曲线" />
      <div className="chart-scale">
        <span>1.0</span>
        <span>0.5</span>
        <span>0.0</span>
      </div>
    </Card>
  );
}

export interface DiagnosticsExportPort { exportJson(payload: string): Promise<void> }
export function browserDownloadDiagnostics(payload: string, filename = 'linkerhand-diagnostics.json') {
  if (typeof document === 'undefined' || typeof URL === 'undefined' || typeof URL.createObjectURL !== 'function') {
    throw new Error('当前环境不支持浏览器下载，请使用桌面运行时导出');
  }
  const link = document.createElement('a');
  const url = URL.createObjectURL(new Blob([payload], { type: 'application/json' }));
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

function LogTable({ entries }: { entries: StructuredLogEntry[] }) {
  const [scrollTop, setScrollTop] = useState(0);
  const windowSize = 9;
  const start = Math.max(0, Math.floor(scrollTop / LOG_ROW_HEIGHT) - 2);
  const visible = entries.slice(start, start + windowSize);

  return (
    <div className="log-window" onScroll={event => setScrollTop(event.currentTarget.scrollTop)} role="log" aria-label="结构化事件日志">
      <div style={{ height: entries.length * LOG_ROW_HEIGHT, position: 'relative' }}>
        {visible.map((entry, index) => (
          <div className="log-row diagnostic-log-row" key={`${entry.id}-${entry.monotonicTimeMs}`} style={{ position: 'absolute', top: (start + index) * LOG_ROW_HEIGHT, left: 0, right: 0 }}>
            <span className={`log-dot ${entry.level}`} />
            <span className="mono">{entry.monotonicTimeMs}</span>
            <strong>{entry.message}</strong>
            <span className="log-source">{entry.event}</span>
          </div>
        ))}
      </div>
      {entries.length === 0 && <div className="log-empty">没有匹配的日志</div>}
    </div>
  );
}

type TimeRange = '1m' | '5m' | 'all';
const TIME_RANGE_MS: Record<TimeRange, number> = { '1m': 60_000, '5m': 5 * 60_000, all: 0 };

function LogPanel({ logs, entries, setEntries }: { logs: LogPort; entries: StructuredLogEntry[]; setEntries: (entries: StructuredLogEntry[]) => void }) {
  const { t, locale } = useI18n();
  const [level, setLevel] = useState<LogLevel | 'all'>('all');
  const [event, setEvent] = useState('');
  const [keyword, setKeyword] = useState('');
  const [timeRange, setTimeRange] = useState<TimeRange>('all');
  const [error, setError] = useState('');
  const [exporting, setExporting] = useState(false);

  const latestTimestamp = useMemo(() => entries.reduce((max, entry) => Math.max(max, entry.monotonicTimeMs), 0), [entries]);
  const filtered = useMemo(() => entries.filter(entry => {
    const matchesLevel = level === 'all' || entry.level === level;
    const matchesEvent = !event || entry.event === event;
    const matchesKeyword = !keyword || `${entry.event} ${entry.message}`.toLowerCase().includes(keyword.toLowerCase());
    const matchesTime = timeRange === 'all' || latestTimestamp - entry.monotonicTimeMs <= TIME_RANGE_MS[timeRange];
    return matchesLevel && matchesEvent && matchesKeyword && matchesTime;
  }), [entries, event, keyword, level, timeRange, latestTimestamp]);

  const refresh = async () => {
    setError('');
    try {
      setEntries(await logs.list(LOG_LIMIT));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '读取日志失败，请稍后重试');
    }
  };

  const exportLogs = async () => {
    setExporting(true);
    setError('');
    try {
      const payload = JSON.stringify({ schemaVersion: 1, generatedAt: new Date().toISOString(), logs: filtered }, null, 2);
      browserDownloadDiagnostics(payload);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '导出失败，请检查下载权限');
    } finally {
      setExporting(false);
    }
  };

  const events = Array.from(new Set(entries.map(entry => entry.event))).slice(0, 100);

  return (
    <Card className="log-card">
      <div className="card-header">
        <div>
          <h2>{t('diagnostics.logs.title')}</h2>
          <span className="muted">窗口化显示 · 最多载入 {LOG_LIMIT} 条</span>
        </div>
        <div className="heading-actions">
          <Button variant="ghost" size="sm" onClick={() => void refresh()}>
            <RotateCcw size={14} />{t('common.button.refresh')}
          </Button>
          <Button variant="secondary" size="sm" disabled={exporting} onClick={() => void exportLogs()}>
            <Download size={14} />{exporting ? (locale === 'en' ? 'Exporting…' : '导出中…') : (locale === 'en' ? 'Export JSON' : '导出 JSON')}
          </Button>
        </div>
      </div>
      <div className="log-filters">
        <Select label="级别" value={level} onChange={value => setLevel(value.target.value as LogLevel | 'all')}>
            <option value="all">全部</option>
            {(['trace', 'debug', 'info', 'warn', 'error'] as const).map(item => <option key={item} value={item}>{item}</option>)}
        </Select>
        <Select label="事件" value={event} onChange={value => setEvent(value.target.value)}>
            <option value="">全部事件</option>
            {events.map(item => <option key={item} value={item}>{item}</option>)}
        </Select>
        <Select label="时间范围" value={timeRange} onChange={value => setTimeRange(value.target.value as TimeRange)}>
            <option value="all">全部</option>
            <option value="5m">最近5分钟</option>
            <option value="1m">最近1分钟</option>
        </Select>
        <TextField label="关键词" className="keyword-filter" value={keyword} onChange={value => setKeyword(value.target.value)} placeholder="搜索事件或消息" />
      </div>
      {error && <p className="diagnostic-error" role="alert">{error}</p>}
      <LogTable entries={filtered} />
    </Card>
  );
}

export function SafetyCard({ entries, disconnectCount }: { entries: StructuredLogEntry[]; disconnectCount: number }) {
  const { locale } = useI18n();
  const errorCount = entries.filter(entry => entry.level === 'error').length;
  const warnCount = entries.filter(entry => entry.level === 'warn').length;
  const latestTimestamp = useMemo(() => entries.reduce((max, entry) => Math.max(max, entry.monotonicTimeMs), 0), [entries]);
  const recentErrors = entries.filter(entry => entry.level === 'error' && latestTimestamp - entry.monotonicTimeMs <= 5 * 60_000);
  const hasErrors = errorCount > 0;
  const hasRecentErrors = recentErrors.length > 0;
  const tone = hasRecentErrors ? 'red' : hasErrors ? 'amber' : 'green';
  const label = hasRecentErrors ? '异常' : hasErrors ? '需关注' : '正常';
  const latestError = [...entries].reverse().find(entry => entry.level === 'error');

  return (
    <Card className="safety-card">
      <div className="card-header">
        <div>
          <h2>{locale === 'en' ? 'Safety monitoring' : '安全监控'}</h2>
          <span className="muted">错误与警告统计 · 遥测断线计数</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Shield size={16} />
          <Badge tone={tone}>{label}</Badge>
        </div>
      </div>
      <div className="safety-stats">
        <div className="safety-stat">
          <span className="metric-label">错误</span>
          <div className="metric-lg">{errorCount}</div>
        </div>
        <div className="safety-stat">
          <span className="metric-label">警告</span>
          <div className="metric-lg">{warnCount}</div>
        </div>
        <div className="safety-stat">
          <span className="metric-label">遥测断线</span>
          <div className="metric-lg">{disconnectCount}</div>
        </div>
      </div>
      {latestError && (
        <div className="safety-latest-error">
          <AlertTriangle size={14} />
          <span>{latestError.message}</span>
        </div>
      )}
    </Card>
  );
}

function CheckList({ checks }: { checks: DiagnosticCheck[] }) {
  return (
    <div className="check-list">
      {checks.map(check => (
        <div className={`check-row tone-${check.tone}`} key={check.id}>
          <span className="check-icon">{check.tone === 'ok' ? <Check size={15} /> : <AlertTriangle size={15} />}</span>
          <div>
            <strong>{check.title}</strong>
            <span>{check.detail}</span>
            {check.action && <small>建议：{check.action}</small>}
          </div>
          <Badge tone={check.tone === 'ok' ? 'green' : check.tone === 'error' ? 'red' : 'amber'}>
            {check.tone === 'ok' ? '正常' : check.tone === 'unknown' ? '待检查' : '需关注'}
          </Badge>
        </div>
      ))}
    </div>
  );
}

export function Diagnostics({ logs, telemetry, device, config, capabilities, exportPort, onAlertChange, debugMode = false, isPhysicalDevice = false, virtualTelemetry }: { logs: LogPort; telemetry?: TelemetryPort; device?: DevicePort; config?: DeviceConfig; capabilities?: DeviceCapabilities; exportPort?: DiagnosticsExportPort; onAlertChange?: (hasAlert: boolean) => void; debugMode?: boolean; isPhysicalDevice?: boolean; virtualTelemetry?: VirtualTelemetryPort }) {
  const { t, locale } = useI18n();
  const [entries, setEntries] = useState<StructuredLogEntry[]>([]);
  const [connection, setConnection] = useState<ConnectionSnapshot>();
  const [resolvedConfig, setResolvedConfig] = useState(config);
  const [resolvedCapabilities, setResolvedCapabilities] = useState(capabilities);
  const virtualSource = debugMode && !isPhysicalDevice ? virtualTelemetry : undefined;
  const effectiveTelemetry = virtualSource ?? (isPhysicalDevice ? telemetry : undefined);
  const telemetrySnapshot = useTelemetryRead(effectiveTelemetry);
  const [showRaw, setShowRaw] = useState(false);
  const [loadError, setLoadError] = useState('');
  const [exportError, setExportError] = useState('');
  const [disconnectCount, setDisconnectCount] = useState(0);
  const prevConnectedRef = useRef<boolean | undefined>(undefined);

  useEffect(() => {
    if (!effectiveTelemetry) return;
    prevConnectedRef.current = undefined;
    return effectiveTelemetry.subscribe(snapshot => {
      if (prevConnectedRef.current === true && snapshot.connected === false) {
        setDisconnectCount(c => c + 1);
      }
      prevConnectedRef.current = snapshot.connected;
    });
  }, [effectiveTelemetry]);

  useEffect(() => {
    let active = true;
    void logs.list(LOG_LIMIT).then(value => {
      if (active) setEntries(value);
    }).catch(cause => {
      if (active) setLoadError(cause instanceof Error ? cause.message : '读取日志失败');
    });
    return () => { active = false; };
  }, [logs]);

  useEffect(() => {
    let active = true;
    void Promise.all([device?.getConnection(), device?.getConfig(), device?.getCapabilities()]).then(([nextConnection, nextConfig, nextCapabilities]) => {
      if (!active) return;
      if (nextConnection) setConnection(nextConnection);
      if (nextConfig) setResolvedConfig(nextConfig);
      if (nextCapabilities) setResolvedCapabilities(nextCapabilities);
    }).catch(() => undefined);
    return () => { active = false; };
  }, [device]);

  const checks = useMemo(() => buildConnectionChecks({ config: resolvedConfig, capabilities: resolvedCapabilities, connection, telemetry: telemetrySnapshot, logs: entries, nowMs: typeof performance !== 'undefined' ? performance.now() : undefined }), [connection, entries, resolvedCapabilities, resolvedConfig, telemetrySnapshot]);
  useEffect(() => { if (onAlertChange) onAlertChange(checks.some(check => check.tone === 'error')); }, [checks, onAlertChange]);
  const exportPackage = async () => {
    setExportError('');
    try {
      const payload = JSON.stringify({ schemaVersion: 1, generatedAt: new Date().toISOString(), checks, logs: entries }, null, 2);
      if (exportPort) await exportPort.exportJson(payload);
      else browserDownloadDiagnostics(payload);
    } catch (cause) {
      setExportError(cause instanceof Error ? cause.message : '导出失败，请检查下载权限');
    }
  };

  return (
    <div className="stack diagnostics-feature">
      <div className="page-heading">
        <div>
          <h1>{t('diagnostics.title')}</h1>
          <p>{locale === 'en' ? 'Use deterministic checks to assess connection, telemetry, and log state.' : '用确定性检查快速判断连接、遥测与日志状态。'}</p>
        </div>
        <Button variant="secondary" onClick={() => void exportPackage()}>
          <Download size={15} />{locale === 'en' ? 'Export diagnostics' : '导出诊断包'}
        </Button>
      </div>
      {loadError && <div className="diagnostic-error" role="alert">{loadError}</div>}
      {exportError && <div className="diagnostic-error" role="alert">{exportError}</div>}
      <div className="diagnostic-summary">
        <Card>
          <span className="metric-label">自检结果</span>
          <div className="metric-lg"><NumberValue value={checks.filter(check => check.tone === 'ok').length} /><small> / {checks.length} 正常</small></div>
          <Badge tone={checks.some(check => check.tone === 'error') ? 'red' : checks.some(check => check.tone === 'warn') ? 'amber' : 'green'}>
            {checks.some(check => check.tone === 'error') ? '需要处理' : checks.some(check => check.tone === 'warn') ? '需关注' : '正常'}
          </Badge>
        </Card>
        <Card>
          <span className="metric-label">日志窗口</span>
          <div className="metric-lg"><NumberValue value={entries.length} /><small> 条</small></div>
          <Badge>有界输入</Badge>
        </Card>
        <Card>
          <span className="metric-label">遥测点上限</span>
          <div className="metric-lg"><NumberValue value={MAX_POINTS} /><small> 点</small></div>
          <Badge>固定窗口</Badge>
        </Card>
      </div>
      {effectiveTelemetry && <TelemetryChart telemetry={effectiveTelemetry} jointCount={resolvedCapabilities?.jointCount} virtual={Boolean(virtualSource)} />}
      <SafetyCard entries={entries} disconnectCount={disconnectCount} />
      <Card className="self-check-card">
        <div className="card-header">
          <div>
            <h2>{t('diagnostics.connection.title')}</h2>
            <span className="muted">{locale === 'en' ? 'Read-only checks of injected ports; does not access the device directly' : '只读检查注入端口，不直接访问设备'}</span>
          </div>
          <Button variant="ghost" size="sm" onClick={() => setShowRaw(value => !value)}>
            <SlidersHorizontal size={14} />{showRaw ? (locale === 'en' ? 'Hide raw values' : '隐藏 raw 值') : t('diagnostics.raw.toggle')}<ChevronDown size={14} />
          </Button>
        </div>
        <CheckList checks={checks} />
        {showRaw && <pre className="raw-drawer">{JSON.stringify({ telemetry: telemetrySnapshot, connection }, null, 2)}</pre>}
      </Card>
      <LogPanel logs={logs} entries={entries} setEntries={setEntries} />
    </div>
  );
}
