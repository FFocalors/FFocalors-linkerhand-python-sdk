import { describe, expect, it } from 'vitest';
import { normalizeVisionAssetRootUrl, visionAssetUrl } from './asset-paths';

describe('vision asset paths', () => {
  it('removes the trailing separator required to prevent FilesetResolver double slashes', () => {
    expect(normalizeVisionAssetRootUrl('/vision/wasm/')).toBe('/vision/wasm');
    expect(normalizeVisionAssetRootUrl('https://tauri.localhost/base/vision/wasm///')).toBe('https://tauri.localhost/base/vision/wasm');
  });

  it('resolves bundled assets from the application base URL', () => {
    expect(visionAssetUrl('vision/wasm')).toMatch(/\/vision\/wasm$/);
    expect(visionAssetUrl('vision/hand_landmarker.task')).toMatch(/\/vision\/hand_landmarker\.task$/);
  });
});
