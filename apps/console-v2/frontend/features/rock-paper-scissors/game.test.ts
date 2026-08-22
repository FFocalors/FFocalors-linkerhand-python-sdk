import { machineMove, outcomeFor, scoreFor } from './game';
describe('RPS pure game rules', () => {
  it.each([['rock', 'scissors', 'win'], ['paper', 'rock', 'win'], ['scissors', 'paper', 'win'], ['rock', 'rock', 'draw'], ['paper', 'scissors', 'lose']] as const)('%s versus %s is %s', (player, machine, expected) => expect(outcomeFor(player, machine)).toBe(expected));
  it('uses injected random deterministically and scores once', () => { expect(machineMove(() => 0)).toBe('rock'); expect(machineMove(() => .34)).toBe('paper'); expect(machineMove(() => .99)).toBe('scissors'); expect(scoreFor({ player: 0, machine: 0, draws: 0 }, 'win')).toEqual({ player: 1, machine: 0, draws: 0 }); });
});

