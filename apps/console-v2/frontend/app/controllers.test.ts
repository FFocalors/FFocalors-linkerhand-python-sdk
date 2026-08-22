import { describe, expect, it } from 'vitest';
import type { JointTargetCommand } from '../shared/contracts';
import { mockRuntime } from '../shared/contracts/mock-runtime';
import { createRpsActionController, createVisionProposalController, O6_RPS_POSES } from './controllers';

describe('application motion controllers', () => {
  it('keeps vision proposals continuous so the actor can latest-win at 20Hz', async () => {
    const commands: Array<{ source: string; finalCommand: boolean; positions: number[] }> = [];
    const runtime = { ...mockRuntime, device: { ...mockRuntime.device, setJointTarget: async (command: JointTargetCommand) => { commands.push(command); } } };
    const controller = createVisionProposalController(runtime, true);
    await controller.submit({ schemaVersion: 1, id: 'vision-1', label: 'open', confidence: .9, positions: [.1, .2], expiresAtMonotonicMs: 100 });
    await controller.submit({ schemaVersion: 1, id: 'vision-2', label: 'open', confidence: .9, positions: [.3, .4], expiresAtMonotonicMs: 150 });
    expect(commands).toHaveLength(2);
    expect(commands.at(-1)).toMatchObject({ source: 'vision', finalCommand: false, positions: [.3, .4] });
  });

  it('uses exactly six normalized O6 vectors for all RPS actions', async () => {
    const commands: Array<{ source: string; positions: number[]; finalCommand: boolean }> = [];
    const runtime = { ...mockRuntime, device: { ...mockRuntime.device, setJointTarget: async (command: JointTargetCommand) => { commands.push(command); } } };
    const controller = createRpsActionController(runtime, await mockRuntime.device.getCapabilities(), true);
    expect(await controller.authorize()).toBe(true);
    for (const move of ['rock', 'paper', 'scissors'] as const) expect((await controller.dispatch({ move, round: 1, reason: 'rps-test' })).status).toBe('executed');
    expect(commands).toHaveLength(3);
    expect(commands.every(command => command.source === 'rockPaperScissors' && command.finalCommand && command.positions.length === 6)).toBe(true);
    expect(commands.map(command => command.positions)).toEqual(Object.values(O6_RPS_POSES).map(values => values.map(value => value / 255)));
  });
});
