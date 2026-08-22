import type { RpsMove, RpsOutcome, RpsScore, RpsState } from './types';

export const MOVES: RpsMove[] = ['rock', 'paper', 'scissors'];
export const initialScore = (): RpsScore => ({ player: 0, machine: 0, draws: 0 });
export const createInitialState = (): RpsState => ({ phase: 'idle', countdown: null, playerMove: null, machineMove: null, outcome: null, invalidReason: null, score: initialScore(), round: 0, cameraState: 'idle', cameraError: null, stableFrames: 0, action: { status: 'disabled', detail: null }, hardwareAuthorized: false });

export function machineMove(random: () => number): RpsMove {
  const value = Number.isFinite(random()) ? random() : 0;
  return MOVES[Math.max(0, Math.min(MOVES.length - 1, Math.floor(value * MOVES.length)))];
}

export function outcomeFor(player: RpsMove, machine: RpsMove): RpsOutcome {
  if (player === machine) return 'draw';
  if ((player === 'rock' && machine === 'scissors') || (player === 'paper' && machine === 'rock') || (player === 'scissors' && machine === 'paper')) return 'win';
  return 'lose';
}

export function scoreFor(score: RpsScore, outcome: Exclude<RpsOutcome, null>): RpsScore {
  return { player: score.player + (outcome === 'win' ? 1 : 0), machine: score.machine + (outcome === 'lose' ? 1 : 0), draws: score.draws + (outcome === 'draw' ? 1 : 0) };
}

export function resetScore(): RpsScore { return initialScore(); }

