import { createHash } from 'node:crypto';
import { mkdir, readFile, writeFile, cp } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
const root = fileURLToPath(new URL('..', import.meta.url));
const assetRoot = resolve(root, 'public/vision');
const manifest = JSON.parse(await readFile(resolve(assetRoot, 'assets-manifest.json'), 'utf8'));
const model = resolve(assetRoot, 'hand_landmarker.task');
const response = await fetch(manifest.modelSource);
if (!response.ok) throw new Error(`Unable to download model: ${response.status}`);
await mkdir(dirname(model), { recursive: true });
await writeFile(model, Buffer.from(await response.arrayBuffer()));
const packageWasm = resolve(root, 'node_modules/@mediapipe/tasks-vision/wasm');
for (const relative of Object.keys(manifest.files).filter(file => file.startsWith('wasm/'))) {
  await mkdir(dirname(resolve(assetRoot, relative)), { recursive: true });
  await cp(resolve(packageWasm, relative.slice('wasm/'.length)), resolve(assetRoot, relative));
}
const hash = createHash('sha256').update(await readFile(model)).digest('hex').toUpperCase();
if (hash !== manifest.files['hand_landmarker.task']) throw new Error(`Downloaded model hash mismatch: ${hash}`);
console.log('Downloaded and verified offline vision assets. Run pnpm check:vision-assets.');
