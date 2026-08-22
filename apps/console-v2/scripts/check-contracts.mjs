import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const root = resolve(import.meta.dirname, '..');
const expected = execFileSync('cargo', ['run', '--quiet', '--package', 'console-contracts', '--bin', 'generate-contracts'], { cwd: root, encoding: 'utf8' });
const checkedIn = readFileSync(resolve(root, 'frontend/shared/contracts/generated.ts'), 'utf8');
// Git may materialize the checked-in projection with CRLF on Windows while
// cargo emits LF. Compare the generated contract content, not checkout EOLs.
const normalizeEol = (value) => value.replace(/\r\n/g, '\n');
if (normalizeEol(expected) !== normalizeEol(checkedIn)) {
  console.error('generated.ts is stale; run pnpm generate:contracts');
  process.exit(1);
}
