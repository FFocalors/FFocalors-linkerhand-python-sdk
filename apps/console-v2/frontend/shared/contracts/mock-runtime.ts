import type { ConsolePorts, DeviceCapabilities, DeviceConfig, TelemetrySnapshot, StructuredLogEntry } from './index';

const config: DeviceConfig = { id: 'lh-o6-001', name: '演示机械手 O6', model: 'O6', address: '192.168.1.42' };
const capabilities: DeviceCapabilities = { model: 'O6', jointCount: 6, visionSync: true, tactile: true };
const logs: StructuredLogEntry[] = [{ id: '1', time: '刚刚', level: 'info', message: '已连接到演示机械手', source: 'runtime' }, { id: '2', time: '1 分钟前', level: 'info', message: '工作区已准备就绪', source: 'workspace' }];
let locked = false;
const telemetry: TelemetrySnapshot = { timestamp: Date.now(), joints: { J1: 12, J2: -8, J3: 34, J4: 5, J5: 18, J6: 0 }, currentMa: 620, temperatureC: 31.4 };

export const mockRuntime: ConsolePorts = {
  device: { async getConfig() { return config; }, async getCapabilities() { return capabilities; }, async getConnection() { return { state: 'connected', latencyMs: 12, lastSeen: '刚刚' }; }, async setJointTarget(command) { telemetry.joints[command.joint] = command.value; logs.unshift({ id: String(Date.now()), time: '刚刚', level: 'info', message: `${command.joint} 已更新为 ${command.value}°`, source: 'device' }); }, async stopAll() { locked = true; logs.unshift({ id: String(Date.now()), time: '刚刚', level: 'warn', message: '全部动作已停止，控制已锁定', source: 'safety' }); }, async unlock() { locked = false; logs.unshift({ id: String(Date.now()), time: '刚刚', level: 'info', message: '控制已恢复', source: 'safety' }); } },
  motion: { async getOperation() { return { state: locked ? 'locked' : 'idle', label: locked ? '等待恢复' : '就绪', progress: 0 }; }, async runAction() {}, async pause() {} },
  telemetry: { async read() { return { ...telemetry, timestamp: Date.now(), joints: { ...telemetry.joints } }; }, subscribe(listener) { const id = window.setInterval(() => void this.read().then(listener), 1800); return () => window.clearInterval(id); } },
  actions: { async list() { return [{ id: 'home', name: '回到安全位', durationMs: 3500, steps: 6, updatedAt: '今天 14:20' }, { id: 'wave', name: '挥手示意', durationMs: 4200, steps: 9, updatedAt: '昨天 09:12' }, { id: 'pick', name: '轻拿轻放', durationMs: 6800, steps: 14, updatedAt: '周一 16:40' }]; }, async delete() {} },
  grasp: { async listPresets() { return [{ id: 'soft', name: '柔软物体', description: '低力度包络抓取' }, { id: 'cube', name: '方形物体', description: '稳定的平行夹持' }, { id: 'precision', name: '精细拾取', description: '指尖精确定位' }]; }, async runPreset() {} },
  vision: { async propose() { return [{ id: 'pose-1', label: '拿起蓝色杯子', confidence: .94, joints: { J1: 16, J2: -14, J3: 42 } }, { id: 'pose-2', label: '向前伸手', confidence: .81, joints: { J1: 3, J2: -4, J3: 20 } }]; }, async sync() {} },
  logs: { async list(limit = 20) { return logs.slice(0, limit); } }
};
