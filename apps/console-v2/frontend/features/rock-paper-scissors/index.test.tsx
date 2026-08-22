import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { StrictMode } from 'react';
import { RockPaperScissors } from './index';
import type { DeviceCapabilities } from '../../shared/contracts';
import type { RpsVisionRuntime } from './types';
import type { VisionRuntimeSnapshot } from '../../shared/vision-runtime';

const capabilities = (model: DeviceCapabilities['model']): DeviceCapabilities => ({ schemaVersion: 1, deviceId: 'test', model, hand: 'left', transport: { type: 'can', channel: 'test' }, jointCount: 6, position: { length: 6, available: true, range: { min: 0, max: 255 } }, speed: { length: 6, available: true, range: { min: 0, max: 255 } }, current: { length: 6, available: true, range: { min: 0, max: 255 } }, torque: { length: 6, available: true, range: { min: 0, max: 255 } }, touch: { length: 6, available: true, range: { min: 0, max: 255 } }, speedCommandLength: 6, currentCommandLength: null, torqueCommandLength: 6, supportedOperations: ['setPosition'] });

describe('RPS action gates', () => {
  it('explains an O6 action controller that is not wired and disables authorization', () => {
    render(<RockPaperScissors capabilities={capabilities('O6')} locked={false} />);
    expect(screen.getByText(/动作控制器未接线/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '授权本局机械手' })).toBeDisabled();
  });

  it('does not expose mechanical action tests for non-O6 preview mode', () => {
    render(<RockPaperScissors capabilities={capabilities('L7')} locked={false} />);
    expect(screen.queryByRole('button', { name: /测试/ })).not.toBeInTheDocument();
    expect(screen.getByText(/仅进行摄像头识别与比分展示/)).toBeInTheDocument();
  });

  it('does not render a running camera control when the shared runtime belongs to vision', async () => {
    const snapshot: VisionRuntimeSnapshot = { state: 'running', owner: 'vision', cameraDeviceId: null, model: 'ready', frameSequence: 1, fps: 30, droppedFrames: 0, inflight: 0, lastError: null };
    const runtime: RpsVisionRuntime = { start: vi.fn(async () => undefined), stop: vi.fn(async () => undefined), subscribe: listener => { listener(snapshot); return () => undefined; }, onResult: () => () => undefined, snapshot: () => snapshot };
    render(<RockPaperScissors capabilities={capabilities('L7')} locked={false} runtime={runtime} />);
    await waitFor(() => expect(screen.getByRole('button', { name: '开启摄像头' })).toBeInTheDocument());
    expect(screen.queryByRole('button', { name: '停止摄像头' })).not.toBeInTheDocument();
    expect(screen.getAllByText(/视觉输入当前由 vision 占用/).length).toBeGreaterThan(0);
  });

  it('shows camera startup failures under StrictMode without an unhandled rejection', async () => {
    const unhandled: unknown[] = [];
    const onUnhandled = (reason: unknown) => unhandled.push(reason);
    process.on('unhandledRejection', onUnhandled);
    try {
      const snapshot: VisionRuntimeSnapshot = { state: 'idle', owner: null, cameraDeviceId: null, model: 'unloaded', frameSequence: 0, fps: null, droppedFrames: 0, inflight: 0, lastError: null };
      const runtime: RpsVisionRuntime = { start: vi.fn(async () => { throw new Error('摄像头权限被拒绝'); }), stop: vi.fn(async () => undefined), subscribe: listener => { listener(snapshot); return () => undefined; }, onResult: () => () => undefined, snapshot: () => snapshot };
      render(<StrictMode><RockPaperScissors capabilities={capabilities('O6')} locked={false} runtime={runtime} /></StrictMode>);
      await userEvent.setup().click(await screen.findByRole('button', { name: '开启摄像头' }));
      await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('摄像头权限被拒绝'));
      expect(unhandled).toHaveLength(0);
    } finally {
      process.off('unhandledRejection', onUnhandled);
    }
  });
});
