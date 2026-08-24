import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

const classicVisionWorkerPlugin = {
  name: 'console-v2-classic-vision-worker',
  enforce: 'post' as const,
  transform(code: string, id: string) {
    if (id.includes('/workers/vision-worker/index.ts?worker_file&type=classic')) {
      const transformed = code.replace(/\n?export\s*\{\s*\};\s*$/, '\n');
      return transformed === code ? undefined : { code: transformed, map: null };
    }
    if (!id.includes('/workers/vision-worker/index.ts?worker&classic')) return;
    const transformed = code
      .replace('?worker_file&type=module', '?worker_file&type=classic')
      .replace('type: "module",', '');
    return transformed === code ? undefined : { code: transformed, map: null };
  },
};

export default defineConfig({
  plugins: [react(), classicVisionWorkerPlugin],
  resolve: { preserveSymlinks: true },
  optimizeDeps: { noDiscovery: true, include: ['react', 'react-dom', 'react-dom/client', 'scheduler'] },
  server: { host: '127.0.0.1', port: 5173, strictPort: true },
  test: { environment: 'jsdom', setupFiles: './frontend/test-setup.ts', globals: true },
});
