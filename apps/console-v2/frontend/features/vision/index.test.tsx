import { render, screen } from '@testing-library/react';
import { VisionMimic } from './index';
import type { VisionPort } from '../../shared/contracts';
const vision: VisionPort = { propose: async () => [{ schemaVersion: 1, id: '1', label: '测试动作', confidence: .9, positions: [0] }], sync: vi.fn(async () => undefined) };
describe('vision permissions', () => {
  it('allows preview but disables sync for non O6 models', async () => {
    render(<VisionMimic vision={vision} capabilities={{ schemaVersion: 1, deviceId: 'x', model: 'L7', hand: 'left', transport: { type: 'can', channel: 'fake' }, jointCount: 7, position: { length: 7, available: true, range: { min: 0, max: 255 } }, speed: { length: 7, available: true, range: { min: 0, max: 255 } }, current: { length: 7, available: true, range: { min: 0, max: 255 } }, torque: { length: 7, available: true, range: { min: 0, max: 255 } }, touch: { length: 7, available: true, range: { min: 0, max: 255 } }, speedCommandLength: 7, currentCommandLength: null, torqueCommandLength: 7, supportedOperations: [] }} locked={false} />);
    const button = await screen.findByRole('button', { name: '同步动作' });
    expect(button).toBeDisabled(); expect(screen.getByText(/当前型号支持预览/)).toBeInTheDocument();
  });
});
