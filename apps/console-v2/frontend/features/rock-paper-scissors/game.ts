import type { RpsMove, RpsOutcome, RpsScore, RpsState, RpsStrategy, PlayerProfile, ExpertCandidate, ExpertName, ChainPrediction } from './types';

export const MOVES: RpsMove[] = ['rock', 'paper', 'scissors'];
export const COUNTER_GESTURE: Record<RpsMove, RpsMove> = { rock: 'paper', paper: 'scissors', scissors: 'rock' };
export const PLAYER_CYCLE_FORWARD: Record<RpsMove, RpsMove> = { rock: 'scissors', scissors: 'paper', paper: 'rock' };
export const PLAYER_CYCLE_REVERSE: Record<RpsMove, RpsMove> = { rock: 'paper', paper: 'scissors', scissors: 'rock' };

export const RECENT_WINDOW_SIZE = 10;
export const MIN_HISTORY = 3;
export const LOW_CONFIDENCE = 0.45;
export const EPSILON = 0.15;
export const EXPERT_SCORE_INIT = 1.0;
export const EXPERT_SCORE_MIN = 0.25;
export const EXPERT_SCORE_MAX = 3.0;
export const EXPERT_REWARD = 0.35;
export const EXPERT_PENALTY = 0.12;

export const initialScore = (): RpsScore => ({ player: 0, machine: 0, draws: 0 });
export const createInitialState = (): RpsState => ({
  phase: 'idle',
  countdown: null,
  playerMove: null,
  machineMove: null,
  outcome: null,
  invalidReason: null,
  score: initialScore(),
  round: 0,
  cameraState: 'idle',
  cameraError: null,
  stableFrames: 0,
  lastHand: null,
  action: { status: 'disabled', detail: null },
  hardwareAuthorized: false,
  roundMode: 'unlimited',
  matchWinner: null,
  strategy: 'personalized_adaptive',
  profile: createPlayerProfile(),
  chain: null,
});

export function outcomeFor(player: RpsMove, machine: RpsMove): RpsOutcome {
  if (player === machine) return 'draw';
  if (
    (player === 'rock' && machine === 'scissors') ||
    (player === 'scissors' && machine === 'paper') ||
    (player === 'paper' && machine === 'rock')
  ) {
    return 'win';
  }
  return 'lose';
}

export function scoreFor(score: RpsScore, outcome: Exclude<RpsOutcome, null>): RpsScore {
  return {
    player: score.player + (outcome === 'win' ? 1 : 0),
    machine: score.machine + (outcome === 'lose' ? 1 : 0),
    draws: score.draws + (outcome === 'draw' ? 1 : 0),
  };
}

export function resetScore(): RpsScore { return initialScore(); }

export function createPlayerProfile(): PlayerProfile {
  return {
    validRounds: 0,
    humanCounts: { rock: 0, paper: 0, scissors: 0 },
    recentWindow: [],
    transitionCounts: { rock: { rock: 0, paper: 0, scissors: 0 }, paper: { rock: 0, paper: 0, scissors: 0 }, scissors: { rock: 0, paper: 0, scissors: 0 } },
    afterWinCounts: { rock: 0, paper: 0, scissors: 0 },
    afterLoseCounts: { rock: 0, paper: 0, scissors: 0 },
    afterDrawCounts: { rock: 0, paper: 0, scissors: 0 },
    lastHuman: null,
    lastResultForHuman: null,
    machineWins: 0,
    humanWins: 0,
    draws: 0,
    expertScores: { streak: 1.0, cycle: 1.0, alternation: 1.0, transition: 1.0, result_reaction: 1.0, recent_shape: 1.0, frequency_bias: 1.0 },
    pendingExpertPredictions: {},
    selectedExpert: null,
  };
}

function clamp01(value: number): number {
  return Math.max(0.0, Math.min(1.0, value));
}

function dominantGesture(gestures: RpsMove[]): { top: RpsMove; topCount: number; total: number } | null {
  const counts: Record<RpsMove, number> = { rock: 0, paper: 0, scissors: 0 };
  for (const gesture of gestures) {
    if (counts[gesture] !== undefined) counts[gesture] += 1;
  }
  const total = counts.rock + counts.paper + counts.scissors;
  if (total <= 0) return null;
  let maxCount = 0;
  let maxGesture: RpsMove = 'rock';
  for (const gesture of MOVES) {
    if (counts[gesture] > maxCount) {
      maxCount = counts[gesture];
      maxGesture = gesture;
    }
  }
  return { top: maxGesture, topCount: maxCount, total };
}

