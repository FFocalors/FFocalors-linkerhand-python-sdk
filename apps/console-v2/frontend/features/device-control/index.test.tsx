import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { DeviceControl } from './index';
import type { DevicePort, TelemetryPort } from '../../shared/contracts';

const device: DevicePort = { getConfig: async () => ({ id: 'x', name: 'x', model: 'O6', address: 'x' }), getCapabilities: async () => ({ model: 'O6', jointCount: 6, visionSync: true, tactile: true }), getConnection: async () => ({ state: 'connected', latencyMs: 1, lastSeen: 'now' }), setJointTarget: vi.fn(async () => undefined), stopAll: async () => undefined, unlock: async () => undefined };
const telemetry: TelemetryPort = { read: async () => ({ timestamp: 0, joints: { J1: 0 }, currentMa: 10, temperatureC: 20 }), subscribe: () => () => undefined };
describe('device slider', () => {
  it('commits the final pointer value', async () => {
    render(<DeviceControl device={device} telemetry={telemetry} config={{ id: 'x', name: 'x', model: 'O6', address: 'x' }} capabilities={{ model: 'O6', jointCount: 1, visionSync: true, tactile: true }} locked={false} />);
    const slider = await screen.findByRole('slider', { name: 'J1 目标' });
    fireEvent.pointerDown(slider); fireEvent.change(slider, { target: { value: '42' } }); fireEvent.pointerUp(slider);
    await waitFor(() => expect(device.setJointTarget).toHaveBeenCalled());
    expect((device.setJointTarget as ReturnType<typeof vi.fn>).mock.calls.at(-1)?.[0]).toMatchObject({ joint: 'J1', value: 42 });
  });
});
