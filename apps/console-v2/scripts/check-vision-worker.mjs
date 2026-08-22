import { readFile, readdir } from 'node:fs/promises';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('..', import.meta.url));
const viteConfig = await readFile(resolve(root, 'vite.config.ts'), 'utf8');
const runtime = await readFile(resolve(root, 'frontend/shared/vision-runtime/runtime.ts'), 'utf8');
if (!viteConfig.includes("format: 'iife'")) throw new Error('Vision worker must use Vite classic IIFE output for MediaPipe Emscripten loaders.');
if (runtime.includes("type: 'module'")) throw new Error('Vision runtime must not create a module worker; ModuleFactory requires a classic worker.');

const assetRoot = resolve(root, 'dist/assets');
const workerNames = (await readdir(assetRoot)).filter(name => /^vision-worker-.*\.js$/.test(name));
if (workerNames.length !== 1) throw new Error(`Expected exactly one vision worker chunk, found ${workerNames.length}.`);
const worker = await readFile(resolve(assetRoot, workerNames[0]), 'utf8');
if (!worker.startsWith('(function')) throw new Error('Vision worker chunk is not a classic IIFE.');
if (!worker.includes('importScripts')) throw new Error('Vision worker does not include the MediaPipe classic loader path.');
if (!worker.includes('ModuleFactory not set.')) throw new Error('Vision worker bundle does not include the MediaPipe ModuleFactory guard.');
console.log(`Verified classic vision worker: ${workerNames[0]}`);
