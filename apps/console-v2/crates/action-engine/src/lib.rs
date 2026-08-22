//! Hardware-independent action registry, recording and deterministic playback.
//!
//! The engine deliberately owns no files or threads. The app runtime can
//! persist the returned DTOs and feed commands into its `MotionPort` later.
use console_contracts::{
    ActionRecording, CommandSource, DeviceModel, JointTargetCommand, CURRENT_SCHEMA_VERSION,
};
use thiserror::Error;

pub const MAX_RECORDING_FRAMES: usize = 4096;
pub const DEFAULT_SAMPLE_INTERVAL_MS: u64 = 50;
pub const MAX_INFINITE_LOOPS: u32 = 1000;

#[derive(Clone, Debug, PartialEq)]
pub struct Preset {
    pub id: String,
    pub name: String,
    pub frames: Vec<JointTargetCommand>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum PlaybackState {
    Idle,
    Recording,
    RecordingPaused,
    Playing,
    Paused,
    Completed,
    Cancelled,
}

#[derive(Clone, Debug, Error, PartialEq, Eq)]
pub enum ActionError {
    #[error("action has no frames")]
    Empty,
    #[error("invalid playback state")]
    InvalidState,
    #[error("invalid preset name")]
    InvalidName,
    #[error("preset {model:?} expects {expected} joints but got {actual}")]
    ModelMismatch {
        model: DeviceModel,
        expected: usize,
        actual: usize,
    },
    #[error("joint vector must contain finite normalized values")]
    InvalidVector,
    #[error("recording frame limit ({0}) reached")]
    FrameLimit(usize),
    #[error("sample time moved backwards ({previous} > {actual})")]
    NonMonotonicTime { previous: u64, actual: u64 },
    #[error("playback speed must be between 0.25x and 2x")]
    InvalidSpeed,
}

#[derive(Clone, Debug)]
struct PlaybackSession {
    recording: ActionRecording,
    frame: usize,
    loops_done: u32,
    loop_enabled: bool,
    loop_count: Option<u32>,
    speed: f32,
    next_due_ms: u64,
}

pub struct ActionEngine {
    recording: Option<ActionRecording>,
    recording_times: Vec<u64>,
    recording_paused: bool,
    state: PlaybackState,
    playback: Option<PlaybackSession>,
    presets: Vec<Preset>,
    joint_count: Option<usize>,
    model: Option<DeviceModel>,
    loop_enabled: bool,
    loop_count: Option<u32>,
    loops_done: u32,
    next_sample_ms: u64,
}

impl Default for ActionEngine {
    fn default() -> Self {
        Self::new()
    }
}

impl ActionEngine {
    pub fn new() -> Self {
        Self {
            recording: None,
            recording_times: Vec::new(),
            recording_paused: false,
            state: PlaybackState::Idle,
            playback: None,
            presets: Vec::new(),
            joint_count: None,
            model: None,
            loop_enabled: false,
            loop_count: None,
            loops_done: 0,
            next_sample_ms: 0,
        }
    }
    pub fn for_model(model: DeviceModel, joint_count: usize) -> Result<Self, ActionError> {
        let expected = model_joint_count(&model);
        if expected != joint_count {
            return Err(ActionError::ModelMismatch {
                model,
                expected,
                actual: joint_count,
            });
        }
        let mut engine = Self::new();
        engine.model = Some(model);
        engine.joint_count = Some(joint_count);
        Ok(engine)
    }
    pub fn configure_model(
        &mut self,
        model: DeviceModel,
        joint_count: usize,
    ) -> Result<(), ActionError> {
        let expected = model_joint_count(&model);
        if expected != joint_count {
            return Err(ActionError::ModelMismatch {
                model,
                expected,
                actual: joint_count,
            });
        }
        self.model = Some(model);
        self.joint_count = Some(joint_count);
        Ok(())
    }
    pub fn register_preset(&mut self, preset: Preset) -> Result<(), ActionError> {
        validate_name(&preset.name)?;
        if preset.frames.is_empty() {
            return Err(ActionError::Empty);
        }
        let joint_count = self.joint_count.unwrap_or(preset.frames[0].positions.len());
        for frame in &preset.frames {
            validate_vector(&frame.positions, joint_count)?;
        }
        if let Some(existing) = self.presets.iter_mut().find(|p| p.id == preset.id) {
            *existing = preset;
        } else {
            self.presets.push(preset);
        }
        Ok(())
    }
    /// Installs a conservative built-in neutral pose for a configured model.
    /// Built-ins use the same registry and validation path as custom actions.
    pub fn install_builtin_presets(
        &mut self,
        model: DeviceModel,
        joint_count: usize,
    ) -> Result<(), ActionError> {
        let expected = model_joint_count(&model);
        if expected != joint_count {
            return Err(ActionError::ModelMismatch {
                model,
                expected,
                actual: joint_count,
            });
        }
        self.model = Some(model);
        self.joint_count = Some(joint_count);
        self.register_preset(Preset {
            id: "builtin:neutral".into(),
            name: "中性姿态".into(),
            frames: vec![JointTargetCommand {
                schema_version: CURRENT_SCHEMA_VERSION,
                command_id: "builtin:neutral:0".into(),
                source: CommandSource::Preset,
                positions: vec![0.5; joint_count],
                duration_ms: Some(DEFAULT_SAMPLE_INTERVAL_MS),
                final_command: true,
            }],
        })
    }
    pub fn register_custom_preset(&mut self, preset: Preset) -> Result<(), ActionError> {
        self.register_preset(preset)
    }
    pub fn register_preset_for(
        &mut self,
        preset: Preset,
        model: DeviceModel,
    ) -> Result<(), ActionError> {
        let joint_count = model_joint_count(&model);
        validate_name(&preset.name)?;
        if preset.frames.is_empty() {
            return Err(ActionError::Empty);
        }
        if preset
            .frames
            .iter()
            .any(|frame| frame.positions.len() != joint_count)
        {
            return Err(ActionError::ModelMismatch {
                model,
                expected: joint_count,
                actual: preset
                    .frames
                    .first()
                    .map_or(0, |frame| frame.positions.len()),
            });
        }
        for frame in &preset.frames {
            validate_vector(&frame.positions, joint_count)?;
        }
        if let Some(existing) = self.presets.iter_mut().find(|p| p.id == preset.id) {
            *existing = preset;
        } else {
            self.presets.push(preset);
        }
        Ok(())
    }
    pub fn list_presets(&self) -> &[Preset] {
        self.presets()
    }
    pub fn unregister_preset(&mut self, id: &str) -> bool {
        let before = self.presets.len();
        self.presets.retain(|preset| preset.id != id);
        before != self.presets.len()
    }
    pub fn presets(&self) -> &[Preset] {
        &self.presets
    }

