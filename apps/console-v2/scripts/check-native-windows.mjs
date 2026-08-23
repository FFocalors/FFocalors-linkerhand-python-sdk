import { access, readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const scripts = fileURLToPath(new URL('.', import.meta.url));
const root = resolve(scripts, '..');
const configPath = resolve(root, 'src-tauri/tauri.conf.json');
const cargoPath = resolve(root, 'src-tauri/Cargo.toml');
const buildPath = resolve(root, 'src-tauri/build.rs');

const config = JSON.parse(await readFile(configPath, 'utf8'));
const cargo = await readFile(cargoPath, 'utf8');
const build = await readFile(buildPath, 'utf8');
const devUrl = new URL(config.build.devUrl);
const commandPort = config.build.beforeDevCommand.match(/(?:^|\s)--port\s+(\d+)(?:\s|$)/)?.[1];

if (!cargo.match(/\[build-dependencies\][\s\S]*?tauri-build\s*=\s*\{[^}]*version\s*=\s*"2"/)) {
  throw new Error('src-tauri/Cargo.toml must declare tauri-build v2 as a build dependency.');
}
if (!/tauri_build::build\s*\(\s*\)/.test(build)) {
  throw new Error('src-tauri/build.rs must invoke tauri_build::build() for the Windows manifest.');
}
if (!commandPort || commandPort !== devUrl.port) {
  throw new Error(`Tauri dev port mismatch: beforeDevCommand=${commandPort ?? 'missing'}, devUrl=${devUrl.port || 'default'}.`);
}

const peIndex = process.argv.indexOf('--pe');
if (peIndex !== -1) {
  const pePath = process.argv[peIndex + 1];
  if (!pePath) throw new Error('--pe requires a Windows executable path.');
  await access(pePath);
  const bytes = await readFile(pePath);
  const text = `${bytes.toString('latin1')}\n${bytes.toString('utf16le')}`;
  const markers = [
    '<assembly',
    'urn:schemas-microsoft-com:asm.v1',
    'Microsoft.Windows.Common-Controls',
  ];
  const missing = markers.filter(marker => !text.includes(marker));
  if (missing.length > 0) {
    throw new Error(`PE manifest is missing Common Controls v6 markers: ${missing.join(', ')}`);
  }
  console.log(`Verified Windows PE manifest: ${pePath}`);
}

console.log(`Verified Tauri dev configuration: ${devUrl.href} and port ${commandPort}`);
