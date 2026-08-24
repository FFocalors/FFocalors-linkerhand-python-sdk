import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { App, readActionCenterStorage, recordDebugModeChange, writeActionCenterStorage } from './App';

describe('console shell', () => {
  it('records debug mode transitions as structured runtime events', async () => {
    const record = vi.fn(async () => undefined);
    await recordDebugModeChange({ list: vi.fn(async () => []), record }, true);
    expect(record).toHaveBeenCalledWith(expect.objectContaining({ event: 'debug_mode.enabled', fields: { enabled: true, source: 'settings' } }));
    await recordDebugModeChange({ list: vi.fn(async () => []), record }, false);
    expect(record).toHaveBeenLastCalledWith(expect.objectContaining({ event: 'debug_mode.disabled', fields: { enabled: false, source: 'settings' } }));
  });
  it('persists action-center poses and programmed actions in their own storage record', () => {
    localStorage.clear();
    const value = { localPresets: [{ id: 'local-pose', label: '本地姿态', category: 'custom' as const, positions: [0, .1, .2, .3, .4, .5] }], programmedActions: [] };
    writeActionCenterStorage(value);
    expect(readActionCenterStorage()).toEqual(value);
    expect(localStorage.getItem('linkerhand-console-v2-custom-presets')).toBeNull();
    localStorage.clear();
  });
  it('stops all actions and exposes recovery', async () => {
    const user = userEvent.setup(); render(<App />);
    await screen.findByRole('heading', { name: '设备控制' });
    await user.click(screen.getByRole('button', { name: /停止全部动作/ }));
    expect(screen.getAllByText('控制已锁定').length).toBeGreaterThan(0);
    expect(screen.getAllByRole('button', { name: /恢复控制/ }).length).toBeGreaterThan(0);
  });
  it('switches theme from the header', async () => {
    const user = userEvent.setup(); render(<App />);
    await screen.findByRole('heading', { name: '设备控制' });
    await user.click(screen.getByRole('button', { name: '切换主题' }));
    await waitFor(() => expect(document.documentElement.dataset.theme).toBe('dark'));
  });
  it('switches the shell and feature copy, then restores the persisted locale', async () => {
    localStorage.clear();
    const user = userEvent.setup();
    const { unmount } = render(<App />);
    await screen.findByRole('heading', { name: '设备控制' });
    await user.click(screen.getByRole('button', { name: '设置' }));
    await screen.findByRole('heading', { name: '设置' });
    await user.click(screen.getByRole('button', { name: 'English' }));
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Settings' })).toBeInTheDocument());
    expect(screen.getByRole('button', { name: 'Device control' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Action center' }));
    await screen.findByRole('heading', { name: 'Action center' });
    await user.click(screen.getByRole('button', { name: 'Diagnostics' }));
    await screen.findByRole('heading', { name: 'Diagnostics' });
    expect(localStorage.getItem('linkerhand-console-v2-locale')).toBe('en');
    unmount();
    render(<App />);
    await screen.findByRole('heading', { name: 'Device control' });
    await user.click(screen.getByRole('button', { name: 'Settings' }));
    await screen.findByRole('heading', { name: 'Settings' });
    await user.click(screen.getByRole('button', { name: '中文' }));
    await waitFor(() => expect(screen.getByRole('heading', { name: '设置' })).toBeInTheDocument());
    expect(localStorage.getItem('linkerhand-console-v2-locale')).toBe('zh');
  });

  it('shares the debug virtual telemetry source with the action-center draft', async () => {
    localStorage.clear();
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole('heading', { name: '设备控制' });
    await user.click(screen.getByRole('button', { name: '设置' }));
    await screen.findByRole('heading', { name: '设置' });
    await user.click(screen.getByRole('button', { name: /高级设置/ }));
    const debugToggle = screen.getByLabelText(/调试模式/);
    await user.click(debugToggle);
    await user.click(screen.getByRole('button', { name: '动作中心' }));
    await screen.findByRole('heading', { name: '姿态编辑器' });
    const actionSlider = screen.getByRole('slider', { name: '大拇指弯曲 目标' });
    fireEvent.change(actionSlider, { target: { value: '0.42' } });
    await user.click(screen.getByRole('button', { name: '设备控制' }));
    const deviceSlider = await screen.findByRole('slider', { name: '大拇指弯曲 目标' });
    await waitFor(() => expect(deviceSlider).toHaveValue('0.42'));
  });

  it('keeps action playback disabled until a real device is connected or debug mode is enabled', async () => {
    localStorage.clear();
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole('heading', { name: '设备控制' });
    await user.click(screen.getByRole('button', { name: '动作中心' }));
    await screen.findByRole('heading', { name: '姿态编辑器' });
    expect(screen.getByText(/未连接真实机械手/)).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: '播放' })[0]).toBeDisabled();
  });
});