    pub fn start_recording(&mut self, id: impl Into<String>, name: impl Into<String>) {
        self.start_recording_at(id, name, 0);
    }
    pub fn start_recording_at(
        &mut self,
        id: impl Into<String>,
        name: impl Into<String>,
        now_ms: u64,
    ) {
        self.recording = Some(ActionRecording {
            schema_version: CURRENT_SCHEMA_VERSION,
            id: id.into(),
            name: name.into(),
            frames: Vec::with_capacity(64),
            duration_ms: 0,
            steps: 0,
            updated_at: String::new(),
        });
        self.recording_times.clear();
        self.recording_paused = false;
        self.next_sample_ms = now_ms;
        self.state = PlaybackState::Recording;
    }
    pub fn pause_recording(&mut self) -> Result<(), ActionError> {
        if self.state != PlaybackState::Recording {
            return Err(ActionError::InvalidState);
        }
        self.recording_paused = true;
        self.state = PlaybackState::RecordingPaused;
        Ok(())
    }
    pub fn resume_recording(&mut self) -> Result<(), ActionError> {
        if self.state != PlaybackState::RecordingPaused {
            return Err(ActionError::InvalidState);
        }
        self.recording_paused = false;
        self.state = PlaybackState::Recording;
        Ok(())
    }
    pub fn cancel_recording(&mut self) -> Result<(), ActionError> {
        if !matches!(
            self.state,
            PlaybackState::Recording | PlaybackState::RecordingPaused
        ) {
            return Err(ActionError::InvalidState);
        }
        self.recording = None;
        self.recording_times.clear();
        self.state = PlaybackState::Cancelled;
        Ok(())
    }
    /// Record at a monotonic fake-clock time. Samples inside the interval merge
    /// into the latest frame, keeping memory bounded and deterministic.
    pub fn record_at(&mut self, now_ms: u64, frame: JointTargetCommand) -> Result<(), ActionError> {
        if !matches!(
            self.state,
            PlaybackState::Recording | PlaybackState::RecordingPaused
        ) || self.recording_paused
        {
            return Err(ActionError::InvalidState);
        }
        let joint_count = self.joint_count.unwrap_or(frame.positions.len());
        validate_vector(&frame.positions, joint_count)?;
        if let Some(previous) = self.recording_times.last().copied() {
            if now_ms < previous {
                return Err(ActionError::NonMonotonicTime {
                    previous,
                    actual: now_ms,
                });
            }
            if now_ms.saturating_sub(previous) < DEFAULT_SAMPLE_INTERVAL_MS {
                let recording = self.recording.as_mut().ok_or(ActionError::InvalidState)?;
                if let Some(last) = recording.frames.last_mut() {
                    *last = frame;
                }
                return Ok(());
            }
        }
        let recording = self.recording.as_mut().ok_or(ActionError::InvalidState)?;
        if recording.frames.len() >= MAX_RECORDING_FRAMES {
            return Err(ActionError::FrameLimit(MAX_RECORDING_FRAMES));
        }
        recording.frames.push(frame);
        self.recording_times.push(now_ms);
        self.next_sample_ms = now_ms.saturating_add(DEFAULT_SAMPLE_INTERVAL_MS);
        Ok(())
    }
    pub fn record(&mut self, frame: JointTargetCommand) -> Result<(), ActionError> {
        let now = self
            .recording_times
            .last()
            .copied()
            .map_or(self.next_sample_ms, |last| {
                last.saturating_add(DEFAULT_SAMPLE_INTERVAL_MS)
            });
        self.record_at(now, frame)
    }
    pub fn finish_recording(&mut self) -> Result<ActionRecording, ActionError> {
        if !matches!(
            self.state,
            PlaybackState::Recording | PlaybackState::RecordingPaused
        ) {
            return Err(ActionError::InvalidState);
        }
        let mut recording = self.recording.take().ok_or(ActionError::InvalidState)?;
        if recording.frames.is_empty() {
            self.state = PlaybackState::Cancelled;
            return Err(ActionError::Empty);
        }
        recording.steps = recording.frames.len() as u32;
        recording.duration_ms = self
            .recording_times
            .last()
            .copied()
            .unwrap_or(0)
            .saturating_sub(self.recording_times.first().copied().unwrap_or(0));
        self.recording_times.clear();
        self.state = PlaybackState::Idle;
        Ok(recording)
    }