function addWeightedCounts(scores: Record<RpsMove, number>, counts: Record<RpsMove, number>, weight: number): boolean {
  const total = counts.rock + counts.paper + counts.scissors;
  if (total <= 0) return false;
  for (const gesture of MOVES) {
    scores[gesture] += weight * (counts[gesture] / total);
  }
  return true;
}

function predictionFromScores(scores: Record<RpsMove, number>, reason: string, validRounds: number, rawTotal: number, random: () => number): { prediction: RpsMove; confidence: number; scores: Record<RpsMove, number> } {
  const total = scores.rock + scores.paper + scores.scissors;
  if (total <= 1e-9) {
    const prediction: RpsMove = MOVES[Math.floor(random() * MOVES.length)];
    return { prediction, confidence: 0, scores: { rock: 0, paper: 0, scissors: 0 } };
  }
  const normalized: Record<RpsMove, number> = {
    rock: scores.rock / total,
    paper: scores.paper / total,
    scissors: scores.scissors / total,
  };
  const prediction: RpsMove = MOVES.reduce((a, b) => normalized[a] >= normalized[b] ? a : b);
  const historyFactor = Math.min(1.0, Math.max(validRounds, rawTotal) / Math.max(1, MIN_HISTORY));
  const confidence = normalized[prediction] * historyFactor;
  return { prediction, confidence, scores: normalized };
}

function predictByFrequency(profile: PlayerProfile, random: () => number): { prediction: RpsMove; confidence: number; reason: string } {
  const scores: Record<RpsMove, number> = { rock: 0, paper: 0, scissors: 0 };
  const rawTotal = profile.humanCounts.rock + profile.humanCounts.paper + profile.humanCounts.scissors;
  if (addWeightedCounts(scores, profile.humanCounts, 1.0)) {
    const result = predictionFromScores(scores, 'frequency', profile.validRounds, rawTotal, random);
    return { prediction: result.prediction, confidence: result.confidence, reason: 'frequency' };
  }
  const result = predictionFromScores(scores, 'frequency_empty', profile.validRounds, 0, random);
  return { prediction: result.prediction, confidence: result.confidence, reason: 'frequency_empty' };
}

function predictByMarkov(profile: PlayerProfile, random: () => number): { prediction: RpsMove; confidence: number; reason: string } {
  const scores: Record<RpsMove, number> = { rock: 0, paper: 0, scissors: 0 };
  const lastHuman = profile.lastHuman;
  if (lastHuman) {
    const row = profile.transitionCounts[lastHuman];
    const rowTotal = row.rock + row.paper + row.scissors;
    if (addWeightedCounts(scores, row, 1.0)) {
      const result = predictionFromScores(scores, 'markov', profile.validRounds, rowTotal, random);
      return { prediction: result.prediction, confidence: result.confidence, reason: 'markov' };
    }
  }
  const fallbackTotal = profile.humanCounts.rock + profile.humanCounts.paper + profile.humanCounts.scissors;
  if (addWeightedCounts(scores, profile.humanCounts, 1.0)) {
    const result = predictionFromScores(scores, 'markov_frequency_fallback', profile.validRounds, fallbackTotal, random);
    return { prediction: result.prediction, confidence: result.confidence, reason: 'markov_frequency_fallback' };
  }
  const result = predictionFromScores(scores, 'markov_empty', profile.validRounds, 0, random);
  return { prediction: result.prediction, confidence: result.confidence, reason: 'markov_empty' };
}

function expertCandidate(name: string, prediction: RpsMove, confidence: number, detail: string): ExpertCandidate | null {
  if (confidence <= 0.0) return null;
  return { name: name as ExpertCandidate['name'], prediction, baseConfidence: clamp01(confidence), detail };
}

function repeatLen(recent: RpsMove[]): { gesture: RpsMove; length: number } | null {
  if (!recent.length) return null;
  let bestGesture: RpsMove = recent[0];
  let bestLength = 0;
  let currentGesture = recent[0];
  let currentLength = 0;
  for (const gesture of recent) {
    if (gesture === currentGesture) {
      currentLength += 1;
    } else {
      if (currentLength > bestLength) {
        bestLength = currentLength;
        bestGesture = currentGesture;
      }
      currentGesture = gesture;
      currentLength = 1;
    }
  }
  if (currentLength > bestLength) {
    bestLength = currentLength;
    bestGesture = currentGesture;
  }
  return { gesture: bestGesture, length: bestLength };
}

