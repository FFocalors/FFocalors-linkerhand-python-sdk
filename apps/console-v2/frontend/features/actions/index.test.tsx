import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ActionCenter, type ActionController, type ActionControllerState, type LoopSequence } from './index';
import type { ActionPort, ActionRecording, DeviceCapabilities, MotionPort, TelemetryPort } from '../../shared/contracts';
import { O6_BASIC_ACTIONS, O6_NUMBER_ACTIONS, O6_JOINT_NAMES } from '../device-control';

const recording: ActionRecording = { schemaVersion: 1, id: 'custom-1', name: '测试动作', frames: [], durationMs: 1000, steps: 2, updatedAt: 'now' };
const recording2: ActionRecording = { schemaVersion: 1, id: 'custom-2', name: '测试动作2', frames: [], durationMs: 2000, steps: 3, updatedAt: 'now' };
const actions: ActionPort = { list: vi.fn(async () => [recording, recording2]), delete: vi.fn(async () => undefined) };
const motion: MotionPort = { getOperation: vi.fn(async () => ({ schemaVersion: 1, operationId: 'motion', kind: 'motion', state: 'idle' as const, progress: 0, detail: null })), runAction: vi.fn(async () => undefined), pause: vi.fn(async () => undefined) };

function controller() {
  let listener: ((state: ActionControllerState) => void) | undefined;
  const value = { state: { state: 'idle', progress: 0 } as ActionControllerState } as ActionController & { state: ActionControllerState };
  value.startRecording = vi.fn(async () => { value.state = { state: 'recording', progress: 0 }; listener?.(value.state); });
  value.pauseRecording = vi.fn(async () => undefined); value.resumeRecording = vi.fn(async () => undefined);
  value.finishRecording = vi.fn(async () => { value.state = { state: 'idle', progress: 0 }; listener?.(value.state); });
  value.cancelRecording = vi.fn(async () => undefined);
  value.play = vi.fn(async (actionId: string) => { value.state = { state: 'playing', actionId, progress: 12 }; listener?.(value.state); });
  value.pausePlayback = vi.fn(async () => undefined); value.resumePlayback = vi.fn(async () => undefined);
  value.stop = vi.fn(async () => undefined);
  const playLoop = vi.fn(async (loop: LoopSequence, options: { speed: number }) => {
    for (const actionId of loop.actionIds) {
      await value.play(actionId, { speed: options.speed, loopCount: 1 });
    }
    value.state = { state: 'idle', progress: 0 };
    listener?.(value.state);
  });
  value.playLoop = playLoop;
  const stopLoop = vi.fn(async () => { value.state = { state: 'idle', progress: 0 }; listener?.(value.state); });
  value.stopLoop = stopLoop;
  value.getState = vi.fn(async () => value.state);
  value.subscribe = vi.fn(next => { listener = next; return () => { listener = undefined; }; });
  return { port: value, playLoop, stopLoop };
}

const allBuiltinActions = [...O6_BASIC_ACTIONS, ...O6_NUMBER_ACTIONS];

const capabilities: DeviceCapabilities = {
  schemaVersion: 1,
  deviceId: 'test-device',
  model: 'O6',
  hand: 'right',
  transport: { type: 'rs485', port: 'COM3', baudrate: 115200 },
  jointCount: 6,
  position: { available: true, range: { min: 0, max: 255 }, length: 6 },
  speed: { available: true, range: { min: 0, max: 255 }, length: 6 },
  current: { available: true, range: { min: 0, max: 255 }, length: 6 },
  torque: { available: true, range: { min: 0, max: 255 }, length: 6 },
  touch: { available: false, range: { min: 0, max: 255 }, length: 0 },
  speedCommandLength: 6,
  currentCommandLength: null,
  torqueCommandLength: 6,
  supportedOperations: ['connect', 'disconnect'],
};

function telemetry(initialValues: number[] = [128, 64, 192, 0, 255, 32]): TelemetryPort {
  let listener: ((snapshot: { rawPosition: number[] }) => void) | undefined;
  const snapshot = () => ({
    schemaVersion: 1,
    deviceId: 'test-device',
    sequence: 0,
    monotonicTimeMs: Date.now(),
    positions: initialValues.map(v => v / 255),
    rawPosition: [...initialValues],
    rawCurrent: Array(6).fill(0),
    rawSpeed: Array(6).fill(0),
    rawTouch: Array(6).fill(0),
    connected: true,
  });
  return {
    read: vi.fn(async () => snapshot()),
    subscribe: vi.fn((cb) => { listener = cb; return () => { listener = undefined; }; }),
  };
}

