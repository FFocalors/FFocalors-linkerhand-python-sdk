import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { Diagnostics, TelemetryChart, buildConnectionChecks, SafetyCard, drawTelemetryCurve } from './index';
import type { DeviceCapabilities, DeviceConfig, LogPort, StructuredLogEntry, TelemetryPort, TelemetrySnapshot } from '../../shared/contracts';
import { createVirtualTelemetry } from '../../shared/telemetry/virtual';

const config: DeviceConfig = { schemaVersion: 1, deviceId: 'demo', name: 'Demo', model: 'O6', hand: 'left', transport: { type: 'can', channel: 'fake' }, autoReconnect: true };
const capabilities: DeviceCapabilities = { schemaVersion: 1, deviceId: 'demo', model: 'O6', hand: 'left', transport: { type: 'can', channel: 'fake' }, jointCount: 2, position: { length: 2, available: true, range: { min: 0, max: 255 } }, speed: { length: 2, available: true, range: { min: 0, max: 255 } }, current: { length: 2, available: true, range: { min: 0, max: 255 } }, torque: { length: 2, available: true, range: { min: 0, max: 255 } }, touch: { length: 2, available: false, range: { min: 0, max: 255 } }, speedCommandLength: 2, currentCommandLength: null, torqueCommandLength: null, supportedOperations: [] };
const entry = (i: number, message = `消息 ${i}`): StructuredLogEntry => ({ schemaVersion: 1, id: String(i), monotonicTimeMs: i, level: i % 2 ? 'warn' : 'info', event: i % 2 ? 'connection.retry' : 'telemetry.sample', message, fields: {} });

