import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { StrictMode } from 'react';
import { ThemeProvider } from '../shared/theme';
import type { ConsolePorts } from '../shared/contracts';
import { Settings } from '../features/settings';
import { createSettingsController } from './settings';

const config = { schemaVersion: 1 as const, deviceId: 'test', name: '测试手', model: 'O6' as const, hand: 'left' as const, transport: { type: 'can' as const, channel: 'can0' }, autoReconnect: true };

describe('settings and real camera controller integration', () => {
  it('keeps left hand when camera enrichment publishes a camera-only snapshot', async () => {
    const enumerateDevices = vi.fn()
      .mockResolvedValueOnce([{ kind: 'videoinput', deviceId: 'default', label: '', groupId: 'local' }])
      .mockResolvedValue([
        { kind: 'videoinput', deviceId: 'laptop', label: 'Integrated Camera', groupId: 'local' },
        { kind: 'videoinput', deviceId: 'phone', label: 'Phone Camera', groupId: 'remote' },
      ]);
    const stream = { getTracks: () => [{ stop: vi.fn() }] } as unknown as MediaStream;
    Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: { enumerateDevices, getUserMedia: vi.fn(async () => stream) } });
    const runtime = { device: { getConfig: vi.fn(async () => config) } } as unknown as ConsolePorts;
    const controller = createSettingsController(runtime, true);
    render(<StrictMode><ThemeProvider><Settings model="O6" transport={{ type: 'can', channel: 'can0' }} controller={controller} /></ThemeProvider></StrictMode>);
    await screen.findByText(/版本 2\.0\.0/);
    await userEvent.setup().click(screen.getByRole('radio', { name: '左手' }));
    await userEvent.setup().click(screen.getByRole('button', { name: '刷新摄像头' }));
    expect(screen.getByRole('radio', { name: '左手' })).toBeChecked();
    await screen.findByRole('option', { name: 'Integrated Camera' });
    expect(screen.getByRole('radio', { name: '左手' })).toBeChecked();
  });
});
