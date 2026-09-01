import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ActionCenter, type ActionController, type ActionControllerState, type PosePreset, type ProgrammedAction } from './index';
import type { ActionPort, DeviceCapabilities, MotionPort, TelemetryPort } from '../../shared/contracts';
import { O6_BASIC_ACTIONS, O6_NUMBER_ACTIONS, O6_JOINT_NAMES } from '../../shared/action-models';

const actions: ActionPort = { list: vi.fn(async () => []), delete: vi.fn(async () => undefined) };
const motion: MotionPort = { getOperation: vi.fn(async () => ({ schemaVersion: 1, operationId: 'motion', kind: 'motion', state: 'idle' as const, progress: 0, detail: null })), runAction: vi.fn(async () => undefined), pause: vi.fn(async () => undefined) };

function controller() {
  let listener: ((state: ActionControllerState) => void) | undefined;
  const value = {
    state: { state: 'idle', progress: 0 } as ActionControllerState,
    getState: vi.fn(async () => value.state),
    subscribe: vi.fn((next: (state: ActionControllerState) => void) => { listener = next; return () => { listener = undefined; }; }),
    play: vi.fn(async (actionId: string) => { value.state = { state: 'playing', actionId, progress: 12 }; listener?.(value.state); }),
    playPose: vi.fn(async (pose: PosePreset) => { value.state = { state: 'playing', actionId: pose.id, progress: 12 }; listener?.(value.state); }),
    applyPose: vi.fn(async (pose: PosePreset) => { value.state = { state: 'playing', actionId: pose.id, progress: 12 }; listener?.(value.state); }),
    playProgrammedAction: vi.fn(async (action: ProgrammedAction) => { value.state = { state: 'playing', actionId: action.id, progress: 12 }; listener?.(value.state); }),
    playLoop: vi.fn(async () => undefined), stopLoop: vi.fn(async () => undefined), stop: vi.fn(async () => undefined),
    startRecording: vi.fn(async () => undefined), pauseRecording: vi.fn(async () => undefined), resumeRecording: vi.fn(async () => undefined), finishRecording: vi.fn(async () => undefined), cancelRecording: vi.fn(async () => undefined),
    pausePlayback: vi.fn(async () => undefined), resumePlayback: vi.fn(async () => undefined),
  } as unknown as ActionController & { playPose: ReturnType<typeof vi.fn>; applyPose: ReturnType<typeof vi.fn>; playProgrammedAction: ReturnType<typeof vi.fn>; play: ReturnType<typeof vi.fn>; state: ActionControllerState };
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

describe('ActionCenter pose-to-action workflow', () => {
  it('uses a two-pane editor and removes the recording compatibility surface', async () => {
    const user = userEvent.setup(); const port = controller();
    render(<ActionCenter actions={actions} motion={motion} locked={false} controller={port} />);
    expect(document.querySelector('.actions-page')).toBeTruthy();
    expect(document.querySelector('.actions-scroll-region')).toBeTruthy();
    expect(document.querySelector('.actions-workspace')).toBeTruthy();
    expect(document.querySelector('.actions-scroll-region .tip-card')).toBeTruthy();
    expect(screen.getByRole('heading', { name: '姿态库' })).toBeDefined();
    expect(screen.getByRole('heading', { name: '动作编辑' })).toBeDefined();
    expect(screen.queryByText('录制兼容区')).toBeNull();
    await user.click(screen.getByRole('button', { name: /新建动作/ }));
    expect(screen.getByRole('checkbox', { name: '选择 张开' })).toBeDefined();
    expect(screen.getByText(/请在左侧勾选姿态/)).toBeDefined();
  });

  it('keeps lower pose rows reachable after selection instead of clipping the page', async () => {
    const user = userEvent.setup();
    const lowerPoses = Array.from({ length: 40 }, (_, index) => ({ id: `custom-${index}`, label: `自定义姿态 ${index + 1}`, category: 'custom' as const, positions: Array(6).fill(index / 40) }));
    render(<ActionCenter actions={actions} motion={motion} locked={false} controller={controller()} customPresets={lowerPoses} />);
    await user.click(screen.getByRole('button', { name: /新建动作/ }));
    const lowerRow = screen.getByRole('checkbox', { name: '选择 自定义姿态 40' });
    await user.click(lowerRow);
    expect(lowerRow).toBeChecked();
    expect(document.querySelector('.actions-page')).toBeTruthy();
    expect(document.querySelector('.actions-scroll-region')?.querySelector('.tip-card')).toBeTruthy();
  });

  it('adds selected poses to the right sequence and saves complete playback options', async () => {
    const user = userEvent.setup(); const port = controller(); const onChange = vi.fn();
    render(<ActionCenter actions={actions} motion={motion} locked={false} controller={port} onProgrammedActionsChange={onChange} />);
    await user.click(screen.getByRole('button', { name: /新建动作/ }));
    await user.click(screen.getByRole('checkbox', { name: '选择 握拳' }));
    await user.click(screen.getByRole('checkbox', { name: '选择 张开' }));
    await user.click(screen.getByRole('button', { name: /添加到动作/ }));
    await user.type(screen.getByLabelText('动作名称'), '迎宾动作');
    await user.selectOptions(document.querySelector('#composer-mode') as HTMLSelectElement, 'single');
    await user.selectOptions(document.querySelector('#composer-speed') as HTMLSelectElement, '0.75');
    await user.selectOptions(document.querySelector('#composer-direction') as HTMLSelectElement, 'reverse');
    await user.click(screen.getByRole('button', { name: '保存动作' }));
    const saved = onChange.mock.calls[0][0][0] as ProgrammedAction;
    expect(saved.poseIds).toEqual(['fist', 'open']);
    expect(saved.poses.map(pose => pose.id)).toEqual(['fist', 'open']);
    expect(saved.playback).toEqual({ mode: 'single', speed: 0.75, direction: 'reverse', loopCount: 1 });
  });

  it('supports explicit sequence reordering/removal and never exposes speed above 1x', async () => {
    const user = userEvent.setup();
    render(<ActionCenter actions={actions} motion={motion} locked={false} controller={controller()} />);
    await user.click(screen.getByRole('button', { name: /新建动作/ }));
    await user.click(screen.getByRole('checkbox', { name: '选择 握拳' }));
    await user.click(screen.getByRole('checkbox', { name: '选择 张开' }));
    await user.click(screen.getByRole('button', { name: /添加到动作/ }));
    const first = screen.getByRole('button', { name: '下移 握拳' });
    await user.click(first);
    expect(screen.getAllByText(/^[12]\. (握拳|张开)$/).map(node => node.textContent)).toEqual(['1. 张开', '2. 握拳']);
    await user.click(screen.getAllByRole('button', { name: '移除' })[0]);
    expect(screen.getAllByText(/^[12]\. (握拳|张开)$/).map(node => node.textContent)).toEqual(['1. 握拳']);
    const speeds = Array.from((document.querySelector('#composer-speed') as HTMLSelectElement).options).map(option => Number(option.value));
    expect(Math.max(...speeds)).toBeLessThanOrEqual(1);
  });
});

describe('ActionCenter pose editor', () => {
  it('explains why a pose cannot be saved and saves it as a custom pose', async () => {
    const user = userEvent.setup(); const onLocal = vi.fn();
    render(<ActionCenter actions={actions} motion={motion} locked={false} controller={controller()} capabilities={capabilities} telemetry={telemetry()} onLocalPresetsChange={onLocal} />);
    await user.click(screen.getByRole('button', { name: /保存当前姿态/ }));
    const save = screen.getByRole('button', { name: '保存到自定义姿态' });
    expect(save).toBeDisabled();
    expect(screen.getByText('请输入姿态名称')).toBeDefined();
    await user.type(screen.getByLabelText('姿态名称'), '准备姿态');
    await waitFor(() => expect(save).not.toBeDisabled());
    await user.click(save);
    expect(onLocal).toHaveBeenCalledWith([expect.objectContaining({ label: '准备姿态', category: 'custom' })]);
    expect(screen.queryByRole('button', { name: '保存到动作中心' })).toBeNull();
  });

  it('keeps an editable debug draft separate from telemetry and syncs the virtual hand', async () => {
    const onVirtual = vi.fn();
    render(<ActionCenter actions={actions} motion={motion} locked={false} controller={controller()} capabilities={capabilities} telemetry={telemetry()} debugMode onVirtualPoseChange={onVirtual} />);
    const slider = await screen.findByLabelText('大拇指弯曲 目标');
    fireEvent.change(slider, { target: { value: '0.75' } });
    await waitFor(() => expect(onVirtual).toHaveBeenCalledWith(expect.arrayContaining([0.75])));
  });

  it('streams the draft pose to a physical hand while dragging and commits on release', async () => {
    const port = controller();
    const streamPose = vi.fn(async (_pose: PosePreset, _finalCommand: boolean) => undefined);
    const wired = { ...port, streamPose };
    render(<ActionCenter actions={actions} motion={motion} locked={false} controller={wired} capabilities={capabilities} telemetry={telemetry()} isPhysicalDevice />);
    const slider = await screen.findByLabelText('大拇指弯曲 目标');
    fireEvent.change(slider, { target: { value: '0.75' } });
    await waitFor(() => expect(streamPose).toHaveBeenCalled());
    const dragCall = streamPose.mock.calls[streamPose.mock.calls.length - 1]!;
    expect(dragCall[0].positions).toEqual(expect.arrayContaining([0.75]));
    expect(dragCall[1]).toBe(false);
    fireEvent.pointerUp(slider);
    await waitFor(() => expect(streamPose.mock.calls[streamPose.mock.calls.length - 1]![1]).toBe(true));
  });

  it('does not stream draft poses when no physical hand is connected', async () => {
    const port = controller();
    const streamPose = vi.fn(async (_pose: PosePreset, _finalCommand: boolean) => undefined);
    const wired = { ...port, streamPose };
    render(<ActionCenter actions={actions} motion={motion} locked={false} controller={wired} capabilities={capabilities} telemetry={telemetry()} debugMode />);
    const slider = await screen.findByLabelText('大拇指弯曲 目标');
    fireEvent.change(slider, { target: { value: '0.75' } });
    // Give a rAF-frame's worth of time for any (incorrect) scheduled stream.
    await waitFor(() => expect(streamPose).not.toHaveBeenCalled(), { timeout: 120 });
    expect(streamPose).not.toHaveBeenCalled();
  });
});

describe('ActionCenter collections and safety', () => {
  it('keeps built-in/custom filters and separates programmed actions', async () => {
    const local = [{ id: 'local-pose', label: '本地姿态', category: 'custom' as const, positions: [0, 0, 0, 0, 0, 0] }];
    const action: ProgrammedAction = { kind: 'sequence', id: 'program-1', name: '已保存动作', source: 'local', poseIds: ['open'], poses: [{ kind: 'pose', id: 'open', name: '张开', source: 'builtin' }], playback: { mode: 'loop', speed: 1, direction: 'forward', loopCount: 3 }, createdAt: 'now' };
    const user = userEvent.setup();
    render(<ActionCenter actions={actions} motion={motion} locked={false} localPresets={local} programmedActions={[action]} customPresets={[{ id: 'home-pose', label: '首页姿态', category: 'custom', positions: [0, 0, 0, 0, 0, 0] }]} />);
    expect(document.querySelectorAll('.actions-table-row').length).toBe([...O6_BASIC_ACTIONS, ...O6_NUMBER_ACTIONS].length + 2);
    await user.click(screen.getByRole('button', { name: '自定义姿态' }));
    expect(screen.getByText('首页姿态')).toBeDefined();
    expect(screen.getByText('本地姿态')).toBeDefined();
    expect(screen.getByRole('heading', { name: '已保存动作' })).toBeDefined();
  });

  it('requires preview then apply before sending a pose to physical hardware', async () => {
    const user = userEvent.setup(); const port = controller();
    render(<ActionCenter actions={actions} motion={motion} locked={false} controller={port} isPhysicalDevice />);
    await user.click(screen.getAllByRole('button', { name: '预览' })[0]);
    expect(port.playPose).not.toHaveBeenCalled();
    expect(port.applyPose).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: '应用到设备' }));
    expect(port.applyPose).toHaveBeenCalledTimes(1);
  });

  it('keeps the physical preview gate when debug mode is enabled', async () => {
    const user = userEvent.setup(); const port = controller();
    render(<ActionCenter actions={actions} motion={motion} locked={false} controller={port} capabilities={capabilities} telemetry={telemetry()} isPhysicalDevice debugMode />);
    await user.click(screen.getAllByRole('button', { name: '预览' })[0]);
    expect(port.playPose).not.toHaveBeenCalled();
    expect(port.applyPose).not.toHaveBeenCalled();
    expect(screen.getAllByText(/真机优先/).length).toBeGreaterThan(0);
  });

  it('renders every joint slider and playback controls', async () => {
    const user = userEvent.setup();
    render(<ActionCenter actions={actions} motion={motion} locked={false} controller={controller()} capabilities={capabilities} telemetry={telemetry()} />);
    expect(document.querySelectorAll('.joint-slider-item').length).toBe(O6_JOINT_NAMES.length);
    await user.click(screen.getByRole('button', { name: /新建动作/ }));
    expect(screen.getByLabelText('播放模式')).toBeDefined();
    expect(screen.getByLabelText('方向')).toBeDefined();
  });
});