describe('ActionCenter controller boundary', () => {
  it('disables execution when controller is not wired', async () => {
    render(<ActionCenter actions={actions} motion={motion} locked={false} />);
    expect(await screen.findByRole('status')).toHaveTextContent('尚未接线');
    expect(screen.getByRole('button', { name: /新建动作/ })).toBeDisabled();
    const runButtons = screen.getAllByRole('button', { name: /运行/ });
    expect(runButtons[0]).toBeDisabled();
  });
  it('calls recording start and finish through the controller', async () => {
    const user = userEvent.setup(); const { port } = controller();
    render(<ActionCenter actions={actions} motion={motion} locked={false} controller={port} />);
    await user.click(screen.getByRole('button', { name: /新建动作/ }));
    await user.type(screen.getByLabelText('动作名称'), '新的动作');
    await user.click(screen.getByRole('button', { name: '开始录制' }));
    expect(port.startRecording).toHaveBeenCalledWith('新的动作');
    await user.click(screen.getByRole('button', { name: '完成录制' }));
    expect(port.finishRecording).toHaveBeenCalled();
  });
  it('passes speed and finite loop and stops through the controller', async () => {
    const user = userEvent.setup(); const { port } = controller();
    render(<ActionCenter actions={actions} motion={motion} locked={false} controller={port} />);
    await user.selectOptions(screen.getByLabelText('倍速'), '2'); await user.selectOptions(screen.getByLabelText('循环'), '3');
    await user.click(screen.getAllByRole('button', { name: /运行/ })[0]);
    expect(port.play).toHaveBeenCalledWith('custom-1', { speed: 2, loopCount: 3 });
    await user.click(screen.getByRole('button', { name: '停止' }));
    expect(port.stop).toHaveBeenCalled();
  });
});

describe('ActionCenter loop feature', () => {
  it('multi-selects actions and creates a loop', async () => {
    const user = userEvent.setup(); const { port } = controller();
    render(<ActionCenter actions={actions} motion={motion} locked={false} controller={port} />);
    await user.click(screen.getByRole('button', { name: /选择动作创建循环/ }));
    await user.click(screen.getByRole('checkbox', { name: '选择 测试动作' }));
    await user.click(screen.getByRole('checkbox', { name: '选择 测试动作2' }));
    await user.click(screen.getByRole('button', { name: /创建循环/ }));
    await user.type(screen.getByLabelText('循环名称'), '我的循环');
    await user.click(screen.getByRole('button', { name: '确认' }));
    expect(screen.getByText('我的循环')).toBeDefined();
    expect(screen.getByText('2 个动作')).toBeDefined();
  });

  it('runs a loop and verifies actions are called in order', async () => {
    const user = userEvent.setup(); const { port, playLoop } = controller();
    render(<ActionCenter actions={actions} motion={motion} locked={false} controller={port} />);
    await user.click(screen.getByRole('button', { name: /选择动作创建循环/ }));
    await user.click(screen.getByRole('checkbox', { name: '选择 测试动作' }));
    await user.click(screen.getByRole('checkbox', { name: '选择 测试动作2' }));
    await user.click(screen.getByRole('button', { name: /创建循环/ }));
    await user.type(screen.getByLabelText('循环名称'), '顺序循环');
    await user.click(screen.getByRole('button', { name: '确认' }));
    await user.click(screen.getByRole('button', { name: '▶ 运行' }));
    await waitFor(() => expect(playLoop).toHaveBeenCalled());
    const loopArg = playLoop.mock.calls[0][0] as LoopSequence;
    expect(loopArg.actionIds).toEqual(['custom-1', 'custom-2']);
    await waitFor(() => expect(port.play).toHaveBeenCalledTimes(2));
    expect(port.play).toHaveBeenNthCalledWith(1, 'custom-1', { speed: 1, loopCount: 1 });
    expect(port.play).toHaveBeenNthCalledWith(2, 'custom-2', { speed: 1, loopCount: 1 });
  });

  it('deletes a loop', async () => {
    const user = userEvent.setup(); const { port } = controller();
    render(<ActionCenter actions={actions} motion={motion} locked={false} controller={port} />);
    await user.click(screen.getByRole('button', { name: /选择动作创建循环/ }));
    await user.click(screen.getByRole('checkbox', { name: '选择 测试动作' }));
    await user.click(screen.getByRole('checkbox', { name: '选择 测试动作2' }));
    await user.click(screen.getByRole('button', { name: /创建循环/ }));
    await user.type(screen.getByLabelText('循环名称'), '待删除');
    await user.click(screen.getByRole('button', { name: '确认' }));
    expect(screen.getByText('待删除')).toBeDefined();
    await user.click(screen.getByRole('button', { name: '🗑 删除' }));
    expect(screen.queryByText('待删除')).toBeNull();
  });

  it('cancels loop creation', async () => {
    const user = userEvent.setup(); const { port } = controller();
    render(<ActionCenter actions={actions} motion={motion} locked={false} controller={port} />);
    await user.click(screen.getByRole('button', { name: /选择动作创建循环/ }));
    await user.click(screen.getByRole('checkbox', { name: '选择 测试动作' }));
    await user.click(screen.getByRole('checkbox', { name: '选择 测试动作2' }));
    await user.click(screen.getByRole('button', { name: /创建循环/ }));
    const cancelButtons = screen.getAllByRole('button', { name: '取消' });
    await user.click(cancelButtons[0]);
    expect(screen.queryByLabelText('循环名称')).toBeNull();
    expect(port.playLoop).not.toHaveBeenCalled();
  });
});