describe('diagnostics feature', () => {
  it('keeps all capability joints selectable, including J25', () => {
    render(<TelemetryChart jointCount={25} />);
    expect(screen.getByText('J25')).toBeInTheDocument();
  });

  it('renders a virtual telemetry stream for debug mode without a device port', () => {
    render(<TelemetryChart telemetry={createVirtualTelemetry(2)} jointCount={2} virtual />);
    expect(screen.getByText('调试虚拟遥测')).toBeInTheDocument();
    expect(screen.getByLabelText('关节遥测曲线')).toBeInTheDocument();
  });

  it('draws received samples instead of only rendering a source badge', () => {
    const context = {
      beginPath: vi.fn(), moveTo: vi.fn(), lineTo: vi.fn(), stroke: vi.fn(),
      strokeStyle: '', lineWidth: 0,
    } as unknown as CanvasRenderingContext2D;
    const sample = (sequence: number, position: number): TelemetrySnapshot => ({ schemaVersion: 1, deviceId: 'demo', sequence, monotonicTimeMs: sequence * 100, positions: [position], rawPosition: [Math.round(position * 255)], rawCurrent: [], rawSpeed: [], rawTouch: [], connected: true });
    const drawn = drawTelemetryCurve(context, { samples: [sample(1, 0.2), sample(2, 0.8)], jointCount: 1, visibleJoints: new Set([0]), windowMs: 30_000, width: 200, height: 80 });
    expect(drawn).toBe(1);
    expect(context.beginPath).toHaveBeenCalledTimes(1);
    expect(context.lineTo).toHaveBeenCalledWith(200, 16);
    expect(context.stroke).toHaveBeenCalledTimes(1);
  });

  it('keeps the chart card mounted when debug is off and no physical source exists', () => {
    render(<Diagnostics logs={{ list: vi.fn(async () => []) }} capabilities={capabilities} debugMode={false} isPhysicalDevice={false} />);
    expect(screen.getByLabelText('关节遥测曲线')).toBeInTheDocument();
    expect(screen.getByText('遥测端口未注入，等待运行时')).toBeInTheDocument();
  });

  it('lets diagnostics opt into virtual telemetry only when debug mode is active', async () => {
    render(<Diagnostics logs={{ list: vi.fn(async () => []) }} capabilities={capabilities} debugMode isPhysicalDevice={false} virtualTelemetry={createVirtualTelemetry(2)} />);
    expect(await screen.findByText('调试虚拟遥测')).toBeInTheDocument();
  });

  it('shares one virtual timer across subscribers and stops it after the last unsubscribe', () => {
    vi.useFakeTimers();
    const intervalSpy = vi.spyOn(window, 'setInterval');
    const clearIntervalSpy = vi.spyOn(window, 'clearInterval');
    const telemetry = createVirtualTelemetry(2);
    const first = vi.fn();
    const second = vi.fn();
    const unsubscribeFirst = telemetry.subscribe(first);
    const unsubscribeSecond = telemetry.subscribe(second);
    expect(intervalSpy).toHaveBeenCalledTimes(1);
    first.mockClear();
    second.mockClear();
    vi.advanceTimersByTime(220);
    expect(first).toHaveBeenCalledTimes(1);
    expect(second).toHaveBeenCalledTimes(1);
    expect(first.mock.calls[0][0].sequence).toBe(second.mock.calls[0][0].sequence);
    unsubscribeFirst();
    vi.advanceTimersByTime(220);
    expect(first).toHaveBeenCalledTimes(1);
    expect(second).toHaveBeenCalledTimes(2);
    unsubscribeSecond();
    expect(clearIntervalSpy).toHaveBeenCalledTimes(1);
    vi.advanceTimersByTime(440);
    expect(second).toHaveBeenCalledTimes(2);
    unsubscribeSecond();
    intervalSpy.mockRestore();
    clearIntervalSpy.mockRestore();
    vi.useRealTimers();
  });

  it('produces deterministic connection advice', () => {
    const checks = buildConnectionChecks({ config, capabilities, logs: [entry(1)], connection: { schemaVersion: 1, deviceId: 'demo', state: 'error', attempt: 2, lastError: null } });
    expect(checks.find(check => check.id === 'connection')).toMatchObject({ tone: 'error', action: '检查连接错误并重新连接' });
    expect(checks.find(check => check.id === 'logs')).toMatchObject({ tone: 'ok' });
  });

  it('uses the injected monotonic clock for telemetry age', () => {
    const checks = buildConnectionChecks({ telemetry: { schemaVersion: 1, deviceId: 'demo', sequence: 7, monotonicTimeMs: 1_000, positions: [], rawPosition: [], rawCurrent: [], rawSpeed: [], rawTouch: [], connected: true }, nowMs: 1_200 });
    expect(checks.find(check => check.id === 'telemetry')).toMatchObject({ tone: 'ok', detail: '序列 7 · 200 ms 前' });
  });

  it('loads bounded logs and filters by keyword', async () => {
    const list = vi.fn(async (_limit?: number) => Array.from({ length: 30 }, (_, i) => entry(i, i === 1 ? '网络已恢复' : `普通消息 ${i}`)));
    const logs: LogPort = { list };
    render(<Diagnostics logs={logs} config={config} capabilities={capabilities} />);
    await waitFor(() => expect(screen.getByText('网络已恢复')).toBeInTheDocument());
    fireEvent.change(screen.getByPlaceholderText('搜索事件或消息'), { target: { value: '网络' } });
    expect(screen.getByText('网络已恢复')).toBeInTheDocument();
    expect(screen.queryByText('普通消息 1')).not.toBeInTheDocument();
    expect(list).toHaveBeenCalledWith(512);
  });

  it('cancels a pending frame and unsubscribes when hidden or unmounted', () => {
    const unsubscribe = vi.fn();
    const frame = { schemaVersion: 1, deviceId: 'demo', sequence: 1, monotonicTimeMs: 1, positions: [0], rawPosition: [0], rawCurrent: [0], rawSpeed: [0], rawTouch: [0], connected: true };
    const telemetry: TelemetryPort = { read: vi.fn(async () => frame), subscribe: vi.fn(listener => { listener(frame); return unsubscribe; }) };
    const request = vi.spyOn(window, 'requestAnimationFrame').mockImplementation(() => 12);
    const cancel = vi.spyOn(window, 'cancelAnimationFrame').mockImplementation(() => undefined);
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
    const { unmount } = render(<TelemetryChart telemetry={telemetry} jointCount={1} />);
    expect(request).toHaveBeenCalled();
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' });
    document.dispatchEvent(new Event('visibilitychange'));
    expect(cancel).toHaveBeenCalledWith(12);
    unmount();
    expect(unsubscribe).toHaveBeenCalled();
    request.mockRestore(); cancel.mockRestore();
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
  });

  it('shows green safety badge when no errors exist', () => {
    render(<SafetyCard entries={[]} disconnectCount={0} />);
    expect(screen.getByText('正常')).toBeInTheDocument();
    expect(screen.queryByText('最新错误')).not.toBeInTheDocument();
  });

  it('shows amber safety badge when errors exist but no recent ones', () => {
    const oldEntries: StructuredLogEntry[] = [
      { schemaVersion: 1, id: '1', monotonicTimeMs: 1000, level: 'error', event: 'test', message: '旧错误', fields: {} },
      { schemaVersion: 1, id: '2', monotonicTimeMs: 500_000, level: 'info', event: 'test', message: '现在', fields: {} },
    ];
    render(<SafetyCard entries={oldEntries} disconnectCount={0} />);
    expect(screen.getByText('需关注')).toBeInTheDocument();
    expect(screen.getByText('旧错误')).toBeInTheDocument();
  });

  it('shows red safety badge when recent errors exist', () => {
    const now = performance.now();
    const recentEntries: StructuredLogEntry[] = [
      { schemaVersion: 1, id: '1', monotonicTimeMs: Math.floor(now), level: 'error', event: 'test', message: '新错误', fields: {} }
    ];
    render(<SafetyCard entries={recentEntries} disconnectCount={0} />);
    expect(screen.getByText('异常')).toBeInTheDocument();
    expect(screen.getByText('新错误')).toBeInTheDocument();
  });

  it('displays telemetry disconnect count', () => {
    render(<SafetyCard entries={[]} disconnectCount={3} />);
    expect(screen.getByText('3')).toBeInTheDocument();
  });

  it('filters logs by time range', async () => {
    const now = performance.now();
    const logs: StructuredLogEntry[] = [
      { schemaVersion: 1, id: '1', monotonicTimeMs: Math.floor(now - 30_000), level: 'info', event: 'test', message: '30秒前', fields: {} },
      { schemaVersion: 1, id: '2', monotonicTimeMs: Math.floor(now - 120_000), level: 'info', event: 'test', message: '2分钟前', fields: {} },
    ];
    const list = vi.fn(async () => logs);
    render(<Diagnostics logs={{ list }} config={config} capabilities={capabilities} />);
    await waitFor(() => expect(screen.getByText('30秒前')).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText('时间范围'), { target: { value: '1m' } });
    expect(screen.getByText('30秒前')).toBeInTheDocument();
    expect(screen.queryByText('2分钟前')).not.toBeInTheDocument();
  });
});
