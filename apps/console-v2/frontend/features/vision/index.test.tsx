import { render, screen } from '@testing-library/react';
import { VisionMimic } from './index';
import type { VisionPort } from '../../shared/contracts';
const vision: VisionPort = { propose: async () => [{ id: '1', label: '测试动作', confidence: .9, joints: {} }], sync: vi.fn(async () => undefined) };
describe('vision permissions', () => {
  it('allows preview but disables sync for non O6 models', async () => {
    render(<VisionMimic vision={vision} capabilities={{ model: 'L7', jointCount: 7, visionSync: false, tactile: true }} locked={false} />);
    const button = await screen.findByRole('button', { name: '同步动作' });
    expect(button).toBeDisabled(); expect(screen.getByText(/只有 O6/)).toBeInTheDocument();
  });
});
