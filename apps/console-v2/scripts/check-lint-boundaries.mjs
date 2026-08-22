import { ESLint } from 'eslint';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(fileURLToPath(new URL('..', import.meta.url)));
const eslint = new ESLint({ cwd: root, errorOnUnmatchedPattern: false });
const generatedRoots = [
  'target/**/tauri-codegen-assets/**/*.js',
  'dist/**',
  'artifacts/**',
  'sidecar/linkerhand-bridge/build/**',
  'sidecar/linkerhand-bridge/dist/**',
  'src-tauri/binaries/**',
  'src-tauri/target/**',
];

const results = await eslint.lintFiles(generatedRoots);
if (results.length !== 0) {
  throw new Error(`Generated paths were linted: ${results.map((result) => result.filePath).join(', ')}`);
}
console.log(`ESLint generated-directory boundary passed (${generatedRoots.length} ignored roots).`);
