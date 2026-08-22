import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
export type ThemePreference = 'light' | 'dark' | 'system';
export type ThemePort = { getTheme(): ThemePreference | Promise<ThemePreference>; setTheme(theme: ThemePreference): void | Promise<void>; subscribe?(listener: (theme: ThemePreference) => void): () => void };
export type Theme = 'light' | 'dark';
const ThemeContext = createContext<{ theme: Theme; toggle: () => void }>({ theme: 'light', toggle: () => undefined });
export function ThemeProvider({ children, themePort }: { children: ReactNode; themePort?: ThemePort }) {
  const [preference, setPreference] = useState<ThemePreference>(() => themePort ? 'system' : ((localStorage.getItem('linkerhand-console-v2-theme') as ThemePreference) || 'light'));
  const [systemDark, setSystemDark] = useState(() => typeof matchMedia !== 'undefined' && matchMedia('(prefers-color-scheme: dark)').matches);
  useEffect(() => { if (!themePort) return undefined; let active = true; void Promise.resolve(themePort.getTheme()).then(value => { if (active) setPreference(value); }); const remove = themePort.subscribe?.(value => setPreference(value)); return () => { active = false; remove?.(); }; }, [themePort]);
  useEffect(() => { if (typeof matchMedia === 'undefined') return undefined; const query = matchMedia('(prefers-color-scheme: dark)'); const onChange = () => setSystemDark(query.matches); query.addEventListener?.('change', onChange); return () => query.removeEventListener?.('change', onChange); }, []);
  const theme: Theme = preference === 'system' ? (systemDark ? 'dark' : 'light') : preference;
  useEffect(() => { document.documentElement.dataset.theme = theme; if (!themePort) localStorage.setItem('linkerhand-console-v2-theme', preference); }, [preference, theme, themePort]);
  const value = useMemo(() => ({ theme, toggle: () => { const next = theme === 'light' ? 'dark' : 'light'; setPreference(next); void themePort?.setTheme(next); } }), [theme, themePort]);
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}
export const useTheme = () => useContext(ThemeContext);
