import { describe, expect, it } from 'vitest';
import type { JointTargetCommand } from '../shared/contracts';
import { mockRuntime } from '../shared/contracts/mock-runtime';
import { createRpsActionController, createVisionProposalController, O6_RPS_POSES, O6_RPS_SCISSORS_STAGES } from './controllers';

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
    expect(commands).toHaveLength(4);
    const expected = [
      ...Object.values(O6_RPS_POSES).slice(0, 2).map(values => values.map(value => value / 255)),
      O6_RPS_SCISSORS_STAGES[0][0].map(value => value / 255),
      O6_RPS_SCISSORS_STAGES[1][0].map(value => value / 255),
    ];
    expect(commands.map(command => command.positions)).toEqual(expected);
  });

  it('keeps RPS hardware authorization across a completed round and only revokes explicitly', async () => {
    const commands: Array<{ source: string; positions: number[]; finalCommand: boolean }> = [];
    const runtime = { ...mockRuntime, device: { ...mockRuntime.device, setJointTarget: async (command: JointTargetCommand) => { commands.push(command); } } };
    const controller = createRpsActionController(runtime, await mockRuntime.device.getCapabilities(), true);
    expect(await controller.authorize()).toBe(true);
    // round 1 executes
    expect((await controller.dispatch({ move: 'rock', round: 1, reason: 'rps-reveal' })).status).toBe('executed');
    // completing a round calls cancel() to release the motion source — this must
    // NOT revoke the operator's 机械手下发 authorization (regression: only the
    // first round used to execute because cancel() dropped authorized)
    await controller.cancel('stopped');
    expect((await controller.dispatch({ move: 'paper', round: 2, reason: 'rps-reveal' })).status).toBe('executed');
    // an explicit revoke does drop the authorization
    await controller.revoke?.('stopped');
    const after = await controller.dispatch({ move: 'scissors', round: 3, reason: 'rps-reveal' });
    expect(after.status).toBe('error');
    expect(commands.length).toBe(2);
  });
});
