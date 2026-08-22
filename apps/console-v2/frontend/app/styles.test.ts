import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';

function cssSources(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap(entry => {
    const path = join(directory, entry.name);
    return entry.isDirectory() ? cssSources(path) : entry.name.endsWith('.css') ? [path] : [];
  });
}

const frontendRoot = join(process.cwd(), 'frontend');

describe('console UX CSS contract', () => {
  const appCss = readFileSync(join(frontendRoot, 'app', 'styles.css'), 'utf8');

  it('is offline-safe and does not request remote fonts or assets', () => {
    for (const file of cssSources(frontendRoot)) {
      const css = readFileSync(file, 'utf8');
      expect(css).not.toMatch(/@import/i);
      expect(css).not.toMatch(/url\(\s*['"]?https?:/i);
    }
  });

  it('defines light/dark semantic tokens and a single restrained page transition', () => {
    expect(appCss).toContain(':root[data-theme="dark"]');
    expect(appCss).toContain('--theme-duration: 180ms');
    expect(appCss).toMatch(/\.page-transition\s*\{[^}]*animation:/s);
    expect(appCss).toMatch(/@keyframes page-enter/);
    expect(appCss).not.toMatch(/\.card\s*\{[^}]*animation:/s);
    expect(appCss).not.toContain('will-change');
  });

  it('protects keyboard and reduced-motion behavior', () => {
    expect(appCss).toMatch(/button:focus-visible[^}]*outline/s);
    expect(appCss).toMatch(/@media \(prefers-reduced-motion: reduce\)/);
    expect(appCss).toMatch(/\.nav-item\s*\{[^}]*min-height: 44px/s);
    expect(appCss).toMatch(/\.button\s*\{[^}]*min-height: 44px/s);
  });

  it('keeps high-frequency slider input free of CSS transitions', () => {
    expect(appCss).toMatch(/input\[type="range"\]\s*\{\s*transition: none;/s);
    expect(appCss).not.toMatch(/\.joint-row input\s*\{[^}]*animation:/s);
  });
});
