import { createHash } from 'node:crypto';
import { mkdir, readFile, readdir, stat, writeFile } from 'node:fs/promises';
import { join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const scripts = fileURLToPath(new URL('.', import.meta.url));
const root = resolve(scripts, '..');
const output = resolve(root, 'artifacts/bundle-inventory.json');
const roots = ['dist', 'src-tauri/binaries'];

async function filesUnder(relativeRoot) {
  const absoluteRoot = join(root, relativeRoot);
  try { await stat(absoluteRoot); } catch { throw new Error(`Missing bundle input: ${absoluteRoot}`); }
  const result = [];
  async function visit(dir) {
    for (const entry of await readdir(dir, { withFileTypes: true })) {
      const absolute = join(dir, entry.name);
      if (entry.isDirectory()) await visit(absolute);
      else if (entry.isFile()) result.push(absolute);
    }
  }
  await visit(absoluteRoot);
  return result;
}

const files = (await Promise.all(roots.map(filesUnder))).flat().sort();
const entries = [];
for (const file of files) {
  const bytes = await readFile(file);
  entries.push({
    path: relative(root, file).replaceAll('\\', '/'),
    bytes: bytes.length,
    sha256: createHash('sha256').update(bytes).digest('hex').toUpperCase(),
  });
}

const packageJson = JSON.parse(await readFile(join(root, 'package.json'), 'utf8'));
await mkdir(resolve(root, 'artifacts'), { recursive: true });
await writeFile(output, `${JSON.stringify({
  product: packageJson.name,
  version: packageJson.version,
  platform: 'windows-x64',
  offlineVisionAssets: true,
  files: entries,
}, null, 2)}\n`);
console.log(`Wrote ${relative(root, output)} (${entries.length} files)`);
