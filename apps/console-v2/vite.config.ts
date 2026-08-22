import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import { readFileSync } from 'node:fs';

const packageMetadata = JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf8')) as { version: string };
const visionBundle = readFileSync(new URL('./node_modules/@mediapipe/tasks-vision/vision_bundle.js', import.meta.url));

const classicVisionWorkerPlugin = {
  name: 'console-v2-classic-vision-worker',
  // Vite serves workers as module workers during dev even when the build
  // format is IIFE. Rewrite only this explicitly-marked worker constructor;
  // the worker source is classic-safe and imports the official UMD bundle.
  enforce: 'post' as const,
  transform(code: string, id: string) {
    if (id.includes('/workers/vision-worker/index.ts?worker_file&type=classic')) {
      // Type-only imports make esbuild preserve an empty module marker. A
      // classic worker cannot parse it, so remove only this exact trailing
      // marker from this one worker_file response.
      const transformed = code.replace(/\n?export\s*\{\s*\};\s*$/, '\n');
      return transformed === code ? undefined : { code: transformed, map: null };
    }
    if (!id.includes('/workers/vision-worker/index.ts?worker&classic')) return;
    const transformed = code
      .replace('?worker_file&type=module', '?worker_file&type=classic')
      .replace('type: "module",', '');
    return transformed === code ? undefined : { code: transformed, map: null };
  },
  configureServer(server: { middlewares: { use: (handler: (request: { url?: string }, response: { statusCode: number; setHeader: (name: string, value: string) => void; end: (body: Buffer) => void }, next: () => void) => void) => void } }) {
    server.middlewares.use((request, response, next) => {
      if (request.url?.split('?')[0].endsWith('/vision/vision_bundle.js') !== true) { next(); return; }
      response.statusCode = 200;
      response.setHeader('Content-Type', 'text/javascript; charset=utf-8');
      response.end(visionBundle);
    });
  },
  generateBundle(this: { emitFile: (asset: { type: 'asset'; fileName: string; source: Buffer }) => void }) {
    this.emitFile({ type: 'asset', fileName: 'vision/vision_bundle.js', source: visionBundle });
  },
};

export default defineConfig({
  plugins: [react(), classicVisionWorkerPlugin],
  define: { 'import.meta.env.VITE_APP_VERSION': JSON.stringify(packageMetadata.version) },
  // MediaPipe Tasks' official Emscripten loader is a classic script. A
  // module worker's dynamic-import fallback cannot expose its script-level
  // `ModuleFactory` on self, so the vision worker must be emitted as a classic
  // IIFE and loaded without `{ type: 'module' }`.
  worker: { format: 'iife', rollupOptions: { output: { entryFileNames: 'assets/vision-worker-[hash].js' } } },
  test: { environment: 'jsdom', setupFiles: './frontend/test-setup.ts', globals: true },
});
