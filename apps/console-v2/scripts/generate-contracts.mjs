import { execFileSync } from 'node:child_process';
import { readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';

const root = resolve(import.meta.dirname, '..');
const output = execFileSync('cargo', ['run', '--quiet', '--package', 'console-contracts', '--bin', 'generate-contracts'], { cwd: root, encoding: 'utf8' });
writeFileSync(resolve(root, 'frontend/shared/contracts/generated.ts'), output);
