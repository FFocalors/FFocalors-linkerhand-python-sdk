import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ActionCenter, type ActionController, type ActionControllerState, type PosePreset, type ProgrammedAction } from './index';
import type { ActionPort, ActionRecording, DeviceCapabilities, MotionPort, TelemetryPort } from '../../shared/contracts';
import { O6_BASIC_ACTIONS, O6_NUMBER_ACTIONS, O6_JOINT_NAMES } from '../device-control';

const recording: ActionRecording = { schemaVersion: 1, id: 'legacy-1', name: '旧录制动作', frames: [], durationMs: 1000, steps: 2, updatedAt: 'now' };
const actions: ActionPort = { list: vi.fn(async () => [recording]), delete: vi.fn(async () => undefined) };
const motion: MotionPort = { getOperation: vi.fn(async () => ({ schemaVersion: 1, operationId: 'motion', kind: 'motion', state: 'idle' as const, progress: 0, detail: null })), runAction: vi.fn(async () => undefined), pause: vi.fn(async () => undefined) };

function controller() {
  let listener: ((state: ActionControllerState) => void) | undefined;
  const value = {
    state: { state: 'idle', progress: 0 } as ActionControllerState,
    getState: vi.fn(async () => value.state),
    subscribe: vi.fn((next: (state: ActionControllerState) => void) => { listener = next; return () => { listener = undefined; }; }),
    play: vi.fn(async (actionId: string) => { value.state = { state: 'playing', actionId, progress: 12 }; listener?.(value.state); }),
    playPose: vi.fn(async (pose: PosePreset) => { value.state = { state: 'playing', actionId: pose.id, progress: 12 }; listener?.(value.state); }),
    playProgrammedAction: vi.fn(async (action: ProgrammedAction) => { value.state = { state: 'playing', actionId: action.id, progress: 12 }; listener?.(value.state); }),
    playLoop: vi.fn(async () => undefined), stopLoop: vi.fn(async () => undefined), stop: vi.fn(async () => undefined),
    startRecording: vi.fn(async () => undefined), pauseRecording: vi.fn(async () => undefined), resumeRecording: vi.fn(async () => undefined), finishRecording: vi.fn(async () => undefined), cancelRecording: vi.fn(async () => undefined),
    pausePlayback: vi.fn(async () => undefined), resumePlayback: vi.fn(async () => undefined),
  } as unknown as ActionController & { playPose: ReturnType<typeof vi.fn>; playProgrammedAction: ReturnType<typeof vi.fn>; play: ReturnType<typeof vi.fn>; state: ActionControllerState };
  return value;
}

const capabilities: DeviceCapabilities = {
  schemaVersion: 1, deviceId: 'test-device', model: 'O6', hand: 'right', transport: { type: 'rs485', port: 'COM3', baudrate: 115200 }, jointCount: 6,
  position: { available: true, range: { min: 0, max: 255 }, length: 6 }, speed: { available: true, range: { min: 0, max: 255 }, length: 6 }, current: { available: true, range: { min: 0, max: 255 }, length: 6 }, torque: { available: true, range: { min: 0, max: 255 }, length: 6 }, touch: { available: false, range: { min: 0, max: 255 }, length: 0 }, speedCommandLength: 6, currentCommandLength: null, torqueCommandLength: 6, supportedOperations: ['connect', 'disconnect'],
};

function telemetry(values = [128, 64, 192, 0, 255, 32]): TelemetryPort {
  const snapshot = () => ({ schemaVersion: 1, deviceId: 'test-device', sequence: 0, monotonicTimeMs: Date.now(), positions: values.map(v => v / 255), rawPosition: values, rawCurrent: Array(6).fill(0), rawSpeed: Array(6).fill(0), rawTouch: Array(6).fill(0), connected: true });
  return { read: vi.fn(async () => snapshot()), subscribe: vi.fn(() => () => undefined) };
}

