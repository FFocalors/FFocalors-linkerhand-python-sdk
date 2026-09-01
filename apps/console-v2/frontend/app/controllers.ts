import type { DeviceCapabilities, DeviceConfig, JointTargetCommand, VisionPoseProposal } from '../shared/contracts';
import type { VisionProposalController } from '../features/vision';
import type { RpsActionController, RpsActionRequest, RpsActionResult } from '../features/rock-paper-scissors/types';
import type { ConsolePorts } from '../shared/contracts';
import { tauriRuntimeExtras } from '../shared/contracts/tauri-runtime';

/** Application-owned bridge for feature-local vision proposals. */
export function createVisionProposalController(runtime: ConsolePorts, simulator: boolean): VisionProposalController {
  return {
    async submit(proposal: VisionPoseProposal) {
      const command: JointTargetCommand = {
        schemaVersion: proposal.schemaVersion,
        commandId: proposal.id,
        source: 'vision',
        positions: proposal.positions,
        durationMs: null,
        // Vision is a continuous source. Leaving this non-final lets the
        // Rust motion actor keep the source claimed and apply its 20 Hz
        // latest-wins tick; revoke/camera stop cancels the source explicitly.
        finalCommand: false,
      };
      await runtime.device.setJointTarget(command);
    },
    async revoke(reason: string) {
      if (simulator) return;
      await tauriRuntimeExtras.motionCancelSource('vision', reason);
    },
  };
}

const O6_RPS_POSES: Record<RpsActionRequest['move'], readonly number[]> = {
  rock: [102, 18, 0, 0, 0, 0],
  paper: [250, 250, 250, 250, 250, 250],
  scissors: [92, 87, 255, 255, 0, 0],
};
const O6_RPS_SCISSORS_STAGES: readonly [readonly number[], number][] = [
  [[102, 167, 0, 0, 0, 0], 0],
  [[102, 167, 255, 255, 0, 0], 360],
];
const normalized = (values: readonly number[]) => values.map(value => Math.max(0, Math.min(1, value / 255)));

/** RPS owns one source only; authorization is deliberately per game. */
export function createRpsActionController(runtime: ConsolePorts, capabilities: DeviceCapabilities, simulator: boolean): RpsActionController {
  let authorized = false;
  let sequence = 0;
  let scissorsToken = 0;
  const canAct = capabilities.model === 'O6' && capabilities.supportedOperations.includes('setPosition');
  return {
    async authorize() {
      authorized = canAct;
      return authorized;
    },
    async dispatch(request): Promise<RpsActionResult> {
      if (!authorized || !canAct) return { status: 'error', message: '本局未授权或当前型号不支持猜拳动作' };
      const pose = O6_RPS_POSES[request.move];
      if (!pose || pose.length !== 6) return { status: 'error', message: 'O6 猜拳动作配置无效' };

      if (request.move === 'scissors') {
        const token = ++scissorsToken;
        try {
          await runtime.device.setJointTarget({
            schemaVersion: 1,
            commandId: `rps-${request.round}-${request.move}-thumb-${token}`,
            source: 'rockPaperScissors',
            positions: normalized(O6_RPS_SCISSORS_STAGES[0][0]),
            durationMs: null,
            finalCommand: false,
          });
          await new Promise(resolve => window.setTimeout(resolve, O6_RPS_SCISSORS_STAGES[1][1]));
          if (token !== scissorsToken) return { status: 'cancelled' };
          await runtime.device.setJointTarget({
            schemaVersion: 1,
            commandId: `rps-${request.round}-${request.move}-extend-${token}`,
            source: 'rockPaperScissors',
            positions: normalized(O6_RPS_SCISSORS_STAGES[1][0]),
            durationMs: null,
            finalCommand: true,
          });
          return { status: 'executed' };
        } catch (error) {
          return { status: 'error', message: error instanceof Error ? error.message : '猜拳动作下发失败' };
        }
      }

      const command: JointTargetCommand = {
        schemaVersion: 1,
        commandId: `rps-${request.round}-${request.move}-${++sequence}`,
        source: 'rockPaperScissors',
        positions: normalized(pose),
        durationMs: null,
        finalCommand: true,
      };
      try {
        await runtime.device.setJointTarget(command);
        return { status: 'executed' };
      } catch (error) {
        return { status: 'error', message: error instanceof Error ? error.message : '猜拳动作下发失败' };
      }
    },
    async cancel(reason) {
      // Releasing the motion source after a completed round must NOT revoke the
      // operator's 机械手下发 authorization, otherwise only the first round of
      // a continuous game would ever move the hand. Authorization is dropped
      // explicitly via revoke() (lock/stop/revoke/reset/device-lost).
      scissorsToken += 1;
      if (!simulator) await tauriRuntimeExtras.motionCancelSource('rockPaperScissors', reason);
    },
    async revoke(reason) {
      authorized = false;
      scissorsToken += 1;
      if (!simulator) await tauriRuntimeExtras.motionCancelSource('rockPaperScissors', reason);
    },
    snapshot: () => ({ status: authorized ? 'authorized' : 'idle', detail: authorized ? '本局已授权' : undefined }),
  };
}

export { O6_RPS_POSES, O6_RPS_SCISSORS_STAGES };
