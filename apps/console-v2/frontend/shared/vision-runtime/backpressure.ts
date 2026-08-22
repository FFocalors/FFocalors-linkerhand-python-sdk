/** A one-slot gate: a new frame is dropped while the worker owns the slot. */
export class SingleFrameGate {
  private occupied = false;
  private dropped = 0;
  tryAcquire(): boolean { if (this.occupied) { this.dropped += 1; return false; } this.occupied = true; return true; }
  release(): void { this.occupied = false; }
  reset(): void { this.occupied = false; this.dropped = 0; }
  get inFlight(): 0 | 1 { return this.occupied ? 1 : 0; }
  get droppedFrames(): number { return this.dropped; }
}
