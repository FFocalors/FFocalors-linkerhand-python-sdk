import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { StrictMode } from 'react';
import { VisionMimic } from './index';
import type { VisionPort } from '../../shared/contracts';
import type { VisionRuntimeLike } from './controller';
import type { VisionRuntimeSnapshot } from '../../shared/vision-runtime';
const vision: VisionPort = { propose: async () => [{ schemaVersion: 1, id: '1', label: '测试动作', confidence: .9, positions: [0] }], sync: vi.fn(async () => undefined) };
const capabilities = { schemaVersion: 1, deviceId: 'x', model: 'O6' as const, hand: 'left' as const, transport: { type: 'can' as const, channel: 'test' }, jointCount: 6, position: { length: 6, available: true, range: { min: 0, max: 255 } }, speed: { length: 6, available: true, range: { min: 0, max: 255 } }, current: { length: 6, available: true, range: { min: 0, max: 255 } }, torque: { length: 6, available: true, range: { min: 0, max: 255 } }, touch: { length: 6, available: true, range: { min: 0, max: 255 } }, speedCommandLength: 6, currentCommandLength: null, torqueCommandLength: 6, supportedOperations: ['setPosition' as const] };
const runtimeSnapshot = (overrides: Partial<VisionRuntimeSnapshot> = {}): VisionRuntimeSnapshot => ({ state: 'idle', owner: null, cameraDeviceId: null, model: 'unloaded', frameSequence: 0, fps: null, droppedFrames: 0, inflight: 0, lastError: null, ...overrides });
function runtimeWithStart(start: VisionRuntimeLike['start']): VisionRuntimeLike {
  let snapshot = runtimeSnapshot();
  const wrappedStart: VisionRuntimeLike['start'] = async (video, source, deviceId) => { await start(video, source, deviceId); snapshot = runtimeSnapshot({ state: 'running', owner: 'vision', model: 'ready' }); };
  return { start: vi.fn(wrappedStart), stop: vi.fn(async () => { snapshot = runtimeSnapshot(); }), snapshot: () => snapshot, subscribe: listener => { listener(snapshot); return () => undefined; }, onResult: () => () => undefined };
}
describe('vision permissions', () => {
  it('allows preview but disables sync for non O6 models', async () => {
    render(<VisionMimic vision={vision} capabilities={{ schemaVersion: 1, deviceId: 'x', model: 'L7', hand: 'left', transport: { type: 'can', channel: 'fake' }, jointCount: 7, position: { length: 7, available: true, range: { min: 0, max: 255 } }, speed: { length: 7, available: true, range: { min: 0, max: 255 } }, current: { length: 7, available: true, range: { min: 0, max: 255 } }, torque: { length: 7, available: true, range: { min: 0, max: 255 } }, touch: { length: 7, available: true, range: { min: 0, max: 255 } }, speedCommandLength: 7, currentCommandLength: null, torqueCommandLength: 7, supportedOperations: [] }} locked={false} />);
    const button = await screen.findByRole('button', { name: '同步动作' });
    expect(button).toBeDisabled(); expect(screen.getByText(/当前型号支持预览/)).toBeInTheDocument();
  });

  it('survives StrictMode effect replay and can start the shared runtime', async () => {
    const start = vi.fn(async () => undefined);
    const runtime = runtimeWithStart(start);
    render(<StrictMode><VisionMimic runtime={runtime} capabilities={capabilities} locked={false} /></StrictMode>);
    await screen.findByRole('button', { name: '开始预览' });
    await userEvent.setup().click(screen.getByRole('button', { name: '开始预览' }));
    await waitFor(() => expect(start).toHaveBeenCalledTimes(1));
  });

  it('shows startup failure in an alert without an unhandled rejection', async () => {
    const unhandled: unknown[] = [];
    const onUnhandled = (reason: unknown) => unhandled.push(reason);
    process.on('unhandledRejection', onUnhandled);
    try {
      const runtime = runtimeWithStart(async () => { throw new Error('摄像头权限被拒绝'); });
      render(<StrictMode><VisionMimic runtime={runtime} capabilities={capabilities} locked={false} /></StrictMode>);
      const user = userEvent.setup();
      await user.click(await screen.findByRole('button', { name: '开始预览' }));
      await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('摄像头权限被拒绝'));
      expect(unhandled).toHaveLength(0);
    } finally {
      process.off('unhandledRejection', onUnhandled);
    }
  });
});