describe('ActionCenter preset sync and joint slider', () => {
  it('renders built-in presets from device-control on the builtin tab', async () => {
    const user = userEvent.setup();
    const { port } = controller();
    const telem = telemetry();
    render(
      <ActionCenter
        actions={actions}
        motion={motion}
        locked={false}
        controller={port}
        capabilities={capabilities}
        telemetry={telem}
      />
    );
    await user.click(screen.getByRole('button', { name: '内置预设' }));

    // All 9 built-in preset labels should appear inside .preset-button elements
    const presetButtons = document.querySelectorAll('.preset-button');
    expect(presetButtons.length).toBe(allBuiltinActions.length);
    for (const action of allBuiltinActions) {
      const found = Array.from(presetButtons).some(btn => (btn as HTMLElement).textContent?.includes(action.label));
      expect(found).toBe(true);
    }
    // Basic and number sections headers should appear
    expect(screen.getByText('基本预设')).toBeDefined();
    expect(screen.getByText('数字预设')).toBeDefined();
    // Clicking a built-in preset should call controller.play
    const openButton = Array.from(presetButtons).find(btn => (btn as HTMLElement).textContent?.includes('张开'));
    expect(openButton).toBeDefined();
    await user.click(openButton as HTMLElement);
    expect(port.play).toHaveBeenCalledWith('open', { speed: 1, loopCount: 1 });
  });

  it('merges homepage custom presets with local actions on the custom tab', async () => {
    const user = userEvent.setup();
    const homepagePresets = [
      { id: 'hp-1', label: '首页预设A', positions: [0.5, 0.5, 0.5, 0.5, 0.5, 0.5], category: 'custom' as const },
      { id: 'hp-2', label: '首页预设B', positions: [0, 0, 0, 0, 0, 0], category: 'custom' as const },
    ];
    const { port } = controller();
    render(
      <ActionCenter
        actions={actions}
        motion={motion}
        locked={false}
        controller={port}
        customPresets={homepagePresets}
      />
    );
    await user.click(screen.getByRole('button', { name: '自定义' }));

    // Homepage presets should appear with 首页 badge
    expect(screen.getByText('首页预设A')).toBeDefined();
    expect(screen.getByText('首页预设B')).toBeDefined();
    const homepageBadges = screen.getAllByText('首页');
    expect(homepageBadges.length).toBeGreaterThanOrEqual(2);

    // Local recordings should appear with 自定义 badge
    const localBadges = screen.getAllByText('自定义');
    expect(localBadges.length).toBeGreaterThanOrEqual(2);
  });

  it('shows joint slider card when capabilities are provided', async () => {
    const telem = telemetry([128, 64, 192, 0, 255, 32]);
    const { port } = controller();
    render(
      <ActionCenter
        actions={actions}
        motion={motion}
        locked={false}
        controller={port}
        capabilities={capabilities}
        telemetry={telem}
      />
    );
    // Card heading should be present
    expect(screen.getByText('关节位置')).toBeDefined();
    // Read-only badge should appear
    expect(screen.getByText('只读')).toBeDefined();
    // All 6 joint names from O6_JOINT_NAMES should appear (verified by sliderItems count below)
    const sliderItems = document.querySelectorAll('.joint-slider-item');
    expect(sliderItems.length).toBe(O6_JOINT_NAMES.length);
    // Telemetry values should be normalized (128/255 ≈ 0.5 → 50%)
    await waitFor(() => expect(screen.getByText('50%')).toBeDefined());
    expect(screen.getByText('25%')).toBeDefined();
    expect(screen.getByText('75%')).toBeDefined();
    expect(screen.getByText('0%')).toBeDefined();
    expect(screen.getByText('100%')).toBeDefined();
    expect(screen.getByText('13%')).toBeDefined();
  });
});
