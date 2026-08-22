import { readFile, readdir } from 'node:fs/promises';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('..', import.meta.url));
const viteConfig = await readFile(resolve(root, 'vite.config.ts'), 'utf8');
const runtime = await readFile(resolve(root, 'frontend/shared/vision-runtime/runtime.ts'), 'utf8');
const composition = await readFile(resolve(root, 'frontend/app/composition.ts'), 'utf8');
if (!viteConfig.includes("format: 'iife'")) throw new Error('Vision worker must use Vite classic IIFE output for MediaPipe Emscripten loaders.');
if (!composition.includes("from '../workers/vision-worker/index?worker&classic'")) throw new Error('App composition must import the Vite classic ?worker constructor.');
if (!composition.includes('new VisionWorker()')) throw new Error('App composition does not instantiate the Vite worker constructor.');
if (!composition.includes('workerFactory: () => new VisionWorker()')) throw new Error('App composition must inject the Vite worker constructor into VisionRuntime.');
if (runtime.includes('new Worker(new URL(') || runtime.includes("from '../../workers/vision-worker")) throw new Error('VisionRuntime shared code bypasses the app-injected Vite worker factory.');

const assetRoot = resolve(root, 'dist/assets');
const visionRoot = resolve(root, 'dist/vision');
const workerNames = (await readdir(assetRoot)).filter(name => /^vision-worker-.*\.js$/.test(name));
if (workerNames.length !== 1) throw new Error(`Expected exactly one vision worker chunk, found ${workerNames.length}.`);
const worker = await readFile(resolve(assetRoot, workerNames[0]), 'utf8');
const visionBundle = await readFile(resolve(visionRoot, 'vision_bundle.js'), 'utf8');
if (!worker.startsWith('(function')) throw new Error('Vision worker chunk is not a classic IIFE.');
if (!worker.includes('importScripts')) throw new Error('Vision worker does not include the MediaPipe classic loader path.');
if (!worker.includes('vision_bundle.js')) throw new Error('Vision worker must load the local classic MediaPipe bundle.');
if (!visionBundle.includes('var Vision=')) throw new Error('The bundled MediaPipe classic UMD asset must expose the Vision namespace.');
if (!visionBundle.includes('ModuleFactory')) throw new Error('The bundled MediaPipe asset must retain the ModuleFactory loader path.');
console.log(`Verified classic vision worker: ${workerNames[0]}`);