    pub fn play(&mut self, recording: ActionRecording) -> Result<(), ActionError> {
        self.play_at(recording, 0)
    }
    pub fn play_at(&mut self, recording: ActionRecording, now_ms: u64) -> Result<(), ActionError> {
        self.validate_recording(&recording)?;
        self.recording = Some(recording.clone());
        self.playback = Some(PlaybackSession {
            recording,
            frame: 0,
            loops_done: 0,
            loop_enabled: self.loop_enabled,
            loop_count: self.loop_count,
            speed: 1.0,
            next_due_ms: now_ms,
        });
        self.loops_done = 0;
        self.state = PlaybackState::Playing;
        Ok(())
    }
    pub fn set_speed(&mut self, speed: f32) -> Result<(), ActionError> {
        if !(0.25..=2.0).contains(&speed) || !speed.is_finite() {
            return Err(ActionError::InvalidSpeed);
        }
        if let Some(playback) = self.playback.as_mut() {
            playback.speed = speed;
        }
        Ok(())
    }
    pub fn speed(&self) -> f32 {
        self.playback.as_ref().map_or(1.0, |p| p.speed)
    }
    pub fn pause(&mut self) -> Result<(), ActionError> {
        if self.state != PlaybackState::Playing {
            return Err(ActionError::InvalidState);
        }
        self.state = PlaybackState::Paused;
        Ok(())
    }
    pub fn pause_playback(&mut self) -> Result<(), ActionError> {
        self.pause()
    }
    pub fn resume(&mut self) -> Result<(), ActionError> {
        if self.state != PlaybackState::Paused {
            return Err(ActionError::InvalidState);
        }
        self.state = PlaybackState::Playing;
        Ok(())
    }
    pub fn resume_playback(&mut self) -> Result<(), ActionError> {
        self.resume()
    }
    pub fn set_loop(&mut self, enabled: bool, count: Option<u32>) {
        self.loop_enabled = enabled;
        self.loop_count = count;
        if let Some(playback) = self.playback.as_mut() {
            playback.loop_enabled = enabled;
            playback.loop_count = count;
        }
    }
    /// Deterministic fake-clock tick; emits no more than one complete command.
    pub fn tick(&mut self, now_ms: u64) -> Option<JointTargetCommand> {
        if self.state != PlaybackState::Playing {
            return None;
        }
        let playback = self.playback.as_mut()?;
        if now_ms < playback.next_due_ms {
            return None;
        }
        if playback.frame >= playback.recording.frames.len() {
            let can_loop = playback.loop_enabled
                && playback
                    .loop_count
                    .is_none_or(|count| playback.loops_done < count)
                && playback.loops_done < MAX_INFINITE_LOOPS;
            if can_loop {
                playback.frame = 0;
                playback.loops_done += 1;
                self.loops_done = playback.loops_done;
            } else {
                self.state = PlaybackState::Completed;
                return None;
            }
        }
        let last = playback.frame + 1 == playback.recording.frames.len();
        let mut command = playback.recording.frames[playback.frame].clone();
        command.source = if playback.loops_done > 0 {
            CommandSource::Loop
        } else {
            CommandSource::Playback
        };
        command.final_command = last
            && (!playback.loop_enabled
                || playback
                    .loop_count
                    .is_some_and(|count| playback.loops_done >= count));
        let delay = command
            .duration_ms
            .unwrap_or(DEFAULT_SAMPLE_INTERVAL_MS)
            .max(1);
        playback.next_due_ms =
            now_ms.saturating_add((delay as f32 / playback.speed).round() as u64);
        playback.frame += 1;
        Some(command)
    }
    #[allow(clippy::should_implement_trait)]
    pub fn next(&mut self) -> Option<JointTargetCommand> {
        let now = self.playback.as_ref().map_or(0, |p| p.next_due_ms);
        self.tick(now)
    }
    pub fn stop_all(&mut self) {
        self.cancel();
    }
    pub fn cancel(&mut self) {
        self.recording = None;
        self.recording_times.clear();
        self.playback = None;
        self.state = PlaybackState::Cancelled;
        self.loops_done = 0;
    }
    pub fn state(&self) -> &PlaybackState {
        &self.state
    }
    pub fn loop_count(&self) -> u32 {
        self.loops_done
    }
    pub fn list(&self) -> Vec<ActionRecording> {
        self.presets
            .iter()
            .map(preset_recording)
            .chain(self.recording.clone())
            .collect()
    }
    fn validate_recording(&self, recording: &ActionRecording) -> Result<(), ActionError> {
        if recording.frames.is_empty() {
            return Err(ActionError::Empty);
        }
        let joint_count = self
            .joint_count
            .unwrap_or(recording.frames[0].positions.len());
        for frame in &recording.frames {
            validate_vector(&frame.positions, joint_count)?;
        }
        Ok(())
    }
}

fn validate_name(name: &str) -> Result<(), ActionError> {
    if name.trim().is_empty() {
        Err(ActionError::InvalidName)
    } else {
        Ok(())
    }
}
fn validate_vector(values: &[f64], joint_count: usize) -> Result<(), ActionError> {
    if values.len() != joint_count
        || values
            .iter()
            .any(|value| !value.is_finite() || !(0.0..=1.0).contains(value))
    {
        Err(ActionError::InvalidVector)
    } else {
        Ok(())
    }
}
fn model_joint_count(model: &DeviceModel) -> usize {
    match model {
        DeviceModel::O6 | DeviceModel::L6 => 6,
        DeviceModel::L7 => 7,
        DeviceModel::L10 => 10,
        DeviceModel::L20 | DeviceModel::G20 => 20,
        DeviceModel::L21 | DeviceModel::L25 => 25,
    }
}
fn preset_recording(preset: &Preset) -> ActionRecording {
    ActionRecording {
        schema_version: CURRENT_SCHEMA_VERSION,
        id: preset.id.clone(),
        name: preset.name.clone(),
        frames: preset.frames.clone(),
        duration_ms: preset
            .frames
            .iter()
            .map(|f| f.duration_ms.unwrap_or(DEFAULT_SAMPLE_INTERVAL_MS))
            .sum(),
        steps: preset.frames.len() as u32,
        updated_at: String::new(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn f(i: u64) -> JointTargetCommand {
        JointTargetCommand {
            schema_version: 1,
            command_id: i.to_string(),
            source: CommandSource::Playback,
            positions: vec![i as f64 / 10.0],
            duration_ms: Some(50),
            final_command: false,
        }
    }
    #[test]
    fn record_play_loop_is_deterministic() {
        let mut a = ActionEngine::new();
        a.start_recording("a", "A");
        a.record(f(1)).unwrap();
        a.record(f(2)).unwrap();
        let r = a.finish_recording().unwrap();
        a.play(r).unwrap();
        a.set_loop(true, Some(1));
        assert_eq!(a.next().unwrap().command_id, "1");
        assert_eq!(a.next().unwrap().command_id, "2");
        assert_eq!(a.next().unwrap().command_id, "1");
        assert_eq!(a.next().unwrap().command_id, "2");
        assert!(a.next().is_none());
        assert_eq!(a.loop_count(), 1);
    }
    #[test]
    fn timestamp_merge_and_vector_validation() {
        let mut a = ActionEngine::for_model(DeviceModel::O6, 6).unwrap();
        a.start_recording_at("a", "A", 10);
        let mut command = f(1);
        command.positions = vec![0.5; 6];
        a.record_at(10, command.clone()).unwrap();
        a.record_at(20, command).unwrap();
        assert_eq!(a.finish_recording().unwrap().steps, 1);
        assert!(a.set_speed(2.1).is_err());
    }
    #[test]
    fn final_command_releases_playback_source() {
        let mut a = ActionEngine::new();
        let r = ActionRecording {
            schema_version: 1,
            id: "x".into(),
            name: "X".into(),
            frames: vec![f(1)],
            duration_ms: 50,
            steps: 1,
            updated_at: String::new(),
        };
        a.play_at(r, 100).unwrap();
        let out = a.tick(100).unwrap();
        assert!(out.final_command);
        assert_eq!(out.source, CommandSource::Playback);
        assert!(a.tick(150).is_none());
    }
}
