import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SmartGrasp, type GraspController, type GraspControllerState } from './index';
import type { GraspPort } from '../../shared/contracts';

const grasp: GraspPort = { listPresets: vi.fn(async () => [{ id: 'soft', name: '柔软物体', description: '低力度' }]), runPreset: vi.fn(async () => undefined) };

function makeIdleState(): GraspControllerState {
  return {
    phase: 'idle', tactileAvailable: false, rawTouch: null, degraded: false, calibrated: false,
    joints: Array.from({ length: 6 }, (_, i) => ({
      index: i, name: `J${i + 1}`, state: 'idle' as const, contactScore: 0, load: 0, loadMax: 255,
    })),
    jointCount: 6,
  };
}

function controller(initial: GraspControllerState): GraspController {
  let state = initial; let listener: ((next: GraspControllerState) => void) | undefined;
  const next = (phase: GraspControllerState['phase']) => { state = { ...state, phase }; listener?.(state); };
  return {
    calibrate: vi.fn(async () => next('calibrating')),
    approach: vi.fn(async () => next('approaching')),
    startGrasp: vi.fn(async () => next('closingCoarse')),
    release: vi.fn(async () => next('releasing')),
    abort: vi.fn(async () => next('aborted')),
    getState: vi.fn(async () => state),
    subscribe: vi.fn(callback => { listener = callback; return () => { listener = undefined; }; }),
  };
}

describe('SmartGrasp controller boundary', () => {
  it.each(['G20', 'L21', 'L25'] as const)('disables %s adaptive profile', async model => {
    render(<SmartGrasp grasp={grasp} locked={false} tactileAvailable={true} model={model} jointCount={6} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('不支持智能自适应抓取');
    expect(screen.getByRole('button', { name: /空载标定/ })).toBeDisabled();
  });
  it('shows calibration as first step and flow visualization', async () => {
    const state = makeIdleState();
    render(<SmartGrasp grasp={grasp} locked={false} tactileAvailable={false} controller={controller(state)} jointCount={6} />);
    expect(await screen.findByText('空载标定')).toBeInTheDocument();
    expect(screen.getByText('快速逼近')).toBeInTheDocument();
    expect(screen.getByText('精细逼近')).toBeInTheDocument();
  });
  it('shows controller failure explanation', async () => {
    const failure = { code: 'no_calibration', message: '未完成空载标定，无法开始抓取。' };
    const state = { ...makeIdleState(), phase: 'failed' as const, failure };
    render(<SmartGrasp grasp={grasp} locked={false} tactileAvailable={false} controller={controller(state)} jointCount={6} />);
    expect(await screen.findByRole('alert')).toHaveTextContent(failure.message);
  });
  it('disables all actions when not connected and debug mode is off', async () => {
    render(<SmartGrasp grasp={grasp} locked={false} tactileAvailable={false} controller={controller(makeIdleState())} jointCount={6} debugMode={false} isPhysicalDevice={false} />);
    expect(await screen.findByText('未连接机械手，智能抓取不可用。')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /空载标定/ })).toBeDisabled();
    expect(screen.getByRole('button', { name: /预抓取定位/ })).toBeDisabled();
    expect(screen.getByRole('button', { name: /开始抓取/ })).toBeDisabled();
    expect(screen.getByRole('button', { name: /释放/ })).toBeDisabled();
  });
});