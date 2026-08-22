//! Deterministic command arbitration and 20 Hz latest-wins scheduling.
use console_contracts::{CommandSource, JointTargetCommand};
use thiserror::Error;

pub const TICK_MS: u64 = 50;
pub trait Clock {
    fn now_ms(&self) -> u64;
}
#[derive(Clone, Debug, Default)]
pub struct ManualClock(pub u64);
impl ManualClock {
    pub fn advance(&mut self, ms: u64) {
        self.0 += ms;
    }
    pub fn set(&mut self, ms: u64) {
        self.0 = ms;
    }
}
impl Clock for ManualClock {
    fn now_ms(&self) -> u64 {
        self.0
    }
}

#[derive(Debug, Error, Clone, PartialEq, Eq)]
pub enum MotionError {
    #[error("motion engine is safety locked")]
    Locked,
    #[error("source {active:?} owns motion; {requested:?} rejected")]
    SourceBusy {
        active: CommandSource,
        requested: CommandSource,
    },
    #[error("empty joint command")]
    EmptyCommand,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct StopReport {
    pub cancelled: Vec<CommandSource>,
    pub pending_cleared: bool,
    pub safety_locked: bool,
}

pub struct MotionEngine {
    active_source: Option<CommandSource>,
    pending: Option<JointTargetCommand>,
    last_commit_ms: Option<u64>,
    locked: bool,
    cancelled: Vec<CommandSource>,
    committed: Vec<JointTargetCommand>,
}
impl Default for MotionEngine {
    fn default() -> Self {
        Self::new()
    }
}
impl MotionEngine {
    pub fn new() -> Self {
        Self {
            active_source: None,
            pending: None,
            last_commit_ms: None,
            locked: false,
            cancelled: vec![],
            committed: vec![],
        }
    }
    pub fn submit(&mut self, command: JointTargetCommand) -> Result<(), MotionError> {
        if self.locked {
            return Err(MotionError::Locked);
        }
        if command.joints.is_empty() {
            return Err(MotionError::EmptyCommand);
        }
        if let Some(active) = &self.active_source {
            if active != &command.source {
                return Err(MotionError::SourceBusy {
                    active: active.clone(),
                    requested: command.source,
                });
            }
        } else {
            self.active_source = Some(command.source.clone());
        }
        self.pending = Some(command);
        Ok(())
    }
    /// Commits at most one latest command every 50 ms. A final command bypasses the interval.
    pub fn tick(&mut self, now_ms: u64) -> Option<JointTargetCommand> {
        let final_cmd = self.pending.as_ref().is_some_and(|c| c.final_command);
        let due = self
            .last_commit_ms
            .is_none_or(|t| now_ms.saturating_sub(t) >= TICK_MS);
        if final_cmd || due {
            self.commit(now_ms)
        } else {
            None
        }
    }
    pub fn force_commit(&mut self, now_ms: u64) -> Option<JointTargetCommand> {
        self.commit(now_ms)
    }
    fn commit(&mut self, now_ms: u64) -> Option<JointTargetCommand> {
        let c = self.pending.take()?;
        self.last_commit_ms = Some(now_ms);
        self.committed.push(c.clone());
        Some(c)
    }
    /// Cancels all software operations. This is not a claim of physical power removal.
    pub fn stop_all(&mut self) -> StopReport {
        let mut cancelled = self.cancelled.clone();
        for s in [
            CommandSource::Vision,
            CommandSource::Loop,
            CommandSource::Playback,
            CommandSource::Grasp,
        ] {
            if !cancelled.contains(&s) {
                cancelled.push(s);
            }
        }
        self.active_source = None;
        self.pending = None;
        self.cancelled = cancelled.clone();
        self.locked = true;
        StopReport {
            cancelled,
            pending_cleared: true,
            safety_locked: true,
        }
    }
    pub fn unlock(&mut self) {
        self.locked = false;
        self.cancelled.clear();
    }
    pub fn is_locked(&self) -> bool {
        self.locked
    }
    pub fn committed(&self) -> &[JointTargetCommand] {
        &self.committed
    }
    pub fn active_source(&self) -> Option<&CommandSource> {
        self.active_source.as_ref()
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    fn c(source: CommandSource, id: &str, final_command: bool) -> JointTargetCommand {
        JointTargetCommand {
            schema_version: 1,
            command_id: id.into(),
            source,
            joints: vec![1.],
            duration_ms: None,
            final_command,
        }
    }
    #[test]
    fn latest_wins_20hz_and_final_forces() {
        let mut e = MotionEngine::new();
        e.submit(c(CommandSource::Manual, "1", false)).unwrap();
        e.submit(c(CommandSource::Manual, "2", false)).unwrap();
        assert!(e.tick(0).is_some());
        e.submit(c(CommandSource::Manual, "3", false)).unwrap();
        assert!(e.tick(20).is_none());
        assert_eq!(e.tick(50).unwrap().command_id, "3");
        e.submit(c(CommandSource::Manual, "4", true)).unwrap();
        assert_eq!(e.tick(51).unwrap().command_id, "4");
    }
    #[test]
    fn source_exclusive_and_stop_locks() {
        let mut e = MotionEngine::new();
        e.submit(c(CommandSource::Vision, "v", false)).unwrap();
        assert!(matches!(
            e.submit(c(CommandSource::Manual, "m", false)),
            Err(MotionError::SourceBusy { .. })
        ));
        let r = e.stop_all();
        assert!(
            r.cancelled.contains(&CommandSource::Vision)
                && r.cancelled.contains(&CommandSource::Grasp)
        );
        assert!(matches!(
            e.submit(c(CommandSource::Manual, "m", false)),
            Err(MotionError::Locked)
        ));
        e.unlock();
        assert!(e.submit(c(CommandSource::Manual, "m", false)).is_ok());
    }
}
