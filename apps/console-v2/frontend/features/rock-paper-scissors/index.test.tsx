import { render, screen } from '@testing-library/react';
import { RockPaperScissors } from './index';
import type { DeviceCapabilities } from '../../shared/contracts';

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
});
