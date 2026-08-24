import type { ConsolePorts, DeviceCapabilities, DeviceConfig, StructuredLogEntry, TelemetrySnapshot } from './index';

const config: DeviceConfig = { schemaVersion: 1, deviceId: 'lh-o6-001', name: '演示机械手 O6', model: 'O6', hand: 'left', transport: { type: 'can', channel: 'fake' }, autoReconnect: true };
const lengths = (n: number) => ({ length: n, available: true, range: { min: 0, max: 255 } });
const capabilities: DeviceCapabilities = { schemaVersion: 1, deviceId: config.deviceId, model: config.model, hand: config.hand, transport: config.transport, jointCount: 6, position: lengths(6), speed: lengths(6), current: lengths(6), torque: lengths(6), touch: lengths(6), speedCommandLength: 6, currentCommandLength: null, torqueCommandLength: 6, supportedOperations: ['connect', 'disconnect', 'capabilities', 'getTelemetry', 'getPosition', 'getCurrent', 'getSpeed', 'getTouch', 'setPosition', 'setSpeed', 'setTorque', 'stop', 'unlock', 'close'] };
const logs: StructuredLogEntry[] = [{ schemaVersion: 1, id: '1', monotonicTimeMs: 1, level: 'info', event: 'info', message: '运行在浏览器模拟器模式，未连接物理机械手', fields: { source: 'runtime' } }];
let locked = false;
const telemetry: TelemetrySnapshot = { schemaVersion: 1, deviceId: config.deviceId, sequence: 0, monotonicTimeMs: 0, positions: [.55, .47, .63, .52, .58, .5], rawPosition: [140, 120, 161, 133, 148, 128], rawCurrent: [62, 62, 62, 62, 62, 62], rawSpeed: [100, 100, 100, 100, 100, 100], rawTouch: [0, 0, 0, 0, 0, 0], connected: true };
const snapshot = (): TelemetrySnapshot => { telemetry.sequence += 1; telemetry.monotonicTimeMs = Date.now(); return { ...telemetry, positions: [...telemetry.positions], rawPosition: [...telemetry.rawPosition], rawCurrent: [...telemetry.rawCurrent], rawSpeed: [...telemetry.rawSpeed], rawTouch: [...telemetry.rawTouch] }; };

export const mockRuntime: ConsolePorts = {
  device: {
    async getConfig() { return config; }, async getCapabilities() { return capabilities; }, async getConnection() { return { schemaVersion: 1, deviceId: config.deviceId, state: 'connected', attempt: 1, lastError: null }; },
    async setJointTarget(command) { if (locked) return; telemetry.positions = [...command.positions]; telemetry.rawPosition = command.positions.map(v => Math.round(v * 255)); logs.unshift({ schemaVersion: 1, id: String(Date.now()), monotonicTimeMs: Date.now(), level: 'info', event: 'position.updated', message: '关节目标已更新', fields: { source: command.source } }); },
    async stopAll() { locked = true; logs.unshift({ schemaVersion: 1, id: String(Date.now()), monotonicTimeMs: Date.now(), level: 'warn', event: 'motion.stopped', message: '全部动作已停止，控制已锁定', fields: {} }); }, async unlock() { locked = false; logs.unshift({ schemaVersion: 1, id: String(Date.now()), monotonicTimeMs: Date.now(), level: 'info', event: 'motion.unlocked', message: '控制已恢复', fields: {} }); }
  },
  motion: { async getOperation() { return { schemaVersion: 1, operationId: 'motion', kind: 'motion', state: locked ? 'locked' : 'idle', progress: 0, detail: null }; }, async runAction() {}, async pause() {} },
  telemetry: { async read() { return snapshot(); }, subscribe(listener) { const id = window.setInterval(() => listener(snapshot()), 400); return () => window.clearInterval(id); } },
  actions: { async list() { return []; }, async delete() {} },
  grasp: { async listPresets() { return [{ id: 'soft', name: '柔软物体', description: '低力度包络抓取' }, { id: 'cube', name: '方形物体', description: '稳定的平行夹持' }, { id: 'precision', name: '精细拾取', description: '指尖精确定位' }]; }, async runPreset() {} },
  vision: { async propose() { return [{ schemaVersion: 1, id: 'pose-1', label: '拿起蓝色杯子', confidence: .94, positions: [.56, .45, .66, .5, .58, .5] }, { schemaVersion: 1, id: 'pose-2', label: '向前伸手', confidence: .81, positions: [.51, .48, .58, .52, .5, .5] }]; }, async sync() {} },
  logs: {
    async list(limit = 20) { return logs.slice(0, limit); },
    async record(entry) {
      const now = Date.now();
      logs.unshift({ schemaVersion: 1, id: String(now), monotonicTimeMs: now, ...entry });
    },
  }
};
