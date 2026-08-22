//! Fixed-capacity telemetry buffers. High-rate frames never share the status stream.
use console_contracts::TelemetrySnapshot;
use std::collections::VecDeque;

#[derive(Clone, Debug)]
pub struct RingBuffer<T> {
    capacity: usize,
    values: VecDeque<T>,
    dropped: u64,
}
impl<T> RingBuffer<T> {
    pub fn new(capacity: usize) -> Self {
        assert!(capacity > 0);
        Self {
            capacity,
            values: VecDeque::with_capacity(capacity),
            dropped: 0,
        }
    }
    pub fn push(&mut self, value: T) {
        if self.values.len() == self.capacity {
            self.values.pop_front();
            self.dropped += 1;
        }
        self.values.push_back(value);
    }
    pub fn len(&self) -> usize {
        self.values.len()
    }
    pub fn is_empty(&self) -> bool {
        self.values.is_empty()
    }
    pub fn capacity(&self) -> usize {
        self.capacity
    }
    pub fn dropped(&self) -> u64 {
        self.dropped
    }
    pub fn iter(&self) -> impl Iterator<Item = &T> {
        self.values.iter()
    }
    pub fn drain(&mut self) -> Vec<T> {
        self.values.drain(..).collect()
    }
}

#[derive(Clone, Debug)]
pub struct TelemetryStore {
    status: RingBuffer<TelemetrySnapshot>,
    frames: RingBuffer<TelemetrySnapshot>,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TelemetrySubscription {
    pub every_n_frames: usize,
}
impl TelemetrySubscription {
    pub fn new(every_n_frames: usize) -> Self {
        Self {
            every_n_frames: every_n_frames.max(1),
        }
    }
}
impl TelemetryStore {
    pub fn new(status_capacity: usize, frame_capacity: usize) -> Self {
        Self {
            status: RingBuffer::new(status_capacity),
            frames: RingBuffer::new(frame_capacity),
        }
    }
    pub fn publish_status(&mut self, value: TelemetrySnapshot) {
        self.status.push(value);
    }
    pub fn publish_frame(&mut self, value: TelemetrySnapshot) {
        self.frames.push(value);
    }
    pub fn status(&self) -> &RingBuffer<TelemetrySnapshot> {
        &self.status
    }
    pub fn frames(&self) -> &RingBuffer<TelemetrySnapshot> {
        &self.frames
    }
    pub fn sample_frames(&self, every_n: usize) -> Vec<&TelemetrySnapshot> {
        let n = every_n.max(1);
        self.frames
            .iter()
            .enumerate()
            .filter_map(|(i, v)| (i % n == 0).then_some(v))
            .collect()
    }
    pub fn subscribe_frames(
        &self,
        subscription: &TelemetrySubscription,
    ) -> Vec<&TelemetrySnapshot> {
        self.sample_frames(subscription.every_n_frames)
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    fn t(i: u64) -> TelemetrySnapshot {
        TelemetrySnapshot {
            schema_version: 1,
            device_id: "d".into(),
            sequence: i,
            monotonic_ms: i,
            joints: vec![],
            forces: vec![],
            connected: true,
        }
    }
    #[test]
    fn bounded_and_dropped() {
        let mut b = RingBuffer::new(2);
        b.push(1);
        b.push(2);
        b.push(3);
        assert_eq!(b.len(), 2);
        assert_eq!(b.dropped(), 1);
        assert_eq!(b.iter().copied().collect::<Vec<_>>(), vec![2, 3]);
    }
    #[test]
    fn streams_are_separate() {
        let mut s = TelemetryStore::new(1, 3);
        s.publish_status(t(0));
        for i in 1..5 {
            s.publish_frame(t(i));
        }
        assert_eq!(s.status().len(), 1);
        assert_eq!(s.frames().len(), 3);
        assert_eq!(s.sample_frames(2).len(), 2);
    }
}
