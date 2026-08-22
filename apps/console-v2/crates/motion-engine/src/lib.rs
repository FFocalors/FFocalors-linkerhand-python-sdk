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
    #[error("source {0:?} has a pending command")]
    PendingCommand(CommandSource),
    #[error("source {requested:?} cannot end active source {active:?}")]
    EndWrongSource {
        active: CommandSource,
        requested: CommandSource,
    },
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
        if command.positions.is_empty() {
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
    /// Explicitly claims a source for a continuous interaction such as dragging.
    pub fn begin_source(&mut self, source: CommandSource) -> Result<(), MotionError> {
        if self.locked {
            return Err(MotionError::Locked);
        }
        if let Some(active) = &self.active_source {
            if active != &source {
                return Err(MotionError::SourceBusy {
                    active: active.clone(),
                    requested: source,
                });
            }
        } else {
            self.active_source = Some(source);
        }
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
        if c.final_command {
            self.active_source = None;
        }
        self.committed.push(c.clone());
        Some(c)
    }
    /// Ends a continuous source after its latest command has been committed.
    pub fn end_source(&mut self, source: CommandSource) -> Result<(), MotionError> {
        if let Some(active) = &self.active_source {
            if active != &source {
                return Err(MotionError::EndWrongSource {
                    active: active.clone(),
                    requested: source,
                });
            }
            if self.pending.is_some() {
                return Err(MotionError::PendingCommand(source));
            }
            self.active_source = None;
        }
        Ok(())
    }
    /// Force the last command through and end the source in one deterministic step.
    pub fn finish_source(
        &mut self,
        source: CommandSource,
        now_ms: u64,
    ) -> Result<Option<JointTargetCommand>, MotionError> {
        if self.active_source.as_ref() != Some(&source) {
            return Err(MotionError::EndWrongSource {
                active: self.active_source.clone().unwrap_or(CommandSource::Safety),
                requested: source,
            });
        }
        let committed = self.force_commit(now_ms);
        self.active_source = None;
        Ok(committed)
    }
    /// Cancels all software operations. This is not a claim of physical power removal.
    pub fn stop_all(&mut self) -> StopReport {
        let mut cancelled = self.cancelled.clone();
        for s in [
            CommandSource::Vision,
            CommandSource::RockPaperScissors,
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
    /// Cancel one controller-owned source without changing the global safety
    /// lock. Used when an action/loop stop is a normal operator cancellation.
    pub fn cancel_source(&mut self, source: CommandSource) {
        if self.active_source.as_ref() == Some(&source) {
            self.active_source = None;
        }
        if self.pending.as_ref().is_some_and(|command| command.source == source) {
            self.pending = None;
        }
        if !self.cancelled.contains(&source) {
            self.cancelled.push(source);
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
    pub fn has_pending(&self) -> bool {
        self.pending.is_some()
    }
    pub fn active_source(&self) -> Option<&CommandSource> {
        self.active_source.as_ref()
    }
    pub fn cancelled_sources(&self) -> &[CommandSource] {
        &self.cancelled
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
            positions: vec![1.],
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
        assert!(e.active_source().is_none());
        e.submit(c(CommandSource::Playback, "p", false)).unwrap();
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
                && r.cancelled.contains(&CommandSource::RockPaperScissors)
                && r.cancelled.contains(&CommandSource::Grasp)
        );
        assert!(matches!(
            e.submit(c(CommandSource::Manual, "m", false)),
            Err(MotionError::Locked)
        ));
        e.unlock();
        assert!(e.submit(c(CommandSource::Manual, "m", false)).is_ok());
    }
    #[test]
    fn continuous_source_can_end_then_playback_starts() {
        let mut e = MotionEngine::new();
        e.begin_source(CommandSource::Manual).unwrap();
        e.submit(c(CommandSource::Manual, "drag", false)).unwrap();
        assert!(e.end_source(CommandSource::Manual).is_err());
        e.tick(0);
        e.end_source(CommandSource::Manual).unwrap();
        e.submit(c(CommandSource::Playback, "play", false)).unwrap();
        assert_eq!(e.tick(50).unwrap().command_id, "play");
    }
}
