import type { TelemetryPort, TelemetrySnapshot } from '../contracts';

export interface VirtualTelemetryPort extends TelemetryPort {
  setPositions(positions: number[]): void;
  getPositions(): number[];
}

const clamp = (value: number) => Math.max(0, Math.min(1, Number.isFinite(value) ? value : 0));

/**
 * A local-only telemetry stream for debug mode. It follows the latest target
 * vector while adding a tiny, deterministic motion so charts remain useful
 * even when no physical device is connected.
 */
export function createVirtualTelemetry(jointCount: number, initialPositions: number[] = []): VirtualTelemetryPort {
  let positions = Array.from({ length: Math.max(0, jointCount) }, (_, index) => clamp(initialPositions[index] ?? 0.5));
  let sequence = 0;
  let phase = 0;
  const listeners = new Set<(snapshot: TelemetrySnapshot) => void>();
  let timer: number | undefined;
  let latestSnapshot: TelemetrySnapshot | undefined;

  const snapshot = (): TelemetrySnapshot => {
    phase += 0.22;
    const animated = positions.map((value, index) => clamp(value + Math.sin(phase + index * 0.7) * 0.012));
    return {
      schemaVersion: 1,
      deviceId: 'virtual-hand',
      sequence: ++sequence,
      monotonicTimeMs: typeof performance !== 'undefined' ? performance.now() : Date.now(),
      positions: animated,
      rawPosition: animated.map(value => Math.round(value * 255)),
      rawCurrent: [],
      rawSpeed: [],
      rawTouch: [],
      connected: true,
    };
  };

  const emit = () => {
    latestSnapshot = snapshot();
    listeners.forEach(listener => listener(latestSnapshot!));
  };

  const startTimer = () => {
    if (timer !== undefined || listeners.size === 0) return;
    timer = window.setInterval(emit, 220);
  };

  const stopTimer = () => {
    if (timer === undefined) return;
    window.clearInterval(timer);
    timer = undefined;
    latestSnapshot = undefined;
  };

  return {
    read: async () => snapshot(),
    subscribe(listener) {
      listeners.add(listener);
      latestSnapshot ??= snapshot();
      listener(latestSnapshot);
      startTimer();
      let subscribed = true;
      return () => {
        if (!subscribed) return;
        subscribed = false;
        listeners.delete(listener);
        if (listeners.size === 0) stopTimer();
      };
    },
    setPositions(next) {
      positions = Array.from({ length: Math.max(0, jointCount) }, (_, index) => clamp(next[index] ?? positions[index] ?? 0.5));
    },
    getPositions() {
      return [...positions];
    },
  };
}