describe('ActionCenter entry and pose model', () => {
  it('opens pose composer from 新建动作 and excludes legacy recordings from candidates', async () => {
    const user = userEvent.setup(); const port = controller();
    render(<ActionCenter actions={actions} motion={motion} locked={false} controller={port} />);
    await user.click(screen.getByRole('button', { name: /新建动作/ }));
    expect(screen.getByText(/候选仅包含静止姿态/)).toBeDefined();
    expect(screen.getByRole('checkbox', { name: '选择 张开' })).toBeDefined();
    expect(screen.queryByRole('checkbox', { name: '选择 旧录制动作' })).toBeNull();
    expect(screen.getByText('录制兼容区')).toBeDefined();
  });

  it('creates a programmed action in selection order with complete playback DTO', async () => {
    const user = userEvent.setup(); const port = controller(); const onChange = vi.fn();
    render(<ActionCenter actions={actions} motion={motion} locked={false} controller={port} onProgrammedActionsChange={onChange} />);
    await user.click(screen.getByRole('button', { name: /新建动作/ }));
    await user.click(screen.getByRole('checkbox', { name: '选择 握拳' }));
    await user.click(screen.getByRole('checkbox', { name: '选择 张开' }));
    await user.click(screen.getByRole('button', { name: '编排动作' }));
    await user.type(screen.getByLabelText('动作名称'), '迎宾动作');
    await user.selectOptions(document.querySelector('#composer-mode') as HTMLSelectElement, 'single');
    await user.selectOptions(document.querySelector('#composer-speed') as HTMLSelectElement, '0.75');
    await user.selectOptions(document.querySelector('#composer-direction') as HTMLSelectElement, 'reverse');
    await user.click(screen.getByRole('button', { name: '保存动作' }));
    expect(onChange).toHaveBeenCalledTimes(1);
    const saved = onChange.mock.calls[0][0][0] as ProgrammedAction;
    expect(saved.kind).toBe('sequence');
    expect(saved.poseIds).toEqual(['fist', 'open']);
    expect(saved.poses.map(pose => pose.id)).toEqual(['fist', 'open']);
    expect(saved.playback).toEqual({ mode: 'single', speed: 0.75, direction: 'reverse', loopCount: 1 });
    await user.click(document.querySelector('.programmed-actions-card .button') as HTMLElement);
    expect(port.playProgrammedAction).toHaveBeenCalledWith(saved, saved.playback);
  });

  it('executes a pose with complete pose DTO through playPose', async () => {
    const user = userEvent.setup(); const port = controller();
    render(<ActionCenter actions={actions} motion={motion} locked={false} controller={port} />);
    await waitFor(() => expect(screen.getByText('张开')).toBeDefined());
    const buttons = screen.getAllByRole('button', { name: '播放' });
    await user.click(buttons[0]);
    expect(port.playPose).toHaveBeenCalledWith(expect.objectContaining({ kind: 'pose', id: 'open', name: '张开' }), expect.objectContaining({ mode: 'loop', speed: 1, direction: 'forward', loopCount: 1 }));
  });
});