function buildPersonalizedExperts(profile: PlayerProfile): ExpertCandidate[] {
  const recent = profile.recentWindow;
  const experts: (ExpertCandidate | null)[] = [];

  const repeated = repeatLen(recent);
  if (repeated && repeated.length >= 2) {
    const confidence = Math.min(0.92, 0.52 + 0.12 * repeated.length);
    experts.push(expertCandidate('streak', repeated.gesture, confidence, `repeat_len=${repeated.length}`));
  }

  if (recent.length >= 4) {
    for (const [name, cycleMap] of [['cycle_forward', PLAYER_CYCLE_FORWARD] as const, ['cycle_reverse', PLAYER_CYCLE_REVERSE] as const]) {
      const pairs: [RpsMove, RpsMove][] = [];
      for (let i = Math.max(0, recent.length - 5); i < recent.length - 1; i++) {
        pairs.push([recent[i], recent[i + 1]]);
      }
      if (!pairs.length) continue;
      const hits = pairs.filter(([prev, cur]) => cycleMap[prev] === cur).length;
      const ratio = hits / pairs.length;
      if (ratio >= 0.66 && cycleMap[recent[recent.length - 1]]) {
        const predicted = cycleMap[recent[recent.length - 1]];
        experts.push(expertCandidate('cycle', predicted, Math.min(0.90, 0.45 + 0.45 * ratio), name));
      }
    }
  }

  if (recent.length >= 4) {
    const suffix = recent.slice(-4);
    if (suffix[0] === suffix[2] && suffix[1] === suffix[3] && suffix[0] !== suffix[1]) {
      experts.push(expertCandidate('alternation', suffix[0], 0.82, 'ABAB'));
    }
  }

  const lastHuman = profile.lastHuman;
  if (lastHuman) {
    const row = profile.transitionCounts[lastHuman];
    const dom = dominantGesture(
      MOVES.flatMap(gesture => Array(row[gesture] ? row[gesture] : 0).fill(gesture))
    );
    if (dom) {
      const confidence = Math.min(0.88, 0.35 + 0.50 * (dom.topCount / dom.total) + 0.05 * Math.min(dom.total, 3));
      experts.push(expertCandidate('transition', dom.top, confidence, `after_${lastHuman}:${dom.topCount}/${dom.total}`));
    }
  }

  const reactionMap: Record<string, { counts: Record<RpsMove, number>; detail: string }> = {
    win: { counts: profile.afterWinCounts, detail: 'after_win' },
    lose: { counts: profile.afterLoseCounts, detail: 'after_lose' },
    draw: { counts: profile.afterDrawCounts, detail: 'after_draw' },
  };
  const resultKey = profile.lastResultForHuman;
  if (resultKey && reactionMap[resultKey]) {
    const { counts, detail } = reactionMap[resultKey];
    const dom = dominantGesture(
      MOVES.flatMap(gesture => Array(counts[gesture] ? counts[gesture] : 0).fill(gesture))
    );
    if (dom) {
      const confidence = Math.min(0.84, 0.34 + 0.48 * (dom.topCount / dom.total) + 0.04 * Math.min(dom.total, 3));
      experts.push(expertCandidate('result_reaction', dom.top, confidence, `${detail}:${dom.topCount}/${dom.total}`));
    }
  }

  if (recent.length >= 3) {
    const window = recent.slice(-Math.min(5, recent.length));
    const dom = dominantGesture(window);
    if (dom && dom.topCount >= 2) {
      const confidence = Math.min(0.78, 0.30 + 0.45 * (dom.topCount / dom.total));
      experts.push(expertCandidate('recent_shape', dom.top, confidence, `last${dom.total}:${dom.topCount}`));
    }
  }

  const global = dominantGesture(
    MOVES.flatMap(gesture => Array(profile.humanCounts[gesture] ? profile.humanCounts[gesture] : 0).fill(gesture))
  );
  if (global) {
    const confidence = Math.min(0.70, 0.25 + 0.40 * (global.topCount / global.total) + 0.03 * Math.min(global.total, 5));
    experts.push(expertCandidate('frequency_bias', global.top, confidence, `global:${global.topCount}/${global.total}`));
  }

  return experts.filter(e => e !== null);
}

