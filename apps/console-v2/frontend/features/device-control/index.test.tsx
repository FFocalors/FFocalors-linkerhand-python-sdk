import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { Profiler } from 'react';
import type { ConnectionSnapshot, DeviceCapabilities, DeviceConfig, DevicePort, OperationSnapshot, TelemetryPort, TelemetrySnapshot } from '../../shared/contracts';
import { DeviceControl, JointSlider, type DeviceControlController } from './index';
import { createVirtualTelemetry } from '../../shared/telemetry/virtual';

const config: DeviceConfig = { schemaVersion: 1, deviceId: 'test-device', name: '测试设备', model: 'L25', hand: 'left', transport: { type: 'can', channel: 'fake' }, autoReconnect: true };
function capabilities(jointCount: number, speedCommandLength = jointCount, torqueCommandLength: number | null = jointCount): DeviceCapabilities {
  const vector = { length: jointCount, available: true, range: { min: 0, max: 255 } };
  return { schemaVersion: 1, deviceId: config.deviceId, model: config.model, hand: config.hand, transport: config.transport, jointCount, position: vector, speed: vector, current: vector, torque: vector, touch: vector, speedCommandLength, currentCommandLength: null, torqueCommandLength, supportedOperations: ['connect', 'disconnect', 'setPosition', 'setSpeed', 'setTorque', 'stop', 'unlock'] };
}
function snapshot(count: number, positions = Array.from({ length: count }, () => 0)): TelemetrySnapshot { return { schemaVersion: 1, deviceId: config.deviceId, sequence: 1, monotonicTimeMs: 1, positions, rawPosition: positions.map(value => Math.round(value * 255)), rawCurrent: [], rawSpeed: [], rawTouch: [], connected: true }; }
function telemetry(count: number, positions?: number[]): TelemetryPort { const value = snapshot(count, positions); return { read: async () => value, subscribe: () => () => undefined }; }
function connection(): ConnectionSnapshot { return { schemaVersion: 1, deviceId: config.deviceId, state: 'connected', attempt: 1, lastError: null }; }
function fixture(count = 2) {
  const operationListeners = new Set<(value: OperationSnapshot) => void>();
  const controller: DeviceControlController = {
    connect: vi.fn(async () => undefined), disconnect: vi.fn(async () => undefined), reconnect: vi.fn(async () => undefined),
    subscribeConnection: vi.fn(listener => { listener(connection()); return () => undefined; }),
    subscribeOperation: vi.fn(listener => { operationListeners.add(listener); return () => operationListeners.delete(listener); }),
    setJointTarget: vi.fn(async () => undefined), setSpeed: vi.fn(async () => undefined), setTorque: vi.fn(async () => undefined),
    startQuickAction: vi.fn(async () => undefined), stopQuickAction: vi.fn(async () => undefined), startLoop: vi.fn(async () => undefined), stopLoop: vi.fn(async () => undefined),
  };
  const device: DevicePort = { getConfig: async () => config, getCapabilities: async () => capabilities(count), getConnection: async () => connection(), setJointTarget: vi.fn(async () => undefined), stopAll: vi.fn(async () => undefined), unlock: vi.fn(async () => undefined) };
  return { controller, device, operationListeners };
}
function renderControl(count = 2, fixtureValue = fixture(count), overrides: Partial<{ debugMode: boolean; isPhysicalDevice: boolean }> = {}) { render(<DeviceControl device={fixtureValue.device} telemetry={telemetry(count)} config={config} capabilities={capabilities(count)} controller={fixtureValue.controller} debugMode={overrides.debugMode ?? true} isPhysicalDevice={overrides.isPhysicalDevice ?? true} />); return fixtureValue; }

