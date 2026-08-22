import { machineMove, outcomeFor, scoreFor } from './game';
describe('RPS pure game rules', () => {
  it.each([['rock', 'scissors', 'win'], ['paper', 'rock', 'win'], ['scissors', 'paper', 'win'], ['rock', 'rock', 'draw'], ['paper', 'scissors', 'lose']] as const)('%s versus %s is %s', (player, machine, expected) => expect(outcomeFor(player, machine)).toBe(expected));
  it('uses one injected random sample deterministically and scores once', () => { let calls = 0; expect(machineMove(() => { calls += 1; return .34; })).toBe('paper'); expect(calls).toBe(1); expect(machineMove(() => 0)).toBe('rock'); expect(machineMove(() => .99)).toBe('scissors'); expect(scoreFor({ player: 0, machine: 0, draws: 0 }, 'win')).toEqual({ player: 1, machine: 0, draws: 0 }); });
});
