import parser from '@typescript-eslint/parser';

// Keep these path groups in sync with scripts/check-boundaries.mjs. The script
// also resolves aliases and arbitrary-depth Windows paths, which ESLint's
// static import matcher cannot do reliably on its own.
const noCrossFeatureImports = { 'no-restricted-imports': ['error', { patterns: [{ group: ['**/features/**'], message: 'Features may not import another feature; compose through app.' }] }] };
const noProductImports = { 'no-restricted-imports': ['error', { patterns: [{ group: ['**/features/**', '**/app/**'], message: 'Shared modules may not depend on product features or app assembly.' }] }] };

export default [
  { ignores: ['dist/**', 'node_modules/**'] },
  { files: ['frontend/**/*.{ts,tsx}'], languageOptions: { parser, parserOptions: { ecmaFeatures: { jsx: true }, sourceType: 'module' } } },
  { files: ['frontend/features/**/*.{ts,tsx}'], rules: noCrossFeatureImports },
  { files: ['frontend/shared/**/*.{ts,tsx}'], rules: noProductImports },
  { files: ['frontend/workers/**/*.{ts,tsx}'], rules: noProductImports },
];