describe('device control', () => {
  it('submits one complete normalized vector on final pointer release', async () => {
    const { controller } = renderControl(2); const slider = await screen.findByRole('slider', { name: '大拇指弯曲 目标' });
    fireEvent.pointerDown(slider); fireEvent.change(slider, { target: { value: '0.42' } }); fireEvent.pointerUp(slider);
    await waitFor(() => expect(controller.setJointTarget).toHaveBeenCalledTimes(1));
    expect(vi.mocked(controller.setJointTarget).mock.calls[0][0]).toMatchObject({ positions: [0.42, 0], finalCommand: true });
  });
  it('uses a fine-grained target slider and keeps a virtual curve in debug mode', async () => {
    const fixtureValue = fixture(1);
    const virtualSource = createVirtualTelemetry(1, [0.42]);
    const subscribe = vi.spyOn(virtualSource, 'subscribe');
    render(<DeviceControl device={fixtureValue.device} telemetry={telemetry(1)} config={config} capabilities={capabilities(1)} controller={fixtureValue.controller} debugMode isPhysicalDevice={false} virtualTelemetry={virtualSource} />);
    const slider = await screen.findByRole('slider', { name: '大拇指弯曲 目标' });
    expect(slider).toHaveAttribute('step', '0.001');
    expect(await screen.findByText('调试虚拟遥测')).toBeInTheDocument();
    await waitFor(() => expect(subscribe.mock.calls.length).toBeGreaterThanOrEqual(2));
    expect((await virtualSource.read()).rawPosition).toEqual([107]);
    expect((await virtualSource.read()).rawPosition).toEqual([107]);
  });
  it('shows one value for each capability and keeps preset groups visually distinct', async () => {
    const fixtureValue = fixture(6);
    render(<DeviceControl device={fixtureValue.device} telemetry={telemetry(6)} config={{ ...config, model: 'O6' }} capabilities={{ ...capabilities(6), model: 'O6' }} controller={fixtureValue.controller} debugMode isPhysicalDevice={false} virtualTelemetry={createVirtualTelemetry(6)} />);
    expect(await screen.findByLabelText('速度当前值')).toHaveTextContent('100%');
    expect(screen.getAllByLabelText('速度当前值')).toHaveLength(1);
    expect(screen.getAllByLabelText('扭矩当前值')).toHaveLength(1);
    expect(screen.getByRole('button', { name: '张开' })).toHaveClass('button-preset-basic');
    expect(screen.getByRole('button', { name: '壹' })).toHaveClass('button-preset-number');
    expect(screen.getByRole('button', { name: '复位视角' }).parentElement).toHaveClass('device-twin-tools');
  });
  it('coalesces rapid changes into at most one non-final command per frame', async () => {
    const { controller } = renderControl(2); const slider = await screen.findByRole('slider', { name: '大拇指弯曲 目标' });
    fireEvent.pointerDown(slider); fireEvent.change(slider, { target: { value: '0.1' } }); fireEvent.change(slider, { target: { value: '0.2' } }); await new Promise(resolve => requestAnimationFrame(resolve));
    expect(vi.mocked(controller.setJointTarget).mock.calls).toHaveLength(1); expect(vi.mocked(controller.setJointTarget).mock.calls[0][0]).toMatchObject({ positions: [0.2, 0], finalCommand: false }); fireEvent.pointerUp(slider); await waitFor(() => expect(vi.mocked(controller.setJointTarget).mock.calls.at(-1)?.[0].finalCommand).toBe(true));
  });
  it('does not render the parent or slider for every input, and final cancels stale RAF', async () => {
    const fixtureValue = fixture(2); const { controller } = fixtureValue; let parentRenders = 0; let sliderRenders = 0;
    render(<Profiler id="device" onRender={() => { parentRenders += 1; }}><DeviceControl device={fixtureValue.device} telemetry={telemetry(2)} config={config} capabilities={capabilities(2)} controller={controller} debugMode={false} isPhysicalDevice={true} /></Profiler>);
    const slider = await screen.findByRole('slider', { name: '大拇指弯曲 目标' }); const stableParentRenders = parentRenders;
    fireEvent.pointerDown(slider); fireEvent.change(slider, { target: { value: '0.1' } }); fireEvent.change(slider, { target: { value: '0.9' } });
    expect(parentRenders).toBe(stableParentRenders); expect(sliderRenders).toBe(0); fireEvent.pointerUp(slider); await new Promise(resolve => requestAnimationFrame(resolve));
    expect(vi.mocked(controller.setJointTarget).mock.calls).toHaveLength(1); expect(vi.mocked(controller.setJointTarget).mock.calls[0][0]).toMatchObject({ positions: [0.9, 0], finalCommand: true });
    cleanup(); sliderRenders = 0; render(<Profiler id="slider" onRender={() => { sliderRenders += 1; }}><JointSlider index={0} value={0} disabled={false} onBegin={() => undefined} onInput={() => undefined} onFinish={() => undefined} /></Profiler>); const localInitialRenders = sliderRenders; const localSlider = screen.getByRole('slider', { name: 'J1 目标' }); fireEvent.change(localSlider, { target: { value: '0.1' } }); fireEvent.change(localSlider, { target: { value: '0.2' } }); expect(sliderRenders).toBe(localInitialRenders);
  });
  it('does not let telemetry overwrite a joint while it is being dragged', async () => {
    let listener: ((value: TelemetrySnapshot) => void) | undefined; const source: TelemetryPort = { read: async () => snapshot(2, [0.1, 0.2]), subscribe: next => { listener = next; return () => undefined; } }; const { controller, device } = fixture(2);
    render(<DeviceControl device={device} telemetry={source} config={config} capabilities={capabilities(2)} controller={controller} debugMode={false} isPhysicalDevice={true} />); const slider = await screen.findByRole('slider', { name: '大拇指弯曲 目标' });
    const second = await screen.findByRole('slider', { name: '大拇指横摆 目标' }); fireEvent.pointerDown(slider); fireEvent.change(slider, { target: { value: '0.8' } }); listener?.(snapshot(2, [0.1, 0.9])); expect(slider).toHaveValue('0.8'); await waitFor(() => expect(second).toHaveValue('0.9')); fireEvent.pointerUp(slider);
  });
  it('renders all 25 joints and groups them for compact access', async () => { renderControl(25); expect(await screen.findByRole('slider', { name: 'J25 目标' })).toBeInTheDocument(); expect(screen.getAllByRole('slider').filter(slider => slider.getAttribute('aria-label')?.endsWith('目标'))).toHaveLength(25); });
  it('covers connection actions and disables the feature without a controller', async () => {
    const fixtureValue = renderControl(2); fireEvent.click(await screen.findByRole('button', { name: '重连' })); expect(fixtureValue.controller.reconnect).toHaveBeenCalled(); cleanup(); const isolated = fixture(1);
    render(<DeviceControl device={isolated.device} telemetry={telemetry(1)} config={config} capabilities={capabilities(1)} />); expect(await screen.findByText(/未接入设备控制器/)).toBeInTheDocument(); expect(screen.getByRole('slider', { name: '大拇指弯曲 目标' })).toBeDisabled();
  });
  it('restores the O6 open pose without invoking the safety stop', async () => {
    const fixtureValue = fixture(6);
    render(<DeviceControl device={fixtureValue.device} telemetry={telemetry(6)} config={{ ...config, model: 'O6' }} capabilities={{ ...capabilities(6), model: 'O6' }} controller={fixtureValue.controller} debugMode={false} isPhysicalDevice />);
    fireEvent.click(await screen.findByRole('button', { name: '恢复初始状态' }));
    await waitFor(() => expect(fixtureValue.controller.setJointTarget).toHaveBeenCalled());
    expect(fixtureValue.controller.setJointTarget).toHaveBeenCalledWith(expect.objectContaining({ positions: Array(6).fill(250 / 255), finalCommand: true }));
    expect(fixtureValue.controller.startQuickAction).toHaveBeenCalledWith('open');
    expect(fixtureValue.device.stopAll).not.toHaveBeenCalled();
    expect(screen.queryByText(/停止全部动作是软件锁定/)).not.toBeInTheDocument();
  });
  it('derives quick action and loop mutual exclusion from operation states', async () => {
    const fixtureValue = fixture(1); render(<DeviceControl device={fixtureValue.device} telemetry={telemetry(1)} config={config} capabilities={capabilities(1)} controller={fixtureValue.controller} loops={[{ id: 'cycle', label: '循环' }]} debugMode={false} isPhysicalDevice={true} />);
    fireEvent.click(await screen.findByRole('button', { name: '回到安全位' })); await waitFor(() => expect(fixtureValue.controller.startQuickAction).toHaveBeenCalled());
    fixtureValue.operationListeners.forEach(listener => listener({ schemaVersion: 1, operationId: 'quick-1', kind: 'quick-action', state: 'running', progress: 0.2, detail: '执行中' }));
    await waitFor(() => expect(screen.getByRole('button', { name: '循环' })).toBeDisabled());
    fixtureValue.operationListeners.forEach(listener => listener({ schemaVersion: 1, operationId: 'quick-1', kind: 'quick-action', state: 'completed', progress: 1, detail: '完成' }));
    await waitFor(() => expect(screen.getByRole('button', { name: '循环' })).not.toBeDisabled());
    fixtureValue.operationListeners.forEach(listener => listener({ schemaVersion: 1, operationId: 'loop-1', kind: 'loop', state: 'error', progress: 0.2, detail: '失败' }));
    expect(screen.getByRole('button', { name: '循环' })).not.toBeDisabled();
  });
  it('submits speed and torque only when capabilities provide command lengths', async () => {
    const { controller } = renderControl(2); const applyButtons = await screen.findAllByRole('button', { name: '应用' }); fireEvent.click(applyButtons[0]); fireEvent.click(applyButtons[1]); await waitFor(() => expect(controller.setSpeed).toHaveBeenCalled()); expect(controller.setTorque).toHaveBeenCalled();
    cleanup(); const noTorque = fixture(2); render(<DeviceControl device={noTorque.device} telemetry={telemetry(2)} config={config} capabilities={capabilities(2, 2, null)} controller={noTorque.controller} debugMode={false} isPhysicalDevice={true} />); expect(await screen.findByRole('slider', { name: '扭矩' })).toBeDisabled();
  });
  it('disables all controls when not connected and debug mode is off', async () => {
    const { controller } = fixture(2);
    const o6Capabilities = { ...capabilities(2), model: 'O6' as const };
    render(<DeviceControl device={fixture(2).device} telemetry={telemetry(2)} config={{ ...config, model: 'O6' }} capabilities={o6Capabilities} controller={controller} debugMode={false} isPhysicalDevice={false} />);
    expect(await screen.findByText(/未连接机械手，设备控制不可用/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '连接' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '断开' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '重连' })).toBeDisabled();
    expect(screen.getByRole('slider', { name: '大拇指弯曲 目标' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '张开' })).toBeDisabled();
    expect(screen.getByRole('slider', { name: '速度' })).toBeDisabled();
    expect(screen.getByRole('slider', { name: '扭矩' })).toBeDisabled();
    expect(screen.getByText('实时关节曲线')).toBeInTheDocument();
    expect(screen.getByText('遥测未接入')).toBeInTheDocument();
  });
});