function selectPersonalizedExpert(experts: ExpertCandidate[], profile: PlayerProfile, random: () => number): { prediction: RpsMove; selectedExpert: ExpertName; confidence: number; reason: string } {
  if (!experts.length) {
    const fallback: RpsMove = MOVES[Math.floor(random() * MOVES.length)];
    return { prediction: fallback, selectedExpert: 'frequency_bias', confidence: 0, reason: 'expert_cold_start' };
  }

  const ranked: { finalScore: number; learnedScore: number; expert: ExpertCandidate }[] = [];
  for (const expert of experts) {
    const learnedScore = profile.expertScores[expert.name] ?? EXPERT_SCORE_INIT;
    const learnedFactor = 0.72 + Math.min(EXPERT_SCORE_MAX, learnedScore) / EXPERT_SCORE_MAX * 0.55;
    const historyTotal = profile.humanCounts.rock + profile.humanCounts.paper + profile.humanCounts.scissors;
    const historyFactor = Math.min(1.0, Math.max(0.35, historyTotal / Math.max(1, MIN_HISTORY)));
    const finalScore = expert.baseConfidence * learnedFactor * historyFactor;
    ranked.push({ finalScore, learnedScore, expert });
  }

  ranked.sort((a, b) => b.finalScore - a.finalScore || b.learnedScore - a.learnedScore);
  const selected = ranked[0];
  const confidence = Math.max(0.0, Math.min(0.98, selected.finalScore));
  const reason = `expert:${selected.expert.name}:${selected.expert.detail}:learned=${selected.learnedScore.toFixed(2)}`;
  return { prediction: selected.expert.prediction, selectedExpert: selected.expert.name, confidence, reason };
}

export function predictHumanNextGesture(profile: PlayerProfile, strategy: RpsStrategy, random: () => number): { prediction: RpsMove; confidence: number; reason: string; experts: ExpertCandidate[]; scores: Record<RpsMove, number> } {
  let prediction: RpsMove;
  let confidence: number;
  let reason: string;
  let experts: ExpertCandidate[] = [];
  let scores: Record<RpsMove, number> = { rock: 0, paper: 0, scissors: 0 };

  if (strategy === 'random') {
    prediction = MOVES[Math.floor(random() * MOVES.length)];
    confidence = 0;
    reason = 'random';
    scores = { rock: 1 / 3, paper: 1 / 3, scissors: 1 / 3 };
  } else if (strategy === 'frequency') {
    const result = predictByFrequency(profile, random);
    prediction = result.prediction;
    confidence = result.confidence;
    reason = result.reason;
    scores = { rock: 0, paper: 0, scissors: 0 };
    const freqTotal = profile.humanCounts.rock + profile.humanCounts.paper + profile.humanCounts.scissors;
    if (freqTotal > 0) {
      scores.rock = profile.humanCounts.rock / freqTotal;
      scores.paper = profile.humanCounts.paper / freqTotal;
      scores.scissors = profile.humanCounts.scissors / freqTotal;
    }
  } else if (strategy === 'markov') {
    const result = predictByMarkov(profile, random);
    prediction = result.prediction;
    confidence = result.confidence;
    reason = result.reason;
    scores = { rock: 0, paper: 0, scissors: 0 };
    const lastHuman = profile.lastHuman;
    if (lastHuman) {
      const row = profile.transitionCounts[lastHuman];
      const rowTotal = row.rock + row.paper + row.scissors;
      if (rowTotal > 0) {
        scores.rock = row.rock / rowTotal;
        scores.paper = row.paper / rowTotal;
        scores.scissors = row.scissors / rowTotal;
      } else {
        const total = profile.humanCounts.rock + profile.humanCounts.paper + profile.humanCounts.scissors;
        if (total > 0) {
          scores.rock = profile.humanCounts.rock / total;
          scores.paper = profile.humanCounts.paper / total;
          scores.scissors = profile.humanCounts.scissors / total;
        }
      }
    } else {
      const total = profile.humanCounts.rock + profile.humanCounts.paper + profile.humanCounts.scissors;
      if (total > 0) {
        scores.rock = profile.humanCounts.rock / total;
        scores.paper = profile.humanCounts.paper / total;
        scores.scissors = profile.humanCounts.scissors / total;
      }
    }
  } else {
    experts = buildPersonalizedExperts(profile);
    const pending: Partial<Record<string, RpsMove>> = {};
    for (const expert of experts) {
      if (!expert) continue;
      pending[expert.name] = expert.prediction;
    }
    profile = { ...profile, pendingExpertPredictions: pending };
    const selected = selectPersonalizedExpert(experts, profile, random);
    prediction = selected.prediction;
    confidence = selected.confidence;
    reason = selected.reason;
    profile = { ...profile, selectedExpert: selected.selectedExpert };
    if (!prediction) {
      prediction = MOVES[Math.floor(random() * MOVES.length)];
      confidence = 0;
      reason = 'expert_cold_start';
    }
    scores = { rock: 0, paper: 0, scissors: 0 };
    scores[prediction] = confidence;
  }

  return { prediction, confidence, reason, experts, scores };
}

