import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ActionCenter, type ActionController, type ActionControllerState } from './index';
import type { ActionPort, ActionRecording, MotionPort } from '../../shared/contracts';

const recording: ActionRecording = { schemaVersion: 1, id: 'custom-1', name: '测试动作', frames: [], durationMs: 1000, steps: 2, updatedAt: 'now' };
const actions: ActionPort = { list: vi.fn(async () => [recording]), delete: vi.fn(async () => undefined) };
const motion: MotionPort = { getOperation: vi.fn(async () => ({ schemaVersion: 1, operationId: 'motion', kind: 'motion', state: 'idle' as const, progress: 0, detail: null })), runAction: vi.fn(async () => undefined), pause: vi.fn(async () => undefined) };
function controller(): ActionController & { state: ActionControllerState } {
  let listener: ((state: ActionControllerState) => void) | undefined;
  const value = { state: { state: 'idle', progress: 0 } as ActionControllerState } as ActionController & { state: ActionControllerState };
  value.startRecording = vi.fn(async () => { value.state = { state: 'recording', progress: 0 }; listener?.(value.state); });
  value.pauseRecording = vi.fn(async () => undefined); value.resumeRecording = vi.fn(async () => undefined);
  value.finishRecording = vi.fn(async () => { value.state = { state: 'idle', progress: 0 }; listener?.(value.state); });
  value.cancelRecording = vi.fn(async () => undefined);
  value.play = vi.fn(async (actionId: string) => { value.state = { state: 'playing', actionId, progress: 12 }; listener?.(value.state); });
  value.pausePlayback = vi.fn(async () => undefined); value.resumePlayback = vi.fn(async () => undefined); value.stop = vi.fn(async () => undefined);
  value.getState = vi.fn(async () => value.state); value.subscribe = vi.fn(next => { listener = next; return () => { listener = undefined; }; });
  return value;
}

describe('ActionCenter controller boundary', () => {
  it('disables execution when controller is not wired', async () => {
    render(<ActionCenter actions={actions} motion={motion} locked={false} />);
    expect(await screen.findByRole('status')).toHaveTextContent('尚未接线');
    expect(screen.getByRole('button', { name: /新建动作/ })).toBeDisabled();
    expect(screen.getByRole('button', { name: /运行/ })).toBeDisabled();
  });
  it('calls recording start and finish through the controller', async () => {
    const user = userEvent.setup(); const port = controller();
    render(<ActionCenter actions={actions} motion={motion} locked={false} controller={port} />);
    await user.click(screen.getByRole('button', { name: /新建动作/ }));
    await user.type(screen.getByLabelText('动作名称'), '新的动作');
    await user.click(screen.getByRole('button', { name: '开始录制' }));
    expect(port.startRecording).toHaveBeenCalledWith('新的动作');
    await user.click(screen.getByRole('button', { name: '完成录制' }));
    expect(port.finishRecording).toHaveBeenCalled();
  });
  it('passes speed and finite loop and stops through the controller', async () => {
    const user = userEvent.setup(); const port = controller();
    render(<ActionCenter actions={actions} motion={motion} locked={false} controller={port} />);
    await user.selectOptions(screen.getByLabelText('倍速'), '2'); await user.selectOptions(screen.getByLabelText('循环'), '3');
    await user.click(await screen.findByRole('button', { name: /运行/ }));
    expect(port.play).toHaveBeenCalledWith('custom-1', { speed: 2, loopCount: 3 });
    await user.click(screen.getByRole('button', { name: '停止' }));
    expect(port.stop).toHaveBeenCalled();
  });
});
