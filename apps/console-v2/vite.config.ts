import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  worker: { rollupOptions: { output: { entryFileNames: 'assets/vision-worker-[hash].js' } } },
  test: { environment: 'jsdom', setupFiles: './frontend/test-setup.ts', globals: true },
});