describe('ActionCenter controlled persistence and collections', () => {
  it('shows all nine builtins plus homepage/local poses, while actions remain separate', async () => {
    const local = [{ id: 'local-pose', label: '本地姿态', category: 'custom' as const, positions: [0, 0, 0, 0, 0, 0] }];
    const action: ProgrammedAction = { kind: 'sequence', id: 'program-1', name: '已保存动作', source: 'local', poseIds: ['open'], poses: [{ kind: 'pose', id: 'open', name: '张开', source: 'builtin' }], playback: { mode: 'loop', speed: 1, direction: 'forward', loopCount: 3 }, createdAt: 'now' };
    render(<ActionCenter actions={actions} motion={motion} locked={false} localPresets={local} programmedActions={[action]} customPresets={[{ id: 'home-pose', label: '首页姿态', category: 'custom', positions: [0, 0, 0, 0, 0, 0] }]} />);
    await waitFor(() => expect(screen.getByText('首页姿态')).toBeDefined());
    expect(document.querySelectorAll('.actions-table-row').length).toBe([...O6_BASIC_ACTIONS, ...O6_NUMBER_ACTIONS].length + 2);
    expect(screen.getByText('已保存动作')).toBeDefined();
    expect(screen.queryByText('旧录制动作')).toBeDefined();
  });

  it('updates controlled local poses and does not call homepage callbacks', async () => {
    const user = userEvent.setup(); const onLocal = vi.fn(); const local = [{ id: 'local-pose', label: '旧本地姿态', category: 'custom' as const, positions: [0, 0, 0, 0, 0, 0] }];
    render(<ActionCenter actions={actions} motion={motion} locked={false} capabilities={capabilities} telemetry={telemetry()} localPresets={local} onLocalPresetsChange={onLocal} customPresets={[{ id: 'home-pose', label: '首页姿态', category: 'custom', positions: [0, 0, 0, 0, 0, 0] }]} />);
    await user.click(screen.getByRole('button', { name: /保存当前姿态/ }));
    await user.type(screen.getByLabelText('姿态名称'), '新本地姿态');
    await user.click(screen.getByRole('button', { name: '保存到动作中心' }));
    expect(onLocal).toHaveBeenCalledWith([...local, expect.objectContaining({ label: '新本地姿态' })]);
    expect(screen.getByText('首页姿态')).toBeDefined();
  });
});

describe('ActionCenter layout and playback controls', () => {
  it('renders all joint sliders using telemetry and exposes mode/direction controls', async () => {
    render(<ActionCenter actions={actions} motion={motion} locked={false} controller={controller()} capabilities={capabilities} telemetry={telemetry()} />);
    expect(document.querySelectorAll('.joint-slider-item').length).toBe(O6_JOINT_NAMES.length);
    expect(screen.getByLabelText('播放模式')).toBeDefined();
    expect(screen.getByLabelText('方向')).toBeDefined();
    await waitFor(() => expect(screen.getByText('50%')).toBeDefined());
  });

  it('keeps an editable debug draft separate from telemetry and syncs the virtual hand', async () => {
    const user = userEvent.setup(); const onVirtual = vi.fn(); const onLocal = vi.fn();
    render(<ActionCenter actions={actions} motion={motion} locked={false} controller={controller()} capabilities={capabilities} telemetry={telemetry()} debugMode onVirtualPoseChange={onVirtual} onLocalPresetsChange={onLocal} />);
    const slider = await screen.findByLabelText('大拇指弯曲 目标');
    expect(slider).not.toBeDisabled();
    fireEvent.change(slider, { target: { value: '0.75' } });
    await user.click(screen.getByRole('button', { name: /保存当前姿态/ }));
    await user.type(screen.getByLabelText('姿态名称'), '调试姿态');
    await user.click(screen.getByRole('button', { name: '保存到动作中心' }));
    expect(onLocal).toHaveBeenCalledWith(expect.arrayContaining([expect.objectContaining({ label: '调试姿态', positions: expect.arrayContaining([0.75]) })]));
    expect(onVirtual).toHaveBeenCalledWith(expect.arrayContaining([0.75]));
  });

  it('requires preview then apply before sending a pose to physical hardware', async () => {
    const user = userEvent.setup(); const port = controller();
    render(<ActionCenter actions={actions} motion={motion} locked={false} controller={port} isPhysicalDevice />);
    await waitFor(() => expect(screen.getByText('张开')).toBeDefined());
    await user.click(screen.getAllByRole('button', { name: '预览' })[0]);
    expect(port.playPose).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: '应用到设备' }));
    expect(port.playPose).toHaveBeenCalledTimes(1);
  });

  it('does not execute when a real device is explicitly disconnected', async () => {
    const user = userEvent.setup(); const port = controller();
    render(<ActionCenter actions={actions} motion={motion} locked={false} controller={port} debugMode={false} isPhysicalDevice={false} />);
    await waitFor(() => expect(screen.getByText(/未连接真实机械手/)).toBeDefined());
    const play = screen.getAllByRole('button', { name: '播放' })[0];
    expect(play).toBeDisabled();
    await user.click(play);
    expect(port.playPose).not.toHaveBeenCalled();
  });
});
