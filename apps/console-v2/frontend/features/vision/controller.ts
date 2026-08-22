import type { DeviceModel, VisionPoseProposal } from '../../shared/contracts';
import type { HandLandmark, VisionLandmarkResult, VisionRuntimeSnapshot, VisionRuntimeState } from '../../shared/vision-runtime';
import { classifyGesture, GestureStabilizer, mapLandmarksToO6, PoseMapper, SessionCalibration, type Gesture, type MapperSettings } from './model';

export const MIN_PROPOSAL_CONFIDENCE = 0.7;

export interface VisionRuntimeLike {
  start(video: HTMLVideoElement, source: 'vision'): Promise<void>;
  stop(): Promise<void>;
  snapshot(): VisionRuntimeSnapshot;
  subscribe(listener: (snapshot: VisionRuntimeSnapshot) => void): () => void;
  onResult(listener: (result: VisionLandmarkResult) => void): () => void;
}
export interface VisionProposalController {
  submit(proposal: VisionPoseProposal): void | Promise<void>;
  revoke(reason: string): void | Promise<void>;
}

export interface VisionFeatureSnapshot {
  runtime: VisionRuntimeSnapshot;
  calibration: ReturnType<SessionCalibration['snapshot']>;
  gesture: Gesture;
  confidence: number;
  authorized: boolean;
  proposalAllowed: boolean;
  lastProposal: VisionPoseProposal | null;
  lastError: string | null;
}

type FeatureListener = (snapshot: VisionFeatureSnapshot) => void;

const noOpController: VisionProposalController = {
  submit: () => undefined,
  revoke: () => undefined,
};

function isActiveRuntime(snapshot: VisionRuntimeSnapshot): boolean {
  return snapshot.state === 'running' && snapshot.owner === 'vision';
}

export interface ProposalEligibility {
  model: DeviceModel;
  authorized: boolean;
  calibrated: boolean;
  confidence: number;
  locked: boolean;
  runtimeState: VisionRuntimeState;
  runtimeOwner: VisionRuntimeSnapshot['owner'];
}

export function canSubmitProposal(input: ProposalEligibility): boolean {
  return input.model === 'O6'
    && input.authorized
    && input.calibrated
    && input.confidence >= MIN_PROPOSAL_CONFIDENCE
    && !input.locked
    && input.runtimeState === 'running'
    && input.runtimeOwner === 'vision';
}

export class VisionFeatureController {
  private readonly runtime: VisionRuntimeLike;
  private readonly sink: VisionProposalController;
  private readonly calibration = new SessionCalibration();
  private readonly stabilizer = new GestureStabilizer();
  private readonly mapper: PoseMapper;
  private readonly listeners = new Set<FeatureListener>();
  private readonly unsubscribeRuntime: () => void;
  private readonly unsubscribeResult: () => void;
  private runtimeSnapshot: VisionRuntimeSnapshot;
  private model: DeviceModel = 'L7';
  private locked = false;
  private stopped = true;
  private authorized = false;
  private gesture: Gesture = 'unknown';
  private confidence = 0;
  private lastProposal: VisionPoseProposal | null = null;
  private lastError: string | null = null;

  constructor(runtime: VisionRuntimeLike, sink: VisionProposalController = noOpController, mapperSettings?: Partial<MapperSettings>) {
    this.runtime = runtime;
    this.sink = sink;
    this.mapper = new PoseMapper(mapperSettings);
    this.runtimeSnapshot = runtime.snapshot();
    this.unsubscribeRuntime = runtime.subscribe(snapshot => {
      this.runtimeSnapshot = snapshot;
      if (!isActiveRuntime(snapshot)) this.revoke('视觉运行已停止');
      this.emit();
    });
    this.unsubscribeResult = runtime.onResult(result => this.handleResult(result));
  }

  subscribe(listener: FeatureListener): () => void {
    this.listeners.add(listener);
    listener(this.snapshot());
    return () => this.listeners.delete(listener);
  }

  snapshot(): VisionFeatureSnapshot {
    const proposalAllowed = canSubmitProposal({
      model: this.model,
      authorized: this.authorized,
      calibrated: this.calibration.snapshot().complete,
      confidence: this.confidence,
      locked: this.locked || this.stopped,
      runtimeState: this.runtimeSnapshot.state,
      runtimeOwner: this.runtimeSnapshot.owner,
    });
    return {
      runtime: this.runtimeSnapshot,
      calibration: this.calibration.snapshot(),
      gesture: this.gesture,
      confidence: this.confidence,
      authorized: this.authorized,
      proposalAllowed,
      lastProposal: this.lastProposal,
      lastError: this.lastError,
    };
  }

