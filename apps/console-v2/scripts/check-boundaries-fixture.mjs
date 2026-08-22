import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { analyzeRustMetadata, checkFrontendBoundaries, checkPythonSidecar } from './check-boundaries.mjs';

const fixture = mkdtempSync(join(tmpdir(), 'console-v2-boundaries-'));
try {
  const frontend = join(fixture, 'frontend');
  mkdirSync(join(frontend, 'features', 'alpha'), { recursive: true });
  mkdirSync(join(frontend, 'features', 'beta'), { recursive: true });
  mkdirSync(join(frontend, 'shared', 'contracts'), { recursive: true });
  mkdirSync(join(frontend, 'workers', 'camera'), { recursive: true });

  writeFileSync(join(frontend, 'features', 'alpha', 'legal.ts'), "import { value } from '../../shared/contracts/value';\nimport { local } from './local';\nexport { value, local };\n");
  writeFileSync(join(frontend, 'features', 'alpha', 'illegal.ts'), "import { Beta } from '../beta/index';\nexport { Beta };\n");
  writeFileSync(join(frontend, 'features', 'alpha', 'illegal-windows.ts'), "import { Beta } from '..\\\\beta\\\\index';\nexport { Beta };\n");
  writeFileSync(join(frontend, 'features', 'beta', 'index.ts'), 'export const Beta = 1;\n');
  writeFileSync(join(frontend, 'shared', 'contracts', 'value.ts'), 'export const value = 1;\n');
  writeFileSync(join(frontend, 'workers', 'camera', 'legal.ts'), "import { value } from '../../shared/contracts/value';\nimport { own } from './own';\nexport { value, own };\n");
  writeFileSync(join(frontend, 'workers', 'camera', 'illegal.ts'), "import { Alpha } from '../../features/alpha/index';\nexport { Alpha };\n");

  const frontendViolations = checkFrontendBoundaries(fixture);
  assert.equal(frontendViolations.length, 3);
  assert(frontendViolations.some((item) => item.includes('features/alpha/illegal.ts')));
  assert(frontendViolations.some((item) => item.includes('features/alpha/illegal-windows.ts')));
  assert(frontendViolations.some((item) => item.includes('workers/camera/illegal.ts')));

  const sidecar = join(fixture, 'sidecar', 'linkerhand-bridge');
  mkdirSync(sidecar, { recursive: true });
  writeFileSync(join(sidecar, 'legal.py'), 'from protocol.schema import ProtocolError\n');
  writeFileSync(join(sidecar, 'illegal.py'), 'from frontend.features.alpha import state\n');
  const pythonViolations = checkPythonSidecar(fixture);
  assert.equal(pythonViolations.length, 1);
  assert(pythonViolations[0].includes('frontend.features.alpha'));

  const metadata = {
    workspace_members: ['core', 'adapter', 'shell'],
    packages: [
      { id: 'core', name: 'core', manifest_path: 'C:/repo/core/Cargo.toml', dependencies: [{ name: 'adapter' }] },
      { id: 'adapter', name: 'device-adapter-api', manifest_path: 'C:/repo/adapter/Cargo.toml', dependencies: [] },
      { id: 'shell', name: 'shell', manifest_path: 'C:/repo/apps/console-v2/src-tauri/Cargo.toml', dependencies: [{ name: 'tauri' }] },
    ],
  };
  assert.deepEqual(analyzeRustMetadata(metadata), []);
  metadata.packages[0].dependencies.push({ name: 'tauri' });
  assert.equal(analyzeRustMetadata(metadata).length, 1);
  metadata.packages[0].dependencies = [{ name: 'adapter' }, { name: 'device-adapter-api' }];
  metadata.packages[1].dependencies = [{ name: 'core' }];
  assert(analyzeRustMetadata(metadata).some((item) => item.includes('dependency cycle')));
  console.log('Boundary fixture tests passed: legal and illegal frontend, sidecar, and Rust examples.');
} finally {
  rmSync(fixture, { recursive: true, force: true });
}
