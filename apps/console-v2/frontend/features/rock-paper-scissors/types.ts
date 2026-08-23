import type { DeviceCapabilities } from '../../shared/contracts';
import type { HandLandmark, VisionErrorCode, VisionLandmarkResult, VisionRuntimeSnapshot, VisionRuntimeState } from '../../shared/vision-runtime';

export type RpsMove = 'rock' | 'paper' | 'scissors';
export type RpsOutcome = 'win' | 'lose' | 'draw' | null;
export type RpsRoundMode = 'best_of_3' | 'best_of_5' | 'unlimited';
export type RpsPhase = 'idle' | 'cameraReady' | 'countdown' | 'capture' | 'recognized' | 'invalid' | 'reveal' | 'score' | 'ready' | 'matchOver';
export type RpsInvalidReason = 'no-hand' | 'multiple-hands' | 'low-confidence' | 'blurred' | 'unknown';
export type RpsActionStatus = 'disabled' | 'idle' | 'authorizing' | 'authorized' | 'dispatching' | 'executed' | 'cancelled' | 'error';
export type RpsStrategy = 'random' | 'frequency' | 'markov' | 'personalized_adaptive';
export type ExpertName = 'streak' | 'cycle' | 'alternation' | 'transition' | 'result_reaction' | 'recent_shape' | 'frequency_bias';
export type ExpertCandidate = { name: ExpertName; prediction: RpsMove; baseConfidence: number; detail: string };
export type ExpertScores = Record<ExpertName, number>;
export type ChainPrediction = {
  prediction: RpsMove; confidence: number; reason: string;
  machineDecision: RpsMove; decisionReason: string;
  experts: ExpertCandidate[];
  scores: Record<RpsMove, number>;
};
export type PlayerProfile = {
  validRounds: number;
  humanCounts: Record<RpsMove, number>;
  recentWindow: RpsMove[];
  transitionCounts: Record<RpsMove, Record<RpsMove, number>>;
  afterWinCounts: Record<RpsMove, number>;
  afterLoseCounts: Record<RpsMove, number>;
  afterDrawCounts: Record<RpsMove, number>;
  lastHuman: RpsMove | null;
  lastResultForHuman: 'win' | 'lose' | 'draw' | null;
  machineWins: number; humanWins: number; draws: number;
  expertScores: ExpertScores;
  pendingExpertPredictions: Partial<Record<ExpertName, RpsMove>>;
  selectedExpert: ExpertName | null;
};

export type RpsRuntimeListener = (snapshot: VisionRuntimeSnapshot) => void;
export type RpsResultListener = (result: VisionLandmarkResult) => void;

/** The smallest surface accepted from the app-owned singleton VisionRuntime. */
export interface RpsVisionRuntime {
  start(video: HTMLVideoElement, source: 'rps', deviceId?: string): Promise<void>;
  stop(): Promise<void>;
  subscribe(listener: RpsRuntimeListener): () => void;
  onResult(listener: RpsResultListener): () => void;
  snapshot(): VisionRuntimeSnapshot;
}

export type RpsActionRequest = { move: RpsMove; round: number; reason: 'rps-reveal' | 'rps-test' };
export type RpsActionResult = { status: 'executed' | 'cancelled' | 'error'; message?: string };

/** Feature-local hardware boundary. It must be supplied by the app; RPS never creates one. */
export interface RpsActionSink {
  authorize(): Promise<boolean>;
  dispatch(request: RpsActionRequest): Promise<RpsActionResult>;
  cancel(reason: 'locked' | 'stopped' | 'unmounted' | 'reset'): Promise<void>;
  snapshot?(): { status: RpsActionStatus; detail?: string };
}
export type RpsActionController = RpsActionSink;

export type RpsSchedulerHandle = number;
export interface RpsScheduler {
  setTimeout(callback: () => void, delayMs: number): RpsSchedulerHandle;
  clearTimeout(handle: RpsSchedulerHandle): void;
}

export type RpsScore = { player: number; machine: number; draws: number };
export type RpsActionState = { status: RpsActionStatus; detail: string | null };

export type RpsState = {
  phase: RpsPhase;
  countdown: 3 | 2 | 1 | null;
  playerMove: RpsMove | null;
  machineMove: RpsMove | null;
  outcome: RpsOutcome;
  invalidReason: RpsInvalidReason | null;
  score: RpsScore;
  round: number;
  cameraState: VisionRuntimeState;
  cameraError: { code: VisionErrorCode; message: string } | null;
  stableFrames: number;
  lastHand: HandLandmark | null;
  action: RpsActionState;
  hardwareAuthorized: boolean;
  roundMode: RpsRoundMode;
  matchWinner: 'player' | 'machine' | null;
  strategy: RpsStrategy;
  profile: PlayerProfile;
  chain: ChainPrediction | null;
};

export type RpsCapabilities = Pick<DeviceCapabilities, 'model' | 'supportedOperations'>;

export const MOVE_LABELS: Record<RpsMove, string> = { rock: '石头', paper: '布', scissors: '剪刀' };
export const MOVE_ICONS: Record<RpsMove, string> = { rock: '●', paper: '▤', scissors: '✂' };
export const INVALID_LABELS: Record<RpsInvalidReason, string> = {
  'no-hand': '没有检测到手，请把手放入画面',
  'multiple-hands': '检测到多只手，请只保留一只手',
  'low-confidence': '手势置信度不足，请靠近光线充足处',
  blurred: '画面较模糊，请保持手部稳定',
  unknown: '手势不明确，请重新比划'
};
export const STRATEGY_LABELS: Record<RpsStrategy, string> = {
  random: '随机模式', frequency: '频率统计', markov: '马尔可夫预测', personalized_adaptive: '个体化自适应',
};
export const STRATEGY_ORDER: RpsStrategy[] = ['random', 'frequency', 'markov', 'personalized_adaptive'];

export const ROUND_MODE_LABELS: Record<RpsRoundMode, string> = {
  best_of_3: '三局两胜', best_of_5: '五局三胜', unlimited: '无限制',
};
export const ROUND_MODE_ORDER: RpsRoundMode[] = ['best_of_3', 'best_of_5', 'unlimited'];
