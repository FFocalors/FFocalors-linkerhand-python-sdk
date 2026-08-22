import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SmartGrasp, type GraspController, type GraspControllerState } from './index';
import type { GraspPort } from '../../shared/contracts';

const grasp: GraspPort = { listPresets: vi.fn(async () => [{ id: 'soft', name: '柔软物体', description: '低力度' }]), runPreset: vi.fn(async () => undefined) };
function controller(initial: GraspControllerState): GraspController {
  let state = initial; let listener: ((next: GraspControllerState) => void) | undefined;
  const next = (phase: GraspControllerState['phase']) => { state = { ...state, phase }; listener?.(state); };
  return { calibrate: vi.fn(async () => next('calibrating')), completeCalibration: vi.fn(async () => next('ready')), approach: vi.fn(async () => next('approach')), startGrasp: vi.fn(async () => next('grasping')), release: vi.fn(async () => next('releasing')), abort: vi.fn(async () => next('aborted')), getState: vi.fn(async () => state), subscribe: vi.fn(callback => { listener = callback; return () => { listener = undefined; }; }) };
}

describe('SmartGrasp controller boundary', () => {
  it.each(['G20', 'L21', 'L25'] as const)('disables %s adaptive profile', async model => {
    render(<SmartGrasp grasp={grasp} locked={false} tactileAvailable={true} model={model} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('不支持智能自适应抓取');
    expect(screen.getByRole('button', { name: /开始标定/ })).toBeDisabled();
  });
  it('requires explicit degraded mode, does not fake touch, and aborts through controller', async () => {
    const user = userEvent.setup(); const port = controller({ phase: 'calibrating', tactileAvailable: false, rawTouch: null, degraded: false });
    render(<SmartGrasp grasp={grasp} locked={false} tactileAvailable={false} controller={port} />);
    expect(screen.getAllByText('暂无触觉数据').length).toBeGreaterThan(0);
    expect(screen.getByText(/不会使用伪造强度/)).toBeInTheDocument();
    await user.click(screen.getByLabelText(/我确认以无触觉降级模式执行/));
    await user.click(screen.getByRole('button', { name: '中止' }));
    expect(port.abort).toHaveBeenCalled();
  });
  it('shows controller failure explanation', async () => {
    const failure = { code: 'tactile_missing', message: '未检测到触觉反馈；请启用显式降级模式。' };
    render(<SmartGrasp grasp={grasp} locked={false} tactileAvailable={false} controller={controller({ phase: 'failed', tactileAvailable: false, rawTouch: null, degraded: false, failure })} />);
    expect(await screen.findByRole('alert')).toHaveTextContent(failure.message);
  });
});
