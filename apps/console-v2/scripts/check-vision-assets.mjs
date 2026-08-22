import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
const root = fileURLToPath(new URL('..', import.meta.url));
const manifest = JSON.parse(await readFile(resolve(root, 'public/vision/assets-manifest.json'), 'utf8'));
for (const [relative, expected] of Object.entries(manifest.files)) {
  const file = resolve(root, 'public/vision', relative);
  let actual;
  try { actual = createHash('sha256').update(await readFile(file)).digest('hex').toUpperCase(); }
  catch { throw new Error(`Missing offline vision asset: ${file}. Run pnpm vision:download.`); }
  if (actual !== expected) throw new Error(`Offline vision asset hash mismatch: ${relative} (expected ${expected}, got ${actual})`);
}
console.log(`Verified ${Object.keys(manifest.files).length} offline vision assets (${manifest.mediapipeTasksVision}).`);
