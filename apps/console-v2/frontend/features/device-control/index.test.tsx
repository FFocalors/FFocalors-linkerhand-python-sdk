import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { ConnectionSnapshot, DeviceCapabilities, DeviceConfig, DevicePort, TelemetryPort, TelemetrySnapshot } from '../../shared/contracts';
import { DeviceControl, type DeviceControlController } from './index';

const config: DeviceConfig = { schemaVersion: 1, deviceId: 'test-device', name: '测试设备', model: 'L25', hand: 'left', transport: { type: 'can', channel: 'fake' }, autoReconnect: true };
function capabilities(jointCount: number, speedCommandLength = jointCount, torqueCommandLength: number | null = jointCount): DeviceCapabilities {
  const vector = { length: jointCount, available: true, range: { min: 0, max: 255 } };
  return { schemaVersion: 1, deviceId: config.deviceId, model: config.model, hand: config.hand, transport: config.transport, jointCount, position: vector, speed: vector, current: vector, torque: vector, touch: vector, speedCommandLength, currentCommandLength: null, torqueCommandLength, supportedOperations: ['connect', 'disconnect', 'setPosition', 'setSpeed', 'setTorque', 'stop', 'unlock'] };
}
function snapshot(count: number, positions = Array.from({ length: count }, () => 0)): TelemetrySnapshot { return { schemaVersion: 1, deviceId: config.deviceId, sequence: 1, monotonicTimeMs: 1, positions, rawPosition: positions.map(value => Math.round(value * 255)), rawCurrent: [], rawSpeed: [], rawTouch: [], connected: true }; }
function telemetry(count: number, positions?: number[]): TelemetryPort { const value = snapshot(count, positions); return { read: async () => value, subscribe: () => () => undefined }; }
function connection(): ConnectionSnapshot { return { schemaVersion: 1, deviceId: config.deviceId, state: 'connected', attempt: 1, lastError: null }; }
function fixture(count = 2) {
  const controller: DeviceControlController = {
    connect: vi.fn(async () => undefined), disconnect: vi.fn(async () => undefined), reconnect: vi.fn(async () => undefined),
    subscribeConnection: vi.fn(listener => { listener(connection()); return () => undefined; }),
    setJointTarget: vi.fn(async () => undefined), setSpeed: vi.fn(async () => undefined), setTorque: vi.fn(async () => undefined),
    startQuickAction: vi.fn(async () => undefined), stopQuickAction: vi.fn(async () => undefined), startLoop: vi.fn(async () => undefined), stopLoop: vi.fn(async () => undefined),
  };
  const device: DevicePort = { getConfig: async () => config, getCapabilities: async () => capabilities(count), getConnection: async () => connection(), setJointTarget: vi.fn(async () => undefined), stopAll: vi.fn(async () => undefined), unlock: vi.fn(async () => undefined) };
  return { controller, device };
}
function renderControl(count = 2, fixtureValue = fixture(count)) { render(<DeviceControl device={fixtureValue.device} telemetry={telemetry(count)} config={config} capabilities={capabilities(count)} controller={fixtureValue.controller} />); return fixtureValue; }

describe('device control', () => {
  it('submits one complete normalized vector on final pointer release', async () => {
    const { controller } = renderControl(2); const slider = await screen.findByRole('slider', { name: 'J1 目标' });
    fireEvent.pointerDown(slider); fireEvent.change(slider, { target: { value: '0.42' } }); fireEvent.pointerUp(slider);
    await waitFor(() => expect(controller.setJointTarget).toHaveBeenCalledTimes(1));
    expect(vi.mocked(controller.setJointTarget).mock.calls[0][0]).toMatchObject({ positions: [0.42, 0], finalCommand: true });
  });
  it('coalesces rapid changes into at most one non-final command per frame', async () => {
    const { controller } = renderControl(2); const slider = await screen.findByRole('slider', { name: 'J1 目标' });
    fireEvent.pointerDown(slider); fireEvent.change(slider, { target: { value: '0.1' } }); fireEvent.change(slider, { target: { value: '0.2' } }); await new Promise(resolve => requestAnimationFrame(resolve));
    expect(vi.mocked(controller.setJointTarget).mock.calls.length).toBeLessThanOrEqual(1); fireEvent.pointerUp(slider); await waitFor(() => expect(vi.mocked(controller.setJointTarget).mock.calls.at(-1)?.[0].finalCommand).toBe(true));
  });
  it('does not let telemetry overwrite a joint while it is being dragged', async () => {
    let listener: ((value: TelemetrySnapshot) => void) | undefined; const source: TelemetryPort = { read: async () => snapshot(2, [0.1, 0.2]), subscribe: next => { listener = next; return () => undefined; } }; const { controller, device } = fixture(2);
    render(<DeviceControl device={device} telemetry={source} config={config} capabilities={capabilities(2)} controller={controller} />); const slider = await screen.findByRole('slider', { name: 'J1 目标' });
    fireEvent.pointerDown(slider); fireEvent.change(slider, { target: { value: '0.8' } }); listener?.(snapshot(2, [0.1, 0.9])); expect(slider).toHaveValue('0.8'); fireEvent.pointerUp(slider);
  });
  it('renders all 25 joints and groups them for compact access', async () => { renderControl(25); expect(await screen.findByRole('slider', { name: 'J25 目标' })).toBeInTheDocument(); expect(screen.getAllByRole('slider', { name: /J\d+ 目标/ })).toHaveLength(25); });
  it('covers connection actions and disables the feature without a controller', async () => {
    const fixtureValue = renderControl(2); fireEvent.click(await screen.findByRole('button', { name: '重新连接' })); expect(fixtureValue.controller.reconnect).toHaveBeenCalled(); cleanup(); const isolated = fixture(1);
    render(<DeviceControl device={isolated.device} telemetry={telemetry(1)} config={config} capabilities={capabilities(1)} />); expect(await screen.findByText(/未接入设备控制器/)).toBeInTheDocument(); expect(screen.getByRole('slider', { name: 'J1 目标' })).toBeDisabled();
  });
  it('locks immediately on stopAll and unlocks only after the shared calls complete', async () => {
    const { controller, device } = renderControl(1); fireEvent.click(await screen.findByRole('button', { name: '设备安全锁' })); await waitFor(() => expect(device.stopAll).toHaveBeenCalled()); expect(screen.getByRole('slider', { name: 'J1 目标' })).toBeDisabled(); fireEvent.click(screen.getByRole('button', { name: '设备安全锁' })); await waitFor(() => expect(device.unlock).toHaveBeenCalled()); expect(controller.setJointTarget).not.toHaveBeenCalled();
  });
  it('submits speed and torque only when capabilities provide command lengths', async () => {
    const { controller } = renderControl(2); fireEvent.click(await screen.findByRole('button', { name: '应用速度' })); fireEvent.click(screen.getByRole('button', { name: '应用扭矩' })); await waitFor(() => expect(controller.setSpeed).toHaveBeenCalled()); expect(controller.setTorque).toHaveBeenCalled();
    cleanup(); const noTorque = fixture(2); render(<DeviceControl device={noTorque.device} telemetry={telemetry(2)} config={config} capabilities={capabilities(2, 2, null)} controller={noTorque.controller} />); expect(await screen.findByRole('button', { name: '应用扭矩' })).toBeDisabled();
  });
});
