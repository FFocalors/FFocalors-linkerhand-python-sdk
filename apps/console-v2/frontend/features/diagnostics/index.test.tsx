import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { Diagnostics, TactileMatrix, TelemetryChart, buildConnectionChecks } from './index';
import type { DeviceCapabilities, DeviceConfig, LogPort, StructuredLogEntry, TelemetryPort } from '../../shared/contracts';

const config: DeviceConfig = { schemaVersion: 1, deviceId: 'demo', name: 'Demo', model: 'O6', hand: 'left', transport: { type: 'can', channel: 'fake' }, autoReconnect: true };
const capabilities: DeviceCapabilities = { schemaVersion: 1, deviceId: 'demo', model: 'O6', hand: 'left', transport: { type: 'can', channel: 'fake' }, jointCount: 2, position: { length: 2, available: true, range: { min: 0, max: 255 } }, speed: { length: 2, available: true, range: { min: 0, max: 255 } }, current: { length: 2, available: true, range: { min: 0, max: 255 } }, torque: { length: 2, available: true, range: { min: 0, max: 255 } }, touch: { length: 2, available: false, range: { min: 0, max: 255 } }, speedCommandLength: 2, currentCommandLength: null, torqueCommandLength: null, supportedOperations: [] };
const entry = (i: number, message = `消息 ${i}`): StructuredLogEntry => ({ schemaVersion: 1, id: String(i), monotonicTimeMs: i, level: i % 2 ? 'warn' : 'info', event: i % 2 ? 'connection.retry' : 'telemetry.sample', message, fields: {} });

describe('diagnostics feature', () => {
  it('explains an unavailable tactile capability without fabricating values', () => {
    render(<TactileMatrix capabilities={capabilities} />);
    expect(screen.getByText('当前设备没有触觉能力')).toBeInTheDocument();
    expect(screen.queryByRole('grid')).not.toBeInTheDocument();
  });

  it('waits for a complete tactile frame before rendering a zero', () => {
    const touchCapabilities = { ...capabilities, touch: { ...capabilities.touch, available: true } };
    render(<TactileMatrix capabilities={touchCapabilities} />);
    expect(screen.getByText('等待第一帧完整遥测')).toBeInTheDocument();
    expect(screen.queryByRole('grid')).not.toBeInTheDocument();
  });

  it('keeps all capability joints selectable, including J25', () => {
    render(<TelemetryChart jointCount={25} />);
    expect(screen.getByRole('option', { name: 'J25' })).toBeInTheDocument();
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
});