export function chooseMachineGesture(profile: PlayerProfile, strategy: RpsStrategy, random: () => number): { machineGesture: RpsMove; chain: ChainPrediction } {
  const { prediction, confidence, reason, experts, scores } = predictHumanNextGesture(profile, strategy, random);

  let machineGesture: RpsMove;
  let decisionReason: string;

  if (strategy === 'random') {
    machineGesture = MOVES[Math.floor(random() * MOVES.length)];
    decisionReason = 'random_mode';
  } else if (confidence < LOW_CONFIDENCE) {
    machineGesture = MOVES[Math.floor(random() * MOVES.length)];
    decisionReason = `low_confidence:${reason}`;
  } else if (strategy === 'personalized_adaptive' && random() < EPSILON) {
    machineGesture = MOVES[Math.floor(random() * MOVES.length)];
    decisionReason = `epsilon_random:${reason}`;
  } else {
    machineGesture = COUNTER_GESTURE[prediction];
    decisionReason = `counter:${reason}`;
  }

  const chain: ChainPrediction = {
    prediction,
    confidence,
    reason,
    machineDecision: machineGesture,
    decisionReason,
    experts,
    scores,
  };

  return { machineGesture, chain };
}

export function resultForHuman(result: string): 'win' | 'lose' | 'draw' | null {
  if (result === 'human') return 'win';
  if (result === 'machine') return 'lose';
  if (result === 'draw') return 'draw';
  return null;
}

export function updatePlayerProfile(profile: PlayerProfile, human: RpsMove, machine: RpsMove, result: string, chain: ChainPrediction | null): PlayerProfile {
  if (human !== 'rock' && human !== 'paper' && human !== 'scissors') return profile;
  if (result !== 'human' && result !== 'machine' && result !== 'draw') return profile;

  const previousHuman = profile.lastHuman;
  const previousResult = profile.lastResultForHuman;
  const validRounds = profile.validRounds + 1;
  const humanCounts = { ...profile.humanCounts, [human]: profile.humanCounts[human] + 1 };

  const recentWindow = [...profile.recentWindow, human];
  if (recentWindow.length > RECENT_WINDOW_SIZE) recentWindow.splice(0, recentWindow.length - RECENT_WINDOW_SIZE);

  const transitionCounts = { ...profile.transitionCounts };
  if (previousHuman) {
    transitionCounts[previousHuman] = { ...transitionCounts[previousHuman], [human]: transitionCounts[previousHuman][human] + 1 };
  }

  const afterWinCounts = { ...profile.afterWinCounts };
  const afterLoseCounts = { ...profile.afterLoseCounts };
  const afterDrawCounts = { ...profile.afterDrawCounts };
  if (previousResult === 'win') afterWinCounts[human] += 1;
  if (previousResult === 'lose') afterLoseCounts[human] += 1;
  if (previousResult === 'draw') afterDrawCounts[human] += 1;

  let expertScores = { ...profile.expertScores };
  const pending = chain?.experts ? chain.experts.filter(e => e && e.name && e.prediction) : [];
  if (pending.length) {
    for (const expert of pending) {
      const current = expertScores[expert.name] ?? EXPERT_SCORE_INIT;
      if (expert.prediction === human) {
        expertScores[expert.name] = Math.min(EXPERT_SCORE_MAX, current + EXPERT_REWARD);
      } else {
        expertScores[expert.name] = Math.max(EXPERT_SCORE_MIN, current - EXPERT_PENALTY);
      }
    }
  }

  const machineWins = profile.machineWins + (result === 'machine' ? 1 : 0);
  const humanWins = profile.humanWins + (result === 'human' ? 1 : 0);
  const draws = profile.draws + (result === 'draw' ? 1 : 0);
  const lastHuman: RpsMove | null = human;
  const lastResultForHuman = resultForHuman(result);

  return {
    validRounds,
    humanCounts,
    recentWindow,
    transitionCounts,
    afterWinCounts,
    afterLoseCounts,
    afterDrawCounts,
    lastHuman,
    lastResultForHuman,
    machineWins,
    humanWins,
    draws,
    expertScores,
    pendingExpertPredictions: {},
    selectedExpert: null,
  };
}
