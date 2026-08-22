//! Pure action preset, recording, playback and loop state machines.
use console_contracts::{ActionRecording, JointTargetCommand};
use thiserror::Error;
#[derive(Clone, Debug, PartialEq)]
pub struct Preset {
    pub id: String,
    pub name: String,
    pub frames: Vec<JointTargetCommand>,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum PlaybackState {
    Idle,
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
}
pub struct ActionEngine {
    recording: Option<ActionRecording>,
    state: PlaybackState,
    frame: usize,
    loop_enabled: bool,
    loop_count: Option<u32>,
    loops_done: u32,
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
            state: PlaybackState::Idle,
            frame: 0,
            loop_enabled: false,
            loop_count: None,
            loops_done: 0,
        }
    }
    pub fn start_recording(&mut self, id: impl Into<String>, name: impl Into<String>) {
        self.recording = Some(ActionRecording {
            schema_version: 1,
            id: id.into(),
            name: name.into(),
            frames: vec![],
            duration_ms: 0,
            steps: 0,
            updated_at: String::new(),
        });
    }
    pub fn record(&mut self, frame: JointTargetCommand) -> Result<(), ActionError> {
        self.recording
            .as_mut()
            .ok_or(ActionError::InvalidState)?
            .frames
            .push(frame);
        Ok(())
    }
    pub fn finish_recording(&mut self) -> Result<ActionRecording, ActionError> {
        let r = self.recording.take().ok_or(ActionError::InvalidState)?;
        if r.frames.is_empty() {
            return Err(ActionError::Empty);
        }
        Ok(r)
    }
    pub fn play(&mut self, r: ActionRecording) -> Result<(), ActionError> {
        if r.frames.is_empty() {
            return Err(ActionError::Empty);
        }
        self.recording = Some(r);
        self.frame = 0;
        self.state = PlaybackState::Playing;
        self.loops_done = 0;
        Ok(())
    }
    pub fn set_loop(&mut self, enabled: bool, count: Option<u32>) {
        self.loop_enabled = enabled;
        self.loop_count = count;
    }
    #[allow(clippy::should_implement_trait)]
    pub fn next(&mut self) -> Option<JointTargetCommand> {
        if self.state != PlaybackState::Playing {
            return None;
        }
        let r = self.recording.as_ref()?;
        if self.frame >= r.frames.len() {
            if self.loop_enabled && self.loop_count.is_none_or(|n| self.loops_done < n) {
                self.frame = 0;
                self.loops_done += 1;
            } else {
                self.state = PlaybackState::Completed;
                return None;
            }
        }
        let c = self.recording.as_ref()?.frames[self.frame].clone();
        self.frame += 1;
        Some(c)
    }
    pub fn cancel(&mut self) {
        self.state = PlaybackState::Cancelled;
        self.frame = 0;
    }
    pub fn state(&self) -> &PlaybackState {
        &self.state
    }
    pub fn loop_count(&self) -> u32 {
        self.loops_done
    }
    pub fn list(&self) -> Vec<ActionRecording> {
        self.recording.clone().into_iter().collect()
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    fn f(i: u64) -> JointTargetCommand {
        JointTargetCommand {
            schema_version: 1,
            command_id: i.to_string(),
            source: console_contracts::CommandSource::Playback,
            positions: vec![i as f64],
            duration_ms: None,
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
}
