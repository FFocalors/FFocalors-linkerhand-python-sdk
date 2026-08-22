import parser from '@typescript-eslint/parser';
export default [{ ignores: ['dist/**', 'node_modules/**'] }, { files: ['frontend/**/*.{ts,tsx}'], languageOptions: { parser, parserOptions: { ecmaFeatures: { jsx: true }, sourceType: 'module' } } }, { files: ['frontend/features/**/*.{ts,tsx}'], rules: { 'no-restricted-imports': ['error', { patterns: ['../../features/*'] }] } }];
