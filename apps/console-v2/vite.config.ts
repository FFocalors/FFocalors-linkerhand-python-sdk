import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import { readFileSync } from 'node:fs';

const packageMetadata = JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf8')) as { version: string };

export default defineConfig({
  plugins: [react()],
  define: { 'import.meta.env.VITE_APP_VERSION': JSON.stringify(packageMetadata.version) },
  worker: { rollupOptions: { output: { entryFileNames: 'assets/vision-worker-[hash].js' } } },
  test: { environment: 'jsdom', setupFiles: './frontend/test-setup.ts', globals: true },
});
