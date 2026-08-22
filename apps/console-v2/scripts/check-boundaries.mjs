import { spawnSync } from 'node:child_process';
import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { dirname, isAbsolute, relative, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url));
export const CONSOLE_ROOT = resolve(SCRIPT_DIR, '..');

const IMPORT_LINE = /^\s*(?:import|export)\b(?:\s+type\b)?(?:[^'"\r\n]+?\sfrom\s+)?["']([^"']+)["']/gm;
const DYNAMIC_IMPORT = /\bimport\s*\(\s*["']([^"']+)["']\s*\)/g;
const PYTHON_IMPORT = /^\s*(?:from|import)\s+([A-Za-z_][\w.]*)/gm;
const TS_EXTENSIONS = new Set(['.ts', '.tsx', '.mts', '.cts', '.d.ts']);
const PYTHON_EXTENSIONS = new Set(['.py']);
const WORKER_SHARED_ALLOWLIST = new Set(['contracts', 'vision-runtime']);
const SIDECAR_FORBIDDEN_SEGMENTS = new Set([
  'frontend',
  'ui',
  'feature',
  'features',
  'product_state',
  'productstate',
  'product-state',
  'app_state',
  'appstate',
  'view_state',
  'viewstate',
]);

const slash = (value) => value.replaceAll('\\', '/');
const relativeDisplay = (root, file) => slash(relative(root, file)) || '.';

function filesUnder(directory, extensions) {
  if (!existsSync(directory)) return [];
  const files = [];
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const file = resolve(directory, entry.name);
    if (entry.isDirectory()) files.push(...filesUnder(file, extensions));
    else if (extensions.has(entry.name.endsWith('.d.ts') ? '.d.ts' : file.slice(file.lastIndexOf('.')))) files.push(file);
  }
  return files;
}

function importSpecifiers(source) {
  const result = [];
  for (const match of source.matchAll(IMPORT_LINE)) result.push(match[1]);
  for (const match of source.matchAll(DYNAMIC_IMPORT)) result.push(match[1]);
  return result;
}

export function classifyFrontendPath(frontendRoot, file) {
  const rel = slash(relative(frontendRoot, file));
  const parts = rel.split('/');
  if (parts[0] === '..' || isAbsolute(rel)) return { kind: 'outside', rel };
  if (parts[0] === 'features' && parts[1]) return { kind: 'feature', name: parts[1], rel };
  if (parts[0] === 'shared' && parts[1]) return { kind: 'shared', area: parts[1], rel };
  if (parts[0] === 'workers' && parts[1]) return { kind: 'worker', name: parts[1], rel };
  if (parts[0] === 'app') return { kind: 'app', rel };
  return { kind: 'frontend', rel };
}

function classifyImport(frontendRoot, sourceFile, specifier) {
  const normalized = slash(specifier);
  const isAlias = normalized.startsWith('@/') || normalized.startsWith('~/');
  const isRelative = normalized.startsWith('./') || normalized.startsWith('../') || normalized === '.' || normalized === '..';
  if (!isAlias && !isRelative && !normalized.startsWith('/')) return { kind: 'external', specifier };
  const target = isAlias
    ? resolve(frontendRoot, normalized.slice(2))
    : resolve(dirname(sourceFile), normalized);
  return { ...classifyFrontendPath(frontendRoot, target), specifier, target };
}

function boundaryViolation(source, target, reason) {
  return `${source}: ${reason} (${target.specifier})`;
}

export function checkFrontendBoundaries(root = CONSOLE_ROOT, options = {}) {
  const frontendRoot = resolve(root, 'frontend');
  const violations = [];
  const files = options.files ?? filesUnder(frontendRoot, TS_EXTENSIONS);
  for (const file of files) {
    const source = classifyFrontendPath(frontendRoot, file);
    if (source.kind === 'outside') continue;
    const sourceLabel = relativeDisplay(root, file);
    for (const specifier of importSpecifiers(readFileSync(file, 'utf8'))) {
      const target = classifyImport(frontendRoot, file, specifier);
      if (target.kind === 'external') continue;
      if (source.kind === 'feature') {
        if (target.kind === 'feature' && target.name === source.name) continue;
        if (target.kind === 'shared') continue;
        violations.push(boundaryViolation(sourceLabel, target, 'feature may import only itself or shared/public contracts'));
      } else if (source.kind === 'shared') {
        if (target.kind === 'shared') continue;
        violations.push(boundaryViolation(sourceLabel, target, 'shared may not depend on features, app, workers, or outside frontend modules'));
      } else if (source.kind === 'worker') {
        if (target.kind === 'worker' && target.name === source.name) continue;
        if (target.kind === 'shared' && WORKER_SHARED_ALLOWLIST.has(target.area)) continue;
        violations.push(boundaryViolation(sourceLabel, target, 'worker may import only itself, shared contracts/runtime, or an external allowlisted package'));
      } else if (source.kind === 'frontend' && target.kind === 'feature') {
        violations.push(boundaryViolation(sourceLabel, target, 'frontend entry files must assemble through app'));
      }
    }
  }
  return violations;
}

export function checkPythonSidecar(root = CONSOLE_ROOT, options = {}) {
  const sidecarRoot = resolve(root, 'sidecar', 'linkerhand-bridge');
  const violations = [];
  const files = options.files ?? filesUnder(sidecarRoot, PYTHON_EXTENSIONS);
  for (const file of files) {
    const sourceLabel = relativeDisplay(root, file);
    for (const match of readFileSync(file, 'utf8').matchAll(PYTHON_IMPORT)) {
      const module = match[1];
      const segments = module.toLowerCase().split('.');
      const forbidden = segments.find((segment) => SIDECAR_FORBIDDEN_SEGMENTS.has(segment));
      if (forbidden) violations.push(`${sourceLabel}: sidecar may not import UI/feature product state (${module}, matched ${forbidden})`);
    }
  }
  return violations;
}

export function analyzeRustMetadata(metadata) {
  const workspaceIds = new Set(metadata.workspace_members ?? []);
  const packages = (metadata.packages ?? []).filter((pkg) => workspaceIds.has(pkg.id));
  const packageByName = new Map(packages.map((pkg) => [pkg.name, pkg]));
  const graph = new Map(packages.map((pkg) => [pkg.name, new Set(pkg.dependencies.map((dep) => dep.name).filter((name) => packageByName.has(name)))]));
  const violations = [];

  for (const pkg of packages) {
    const hasTauri = pkg.dependencies.some((dependency) => dependency.name === 'tauri');
    const manifest = slash(pkg.manifest_path ?? '');
    if (hasTauri && !manifest.endsWith('/src-tauri/Cargo.toml')) {
      violations.push(`${pkg.name}: business crates may not depend on tauri (only src-tauri is allowed)`);
    }
  }

  const adapter = graph.get('device-adapter-api');
  for (const dependency of adapter ?? []) {
    if (dependency !== 'console-contracts') {
      violations.push(`device-adapter-api: adapter API points toward ${dependency}; keep the dependency direction from runtime to adapter API`);
    }
  }

  const visiting = new Set();
  const visited = new Set();
  const stack = [];
  const visit = (name) => {
    if (visiting.has(name)) {
      const cycleStart = stack.indexOf(name);
      violations.push(`Rust workspace dependency cycle: ${[...stack.slice(cycleStart), name].join(' -> ')}`);
      return;
    }
    if (visited.has(name)) return;
    visiting.add(name);
    stack.push(name);
    for (const dependency of graph.get(name) ?? []) visit(dependency);
    stack.pop();
    visiting.delete(name);
    visited.add(name);
  };
  for (const name of graph.keys()) visit(name);
  return violations;
}

export function readRustMetadata(root = CONSOLE_ROOT) {
  const result = spawnSync('cargo', ['metadata', '--format-version', '1', '--no-deps', '--manifest-path', resolve(root, 'Cargo.toml')], {
    cwd: root,
    encoding: 'utf8',
    windowsHide: true,
  });
  if (result.error) throw new Error(`cargo metadata failed to start: ${result.error.message}`);
  if (result.status !== 0) throw new Error(`cargo metadata failed (${result.status}): ${(result.stderr || result.stdout || '').trim()}`);
  return JSON.parse(result.stdout);
}

export function checkRustBoundaries(root = CONSOLE_ROOT, options = {}) {
  const metadata = options.metadata ?? readRustMetadata(root);
  return analyzeRustMetadata(metadata);
}

export function runChecks(root = CONSOLE_ROOT, options = {}) {
  const violations = [
    ...checkFrontendBoundaries(root),
    ...checkPythonSidecar(root),
    ...(options.skipRust ? [] : checkRustBoundaries(root, options)),
  ];
  if (violations.length > 0) {
    throw new Error(`Boundary check failed with ${violations.length} violation(s):\n${violations.map((item) => `  - ${item}`).join('\n')}`);
  }
  return { checked: true, violations: [] };
}

const invokedPath = process.argv[1] ? pathToFileURL(resolve(process.argv[1])).href : '';
if (import.meta.url === invokedPath) {
  try {
    runChecks(CONSOLE_ROOT, { skipRust: process.argv.includes('--skip-rust') });
    console.log('Boundary checks passed: frontend, Rust workspace, and Python sidecar.');
  } catch (error) {
    console.error(error instanceof Error ? error.message : String(error));
    process.exitCode = 1;
  }
}
