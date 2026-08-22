import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { DeviceControl } from './index';
import type { DevicePort, TelemetryPort } from '../../shared/contracts';

const device: DevicePort = { getConfig: async () => ({ schemaVersion: 1, deviceId: 'x', name: 'x', model: 'O6', hand: 'left', transport: { type: 'can', channel: 'fake' }, autoReconnect: true }), getCapabilities: async () => ({ schemaVersion: 1, deviceId: 'x', model: 'O6', hand: 'left', transport: { type: 'can', channel: 'fake' }, jointCount: 1, position: { length: 1, available: true, range: { min: 0, max: 255 } }, speed: { length: 1, available: true, range: { min: 0, max: 255 } }, current: { length: 1, available: true, range: { min: 0, max: 255 } }, torque: { length: 1, available: true, range: { min: 0, max: 255 } }, touch: { length: 1, available: true, range: { min: 0, max: 255 } }, speedCommandLength: 1, currentCommandLength: null, torqueCommandLength: 1, supportedOperations: [] }), getConnection: async () => ({ schemaVersion: 1, deviceId: 'x', state: 'connected', attempt: 1, lastError: null }), setJointTarget: vi.fn(async () => undefined), stopAll: async () => undefined, unlock: async () => undefined };
const telemetry: TelemetryPort = { read: async () => ({ schemaVersion: 1, deviceId: 'x', sequence: 0, monotonicTimeMs: 0, positions: [0], rawPosition: [0], rawCurrent: [0], rawSpeed: [0], rawTouch: [0], connected: true }), subscribe: () => () => undefined };
describe('device slider', () => {
  it('commits the final pointer value', async () => {
    render(<DeviceControl device={device} telemetry={telemetry} config={{ schemaVersion: 1, deviceId: 'x', name: 'x', model: 'O6', hand: 'left', transport: { type: 'can', channel: 'fake' }, autoReconnect: true }} capabilities={await device.getCapabilities()} locked={false} />);
    const slider = await screen.findByRole('slider', { name: 'J1 目标' });
    fireEvent.pointerDown(slider); fireEvent.change(slider, { target: { value: '0.42' } }); fireEvent.pointerUp(slider);
    await waitFor(() => expect(device.setJointTarget).toHaveBeenCalled());
    expect((device.setJointTarget as ReturnType<typeof vi.fn>).mock.calls.at(-1)?.[0]).toMatchObject({ source: 'manual', positions: [0.42] });
  });
});
