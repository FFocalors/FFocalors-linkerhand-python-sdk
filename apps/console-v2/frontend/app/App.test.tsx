import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { App } from './App';

describe('console shell', () => {
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
});