  setModel(model: DeviceModel): void {
    this.model = model;
    if (model !== 'O6') {
      this.authorized = false;
      this.revoke('当前型号不支持视觉同步');
    }
    this.emit();
  }

  setLocked(locked: boolean): void {
    this.locked = locked;
    if (locked) {
      this.authorized = false;
      this.revoke('控制已锁定');
    }
    this.emit();
  }

  setAuthorized(authorized: boolean): void {
    if (authorized && (this.model !== 'O6' || this.locked || this.stopped)) return;
    this.authorized = authorized;
    if (!authorized) this.revoke('操作员未允许同步');
    this.emit();
  }

  beginCalibration(): void {
    this.calibration.begin();
    this.mapper.reset();
    this.revoke('校准进行中');
    this.emit();
  }

  updateMapperSettings(settings: Partial<MapperSettings>): void {
    this.mapper.setSettings(settings);
    this.emit();
  }

  mapperSettings(): MapperSettings { return this.mapper.settings(); }

  async start(video: HTMLVideoElement): Promise<void> {
    this.lastError = null;
    this.stopped = false;
    try {
      await this.runtime.start(video, 'vision');
      this.runtimeSnapshot = this.runtime.snapshot();
      this.emit();
    } catch (error) {
      this.stopped = true;
      this.lastError = error instanceof Error ? error.message : '无法启动视觉输入';
      this.emit();
      throw error;
    }
  }

  async stop(): Promise<void> {
    this.stopped = true;
    this.authorized = false;
    this.revoke('视觉输入已停止');
    if (this.runtime.snapshot().owner === 'vision') await this.runtime.stop();
    this.runtimeSnapshot = this.runtime.snapshot();
    this.emit();
  }

  async dispose(): Promise<void> {
    this.stopped = true;
    this.authorized = false;
    this.revoke('视觉页面已离开');
    this.unsubscribeResult();
    this.unsubscribeRuntime();
    if (this.runtime.snapshot().owner === 'vision') await this.runtime.stop();
    this.listeners.clear();
  }

  private handleResult(result: VisionLandmarkResult): void {
    if (this.stopped || result.source !== 'vision') return;
    const hand = this.bestHand(result.hands);
    if (!hand) {
      this.gesture = 'unknown';
      this.confidence = 0;
      this.emit();
      return;
    }
    const observation = classifyGesture(hand);
    const stable = this.stabilizer.update(observation.gesture, observation.confidence);
    this.gesture = stable.gesture;
    this.confidence = stable.confidence;
    this.calibration.accept(stable.gesture, hand.landmarks);
    if (canSubmitProposal({
      model: this.model,
      authorized: this.authorized,
      calibrated: this.calibration.snapshot().complete,
      confidence: this.confidence,
      locked: this.locked || this.stopped,
      runtimeState: this.runtimeSnapshot.state,
      runtimeOwner: this.runtimeSnapshot.owner,
    })) {
      const positions = this.mapper.map(hand.landmarks, this.calibration.snapshot());
      const proposal: VisionPoseProposal = {
        schemaVersion: 1,
        id: `vision-${result.frameSequence}`,
        label: this.gesture === 'open' ? '张开手掌' : '握拳',
        confidence: this.confidence,
        positions,
        expiresAtMonotonicMs: result.monotonicTimeMs + 500,
      };
      this.lastProposal = proposal;
      try {
        void this.sink.submit(proposal);
      } catch (error) {
        this.lastError = error instanceof Error ? error.message : '视觉建议提交失败';
      }
    }
    this.emit();
  }

  private bestHand(hands: HandLandmark[]): HandLandmark | null {
    return hands.filter(hand => hand.landmarks.length === 21).sort((a, b) => b.confidence - a.confidence)[0] ?? null;
  }

  private revoke(reason: string): void {
    this.lastProposal = null;
    try { void this.sink.revoke(reason); } catch (error) { this.lastError = error instanceof Error ? error.message : '视觉建议撤销失败'; }
  }

  private emit(): void {
    const next = this.snapshot();
    this.listeners.forEach(listener => listener(next));
  }
}
