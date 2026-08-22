//! Fixed-capacity telemetry buffers. High-rate frames never share the status stream.
use console_contracts::TelemetrySnapshot;
use std::collections::VecDeque;

/// Rendering visibility used by high-rate consumers. Hidden tabs stop sampling;
/// low-visibility surfaces use a slower cadence to preserve battery/CPU.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum Visibility {
    #[default]
    Visible,
    LowVisibility,
    Hidden,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct SamplerConfig {
    pub visible_interval_ms: u64,
    pub low_visibility_interval_ms: u64,
}

impl Default for SamplerConfig {
    fn default() -> Self {
        Self {
            visible_interval_ms: 16,
            low_visibility_interval_ms: 250,
        }
    }
}

/// Pure timing policy; callers decide how to schedule the actual callback.
#[derive(Clone, Debug)]
pub struct VisibilityAwareSampler {
    config: SamplerConfig,
    visibility: Visibility,
    last_sample_ms: Option<u64>,
}

impl VisibilityAwareSampler {
    pub fn new(config: SamplerConfig) -> Self {
        Self {
            config,
            visibility: Visibility::Visible,
            last_sample_ms: None,
        }
    }
    pub fn set_visibility(&mut self, visibility: Visibility) {
        self.visibility = visibility;
    }
    pub fn visibility(&self) -> Visibility {
        self.visibility
    }
    pub fn reset(&mut self) {
        self.last_sample_ms = None;
    }
    pub fn should_sample(&mut self, now_ms: u64) -> bool {
        if self.visibility == Visibility::Hidden {
            return false;
        }
        let interval = match self.visibility {
            Visibility::Visible => self.config.visible_interval_ms,
            Visibility::LowVisibility => self.config.low_visibility_interval_ms,
            Visibility::Hidden => return false,
        };
        let due = self
            .last_sample_ms
            .is_none_or(|last| now_ms.saturating_sub(last) >= interval);
        if due {
            self.last_sample_ms = Some(now_ms);
        }
        due
    }
}

/// A bounded view over a telemetry stream. It never allocates beyond capacity.
#[derive(Clone, Debug)]
pub struct BoundedTelemetryWindow {
    values: VecDeque<TelemetrySnapshot>,
    capacity: usize,
}

impl BoundedTelemetryWindow {
    pub fn new(capacity: usize) -> Self {
        assert!(capacity > 0);
        Self {
            values: VecDeque::with_capacity(capacity),
            capacity,
        }
    }
    pub fn push(&mut self, value: TelemetrySnapshot) {
        if self.values.len() == self.capacity {
            self.values.pop_front();
        }
        self.values.push_back(value);
    }
    pub fn clear(&mut self) {
        self.values.clear();
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
    pub fn iter(&self) -> impl Iterator<Item = &TelemetrySnapshot> {
        self.values.iter()
    }
    /// Returns at most `limit` evenly spaced points, preserving chronological order.
    pub fn sampled(&self, limit: usize) -> Vec<&TelemetrySnapshot> {
        if limit == 0 || self.values.is_empty() {
            return Vec::new();
        }
        if limit == 1 {
            return vec![self.values.back().expect("non-empty")];
        }
        if self.values.len() <= limit {
            return self.values.iter().collect();
        }
        let last = self.values.len() - 1;
        (0..limit)
            .map(|i| &self.values[i * last / (limit - 1)])
            .collect()
    }
}

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
    pub fn latest(&self) -> Option<&TelemetrySnapshot> {
        self.status.iter().last()
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
            monotonic_time_ms: i,
            positions: vec![],
            raw_position: vec![],
            raw_current: vec![],
            raw_speed: vec![],
            raw_touch: vec![],
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

    #[test]
    fn visibility_sampler_stops_hidden_and_slows_low_visibility() {
        let mut sampler = VisibilityAwareSampler::new(SamplerConfig {
            visible_interval_ms: 10,
            low_visibility_interval_ms: 100,
        });
        assert!(sampler.should_sample(0));
        assert!(!sampler.should_sample(9));
        assert!(sampler.should_sample(10));
        sampler.set_visibility(Visibility::Hidden);
        assert!(!sampler.should_sample(1_000));
        sampler.set_visibility(Visibility::LowVisibility);
        assert!(!sampler.should_sample(105));
        assert!(sampler.should_sample(110));
    }

    #[test]
    fn sampled_window_has_fixed_point_limit() {
        let mut window = BoundedTelemetryWindow::new(5);
        for i in 0..20 {
            window.push(t(i));
        }
        assert_eq!(window.len(), 5);
        assert_eq!(window.sampled(3).len(), 3);
        assert_eq!(window.sampled(3).first().unwrap().sequence, 15);
        assert_eq!(window.sampled(3).last().unwrap().sequence, 19);
    }
}
