import type { VisionPoseProposal } from '../../shared/contracts';
export type VisionWorkerRequest = { image: ImageBitmap; source: 'vision' | 'rps' };
export type VisionWorkerResponse = { proposals: VisionPoseProposal[] };
// Real camera processing is intentionally behind this boundary for the first shell.
export const visionWorkerBoundary = { async detect(): Promise<VisionWorkerResponse> { return { proposals: [] }; } };
