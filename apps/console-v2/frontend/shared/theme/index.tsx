import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
export type Theme = 'light' | 'dark';
const ThemeContext = createContext<{ theme: Theme; toggle: () => void }>({ theme: 'light', toggle: () => undefined });
export function ThemeProvider({ children }: { children: ReactNode }) { const [theme, setTheme] = useState<Theme>(() => (localStorage.getItem('lh-theme') as Theme) || 'light'); useEffect(() => { document.documentElement.dataset.theme = theme; localStorage.setItem('lh-theme', theme); }, [theme]); return <ThemeContext.Provider value={{ theme, toggle: () => setTheme(value => value === 'light' ? 'dark' : 'light') }}>{children}</ThemeContext.Provider>; }
export const useTheme = () => useContext(ThemeContext);
