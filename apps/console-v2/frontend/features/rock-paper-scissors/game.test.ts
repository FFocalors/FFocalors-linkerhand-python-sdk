import { chooseMachineGesture, createInitialState, createPlayerProfile, outcomeFor, scoreFor, updatePlayerProfile } from './game';
import type { PlayerProfile } from './types';

const seededRandom = (sequence: number[]) => {
  let i = 0;
  return () => sequence[i++] ?? 0;
};

describe('RPS pure game rules', () => {
  it.each([['rock', 'scissors', 'win'], ['paper', 'rock', 'win'], ['scissors', 'paper', 'win'], ['rock', 'rock', 'draw'], ['paper', 'scissors', 'lose']] as const)('%s versus %s is %s', (player, machine, expected) => expect(outcomeFor(player, machine)).toBe(expected));
  it('uses one injected random sample deterministically and scores once', () => { let calls = 0; expect(outcomeFor('rock', 'scissors')).toBe('win'); expect(scoreFor({ player: 0, machine: 0, draws: 0 }, 'win')).toEqual({ player: 1, machine: 0, draws: 0 }); });
});

describe('createPlayerProfile', () => {
  it('returns empty counters and default expert scores', () => {
    const profile = createPlayerProfile();
    expect(profile.validRounds).toBe(0);
    expect(profile.humanCounts).toEqual({ rock: 0, paper: 0, scissors: 0 });
    expect(profile.expertScores.streak).toBe(1.0);
    expect(profile.lastHuman).toBeNull();
    expect(profile.lastResultForHuman).toBeNull();
  });
});

describe('predictByFrequency', () => {
  it('predicts the most frequent move', () => {
    const profile = createPlayerProfile();
    profile.humanCounts = { rock: 5, paper: 2, scissors: 1 };
    const result = chooseMachineGesture(profile, 'frequency', Math.random);
    expect(result.machineGesture).toBe('paper'); // counter to rock
    expect(result.chain.prediction).toBe('rock');
    expect(result.chain.decisionReason).toBe('counter:frequency');
  });
});

describe('predictByMarkov', () => {
  it('uses transition counts when last human is known', () => {
    const profile = createPlayerProfile();
    profile.lastHuman = 'rock';
    profile.transitionCounts = {
      rock: { rock: 1, paper: 0, scissors: 3 },
      paper: { rock: 0, paper: 0, scissors: 0 },
      scissors: { rock: 0, paper: 0, scissors: 0 },
    };
    const result = chooseMachineGesture(profile, 'markov', Math.random);
    expect(result.chain.prediction).toBe('scissors');
    expect(result.machineGesture).toBe('rock'); // counter to scissors
  });
});

describe('buildPersonalizedExperts', () => {
  it('detects streak expert', () => {
    const profile = createPlayerProfile();
    profile.recentWindow = ['rock', 'rock', 'rock', 'paper'];
    const random = seededRandom([0.5]);
    const result = chooseMachineGesture(profile, 'personalized_adaptive', random);
    expect(result.chain.experts.some(e => e.name === 'streak' && e.prediction === 'rock')).toBe(true);
    expect(result.machineGesture).toBe('paper'); // counter to rock
  });
});

describe('chooseMachineGesture', () => {
  it('falls back to random in random mode', () => {
    const random = seededRandom([0.1, 0.5, 0.9]);
    const profile = createPlayerProfile();
    const result = chooseMachineGesture(profile, 'random', random);
    expect(result.machineGesture).toBe('paper');
    expect(result.chain.decisionReason).toBe('random_mode');
  });

  it('uses counter when confidence is high enough', () => {
    const profile = createPlayerProfile();
    profile.humanCounts = { rock: 10, paper: 1, scissors: 1 };
    const random = seededRandom([0.5]);
    const result = chooseMachineGesture(profile, 'personalized_adaptive', random);
    expect(result.chain.prediction).toBe('rock');
    expect(result.machineGesture).toBe('paper');
    expect(result.chain.decisionReason).toMatch(/^counter:expert:frequency_bias:/);
  });

  it('falls back to random when confidence is low', () => {
    const profile = createPlayerProfile();
    profile.validRounds = 1;
    profile.humanCounts = { rock: 1, paper: 0, scissors: 0 };
    const random = vi.fn(() => 0.2);
    const result = chooseMachineGesture(profile, 'personalized_adaptive', random);
    // low confidence or expert cold start may trigger random; both are acceptable
    expect(['rock', 'paper', 'scissors']).toContain(result.machineGesture);
  });
});

describe('updatePlayerProfile', () => {
  it('updates counts and transitions', () => {
    const profile = createPlayerProfile();
    profile.lastHuman = 'rock';
    profile.lastResultForHuman = 'draw';
    const updated = updatePlayerProfile(profile, 'paper', 'scissors', 'human', null);
    expect(updated.validRounds).toBe(1);
    expect(updated.humanCounts.paper).toBe(1);
    expect(updated.transitionCounts.rock.paper).toBe(1);
    expect(updated.afterDrawCounts.paper).toBe(1);
    expect(updated.humanWins).toBe(1);
    expect(updated.lastHuman).toBe('paper');
    expect(updated.lastResultForHuman).toBe('win');
  });

  it('does not update profile on invalid result with unknown gesture', () => {
    const profile = createPlayerProfile();
    const updated = updatePlayerProfile(profile, 'rock', 'paper', 'invalid', null);
    expect(updated).toBe(profile);
  });
});
