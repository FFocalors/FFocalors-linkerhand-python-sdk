import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { Diagnostics, TactileMatrix, buildConnectionChecks } from './index';
import type { DeviceCapabilities, DeviceConfig, LogPort, StructuredLogEntry } from '../../shared/contracts';

const config: DeviceConfig = { schemaVersion: 1, deviceId: 'demo', name: 'Demo', model: 'O6', hand: 'left', transport: { type: 'can', channel: 'fake' }, autoReconnect: true };
const capabilities: DeviceCapabilities = { schemaVersion: 1, deviceId: 'demo', model: 'O6', hand: 'left', transport: { type: 'can', channel: 'fake' }, jointCount: 2, position: { length: 2, available: true, range: { min: 0, max: 255 } }, speed: { length: 2, available: true, range: { min: 0, max: 255 } }, current: { length: 2, available: true, range: { min: 0, max: 255 } }, torque: { length: 2, available: true, range: { min: 0, max: 255 } }, touch: { length: 2, available: false, range: { min: 0, max: 255 } }, speedCommandLength: 2, currentCommandLength: null, torqueCommandLength: null, supportedOperations: [] };
const entry = (i: number, message = `消息 ${i}`): StructuredLogEntry => ({ schemaVersion: 1, id: String(i), monotonicTimeMs: i, level: i % 2 ? 'warn' : 'info', event: i % 2 ? 'connection.retry' : 'telemetry.sample', message, fields: {} });

describe('diagnostics feature', () => {
  it('explains an unavailable tactile capability without fabricating values', () => {
    render(<TactileMatrix capabilities={capabilities} />);
    expect(screen.getByText('当前设备没有触觉能力')).toBeInTheDocument();
    expect(screen.queryByRole('grid')).not.toBeInTheDocument();
  });

  it('produces deterministic connection advice', () => {
    const checks = buildConnectionChecks({ config, capabilities, logs: [entry(1)], connection: { schemaVersion: 1, deviceId: 'demo', state: 'error', attempt: 2, lastError: null } });
    expect(checks.find(check => check.id === 'connection')).toMatchObject({ tone: 'error', action: '检查连接错误并重新连接' });
    expect(checks.find(check => check.id === 'logs')).toMatchObject({ tone: 'ok' });
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
});
