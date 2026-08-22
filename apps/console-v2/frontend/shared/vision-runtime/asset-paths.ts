/**
 * Resolve bundled vision files against the Vite application base. This keeps
 * browser dev, a non-root production base, and the Tauri webview on the same
 * URL while preserving the path shape expected by FilesetResolver.
 */
function applicationBaseUrl(): URL {
  const documentBase = typeof document !== 'undefined' && document.baseURI ? document.baseURI : 'http://localhost/';
  return new URL(import.meta.env.BASE_URL || '/', documentBase);
}

export function visionAssetUrl(relativePath: string): string {
  return new URL(relativePath.replace(/^\/+/, ''), applicationBaseUrl()).toString();
}

/** FilesetResolver appends `/vision_wasm_*.{js,wasm}` itself. */
export function normalizeVisionAssetRootUrl(value: string): string {
  const trimmed = value.trim().replace(/\/+$/, '');
  return trimmed || '.';
}
