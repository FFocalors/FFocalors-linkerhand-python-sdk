//! Hardware-independent adaptive grasp state machine.
//!
//! It consumes snapshots supplied by the runtime and returns complete
//! normalized vectors. There are no threads, timers, device calls or files in
//! this crate, so every path is reproducible with a fake clock and telemetry.
use console_contracts::{CommandSource, DeviceModel, JointTargetCommand, CURRENT_SCHEMA_VERSION};
use serde::{Deserialize, Serialize};
use thiserror::Error;

pub const CONTROL_STEP_MS: u64 = 50;
pub const DEFAULT_TIMEOUT_MS: u64 = 10_000;
pub const DEFAULT_STEP_LIMIT: f64 = 0.05;

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum Profile {
    O6,
    L6,
    L7,
    L10,
    L20,
    G20,
    L21,
    L25,
}
impl Profile {
    pub fn joint_count(&self) -> usize {
        match self {
            Self::O6 | Self::L6 => 6,
            Self::L7 => 7,
            Self::L10 => 10,
            Self::L20 | Self::G20 => 20,
            Self::L21 | Self::L25 => 25,
        }
    }
    pub fn is_supported(&self) -> bool {
        matches!(self, Self::O6 | Self::L6 | Self::L7 | Self::L10 | Self::L20)
    }
    pub fn model(&self) -> DeviceModel {
        match self {
            Self::O6 => DeviceModel::O6,
            Self::L6 => DeviceModel::L6,
            Self::L7 => DeviceModel::L7,
            Self::L10 => DeviceModel::L10,
            Self::L20 => DeviceModel::L20,
            Self::G20 => DeviceModel::G20,
            Self::L21 => DeviceModel::L21,
            Self::L25 => DeviceModel::L25,
        }
    }
    pub fn label(&self) -> &'static str {
        match self {
            Self::O6 => "O6",
            Self::L6 => "L6",
            Self::L7 => "L7",
            Self::L10 => "L10",
            Self::L20 => "L20",
            Self::G20 => "G20",
            Self::L21 => "L21",
            Self::L25 => "L25",
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum GraspState {
    Idle,
    Calibrating,
    Ready,
    Approaching,
    Grasping,
    Holding,
    Releasing,
    Aborted,
    Failed,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum FailureReason {
    Disconnected,
    TactileMissing,
    Timeout,
    OverCurrent { joint: usize },
    InvalidTelemetry,
    UnsupportedProfile(Profile),
}
impl FailureReason {
    pub fn operator_message(&self) -> &'static str {
        match self {
            Self::Disconnected => "设备已断开，请重新连接后重试。",
            Self::TactileMissing => "未检测到触觉反馈；请启用显式的无触觉降级模式。",
            Self::Timeout => "抓取在规定时间内未完成，请检查目标是否卡住。",
            Self::OverCurrent { .. } => "检测到过流，动作已停止以保护设备。",
            Self::InvalidTelemetry => "遥测数据不完整或超出归一化范围。",
            Self::UnsupportedProfile(_) => "该型号暂不支持智能自适应抓取。",
        }
    }
}

#[derive(Clone, Debug, Error, PartialEq, Eq)]
pub enum GraspError {
    #[error("profile {0:?} is not available for adaptive grasp")]
    UnsupportedProfile(Profile),
    #[error("profile has {expected} joints but got {actual}")]
    JointCount { expected: usize, actual: usize },
    #[error("normalized joint vector is invalid")]
    InvalidVector,
    #[error("invalid transition from {0:?}")]
    Invalid(GraspState),
    #[error("grasp failed: {0:?}")]
    Failed(FailureReason),
}

#[derive(Clone, Debug, PartialEq)]
pub struct GraspConfig {
    pub timeout_ms: u64,
    pub step_limit: f64,
    pub allow_degraded_without_tactile: bool,
    pub touch_threshold: u8,
    pub over_current_threshold: u8,
}
impl Default for GraspConfig {
    fn default() -> Self {
        Self {
            timeout_ms: DEFAULT_TIMEOUT_MS,
            step_limit: DEFAULT_STEP_LIMIT,
            allow_degraded_without_tactile: false,
            touch_threshold: 8,
            over_current_threshold: 250,
        }
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct GraspTelemetry {
    pub connected: bool,
    pub tactile_available: bool,
    pub raw_touch: Vec<u8>,
    pub raw_current: Vec<u8>,
    pub positions: Vec<f64>,
}
impl GraspTelemetry {
    pub fn disconnected() -> Self {
        Self {
            connected: false,
            tactile_available: false,
            raw_touch: Vec::new(),
            raw_current: Vec::new(),
            positions: Vec::new(),
        }
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct GraspOutput {
    pub command: JointTargetCommand,
    pub state: GraspState,
    pub adapted: bool,
    pub degraded: bool,
    pub contact: Vec<bool>,
}

pub struct GraspMachine {
    profile: Profile,
    state: GraspState,
    config: GraspConfig,
    approach_target: Vec<f64>,
    grasp_target: Vec<f64>,
    current: Vec<f64>,
    contact: Vec<bool>,
    started_at_ms: Option<u64>,
    last_tick_ms: Option<u64>,
    degraded: bool,
    last_failure: Option<FailureReason>,
    command_sequence: u64,
}

impl GraspMachine {
    pub fn new(profile: Profile) -> Self {
        let n = profile.joint_count();
        Self {
            profile,
            state: GraspState::Idle,
            config: GraspConfig::default(),
            approach_target: vec![0.5; n],
            grasp_target: vec![0.5; n],
            current: vec![0.5; n],
            contact: vec![false; n],
            started_at_ms: None,
            last_tick_ms: None,
            degraded: false,
            last_failure: None,
            command_sequence: 0,
        }
    }
    pub fn try_new(profile: Profile) -> Result<Self, GraspError> {
        if !profile.is_supported() {
            return Err(GraspError::UnsupportedProfile(profile));
        }
        Ok(Self::new(profile))
    }
    pub fn with_config(mut self, config: GraspConfig) -> Self {
        self.config = config;
        self
    }
    pub fn set_config(&mut self, config: GraspConfig) {
        self.config = config;
    }
    pub fn profile(&self) -> &Profile {
        &self.profile
    }
    pub fn state(&self) -> &GraspState {
        &self.state
    }
    pub fn is_available(&self) -> bool {
        self.profile.is_supported()
    }
    pub fn degraded(&self) -> bool {
        self.degraded
    }
    pub fn failure(&self) -> Option<&FailureReason> {
        self.last_failure.as_ref()
    }
    pub fn failure_message(&self) -> Option<&'static str> {
        self.last_failure
            .as_ref()
            .map(FailureReason::operator_message)
    }

    pub fn calibrate(&mut self) -> Result<(), GraspError> {
        self.start_calibration(0)
    }
    pub fn start_calibration(&mut self, now_ms: u64) -> Result<(), GraspError> {
        self.ensure_supported()?;
        if self.state != GraspState::Idle {
            return Err(GraspError::Invalid(self.state.clone()));
        }
        self.state = GraspState::Calibrating;
        self.started_at_ms = Some(now_ms);
        self.last_failure = None;
        Ok(())
    }
    pub fn calibration_complete(&mut self) -> Result<(), GraspError> {
        if self.state != GraspState::Calibrating {
            return Err(GraspError::Invalid(self.state.clone()));
        }
        self.state = GraspState::Ready;
        self.started_at_ms = None;
        Ok(())
    }

    pub fn start_approach(
        &mut self,
        now_ms: u64,
        approach: &[f64],
        target: &[f64],
    ) -> Result<(), GraspError> {
        self.ensure_supported()?;
        self.validate(approach)?;
        self.validate(target)?;
        if self.state != GraspState::Ready {
            return Err(GraspError::Invalid(self.state.clone()));
        }
        self.approach_target = approach.to_vec();
        self.grasp_target = target.to_vec();
        self.current = approach.to_vec();
        self.contact.fill(false);
        self.degraded = false;
        self.started_at_ms = Some(now_ms);
        self.last_tick_ms = None;
        self.state = GraspState::Approaching;
        Ok(())
    }
    /// Compatibility shortcut for callers that already have an approach pose.
    pub fn grasp(&mut self, joints: &[f64]) -> Result<(), GraspError> {
        self.ensure_supported()?;
        self.validate(joints)?;
        if self.state != GraspState::Ready {
            return Err(GraspError::Invalid(self.state.clone()));
        }
        self.grasp_target = joints.to_vec();
        self.current = joints.to_vec();
        self.contact.fill(false);
        self.started_at_ms = Some(0);
        self.state = GraspState::Grasping;
        Ok(())
    }
    pub fn approach_complete(&mut self) -> Result<(), GraspError> {
        if self.state != GraspState::Approaching {
            return Err(GraspError::Invalid(self.state.clone()));
        }
        self.state = GraspState::Grasping;
        Ok(())
    }
    pub fn grasp_complete(&mut self) -> Result<(), GraspError> {
        if self.state != GraspState::Grasping {
            return Err(GraspError::Invalid(self.state.clone()));
        }
        self.state = GraspState::Holding;
        Ok(())
    }
    pub fn release(&mut self) -> Result<(), GraspError> {
        if self.state != GraspState::Holding {
            return Err(GraspError::Invalid(self.state.clone()));
        }
        self.state = GraspState::Releasing;
        self.started_at_ms = Some(0);
        Ok(())
    }
    pub fn release_complete(&mut self) -> Result<(), GraspError> {
        if self.state != GraspState::Releasing {
            return Err(GraspError::Invalid(self.state.clone()));
        }
        self.state = GraspState::Ready;
        self.started_at_ms = None;
        Ok(())
    }

    /// Progress one fixed-rate control step. A disconnected device, malformed
    /// telemetry, timeout or over-current enters a stable, explainable failure.
    pub fn tick(
        &mut self,
        now_ms: u64,
        telemetry: &GraspTelemetry,
    ) -> Result<Option<GraspOutput>, GraspError> {
        if matches!(
            self.state,
            GraspState::Idle
                | GraspState::Ready
                | GraspState::Holding
                | GraspState::Aborted
                | GraspState::Failed
        ) {
            return Ok(None);
        }
        if !telemetry.connected {
            return Err(self.fail(FailureReason::Disconnected));
        }
        if telemetry.positions.len() != self.profile.joint_count()
            || telemetry
                .positions
                .iter()
                .any(|v| !v.is_finite() || !(0.0..=1.0).contains(v))
        {
            return Err(self.fail(FailureReason::InvalidTelemetry));
        }
        if telemetry
            .raw_current
            .iter()
            .any(|value| *value >= self.config.over_current_threshold)
        {
            return Err(self.fail(FailureReason::OverCurrent {
                joint: telemetry
                    .raw_current
                    .iter()
                    .position(|v| *v >= self.config.over_current_threshold)
                    .unwrap_or(0),
            }));
        }
        if let Some(start) = self.started_at_ms {
            if now_ms.saturating_sub(start) > self.config.timeout_ms {
                return Err(self.fail(FailureReason::Timeout));
            }
        }
        if let Some(last) = self.last_tick_ms {
            if now_ms.saturating_sub(last) < CONTROL_STEP_MS {
                return Ok(None);
            }
        }
        self.last_tick_ms = Some(now_ms);
        self.current = telemetry.positions.clone();
        if !telemetry.tactile_available && !self.config.allow_degraded_without_tactile {
            return Err(self.fail(FailureReason::TactileMissing));
        }
        self.degraded = !telemetry.tactile_available;
        if self.state == GraspState::Approaching {
            self.approach_step();
            if close_enough(&self.current, &self.approach_target) {
                self.state = GraspState::Grasping;
            }
        } else if self.state == GraspState::Grasping {
            self.grasp_step(telemetry);
        } else if self.state == GraspState::Releasing {
            self.release_step();
            if close_enough(&self.current, &self.approach_target) {
                self.state = GraspState::Ready;
                self.started_at_ms = None;
            }
        }
        self.command_sequence += 1;
        let source = CommandSource::Grasp;
        let final_command = self.state == GraspState::Ready;
        Ok(Some(GraspOutput {
            command: JointTargetCommand {
                schema_version: CURRENT_SCHEMA_VERSION,
                command_id: format!("grasp-{}", self.command_sequence),
                source,
                positions: self.current.clone(),
                duration_ms: Some(CONTROL_STEP_MS),
                final_command,
            },
            state: self.state.clone(),
            adapted: self.state == GraspState::Grasping && !self.degraded,
            degraded: self.degraded,
            contact: self.contact.clone(),
        }))
    }
    pub fn abort(&mut self) {
        self.state = GraspState::Aborted;
        self.started_at_ms = None;
        self.last_tick_ms = None;
    }
    pub fn stop_all(&mut self) {
        self.abort();
    }

    fn approach_step(&mut self) {
        move_towards(
            &mut self.current,
            &self.approach_target,
            self.config.step_limit,
        );
    }
    fn grasp_step(&mut self, telemetry: &GraspTelemetry) {
        for i in 0..self.current.len() {
            if !self.contact[i]
                && telemetry.raw_touch.get(i).copied().unwrap_or(0) >= self.config.touch_threshold
            {
                self.contact[i] = true;
            }
            if !self.contact[i] {
                self.current[i] = move_one(
                    self.current[i],
                    self.grasp_target[i],
                    self.config.step_limit,
                );
            }
        }
        if self.contact.iter().all(|value| *value) {
            self.state = GraspState::Holding;
        }
    }
    fn release_step(&mut self) {
        move_towards(
            &mut self.current,
            &self.approach_target,
            self.config.step_limit,
        );
        self.contact.fill(false);
    }
    fn validate(&self, values: &[f64]) -> Result<(), GraspError> {
        if values.len() != self.profile.joint_count() {
            return Err(GraspError::JointCount {
                expected: self.profile.joint_count(),
                actual: values.len(),
            });
        }
        if values
            .iter()
            .any(|v| !v.is_finite() || !(0.0..=1.0).contains(v))
        {
            return Err(GraspError::InvalidVector);
        }
        Ok(())
    }
    fn ensure_supported(&self) -> Result<(), GraspError> {
        if self.profile.is_supported() {
            Ok(())
        } else {
            Err(GraspError::UnsupportedProfile(self.profile.clone()))
        }
    }
    fn fail(&mut self, reason: FailureReason) -> GraspError {
        self.last_failure = Some(reason.clone());
        self.state = GraspState::Failed;
        GraspError::Failed(reason)
    }
}

fn move_one(current: f64, target: f64, limit: f64) -> f64 {
    let delta = (target - current).clamp(-limit, limit);
    (current + delta).clamp(0.0, 1.0)
}
fn move_towards(current: &mut [f64], target: &[f64], limit: f64) {
    for (current, target) in current.iter_mut().zip(target) {
        *current = move_one(*current, *target, limit);
    }
}
fn close_enough(current: &[f64], target: &[f64]) -> bool {
    current
        .iter()
        .zip(target)
        .all(|(a, b)| (a - b).abs() <= DEFAULT_STEP_LIMIT)
}

#[cfg(test)]
mod tests {
    use super::*;
    fn telemetry(n: usize) -> GraspTelemetry {
        GraspTelemetry {
            connected: true,
            tactile_available: true,
            raw_touch: vec![0; n],
            raw_current: vec![0; n],
            positions: vec![0.5; n],
        }
    }
    #[test]
    fn supported_profiles_follow_full_lifecycle_and_abort() {
        for profile in [
            Profile::O6,
            Profile::L6,
            Profile::L7,
            Profile::L10,
            Profile::L20,
        ] {
            let n = profile.joint_count();
            let mut machine = GraspMachine::new(profile);
            machine.calibrate().unwrap();
            machine.calibration_complete().unwrap();
            machine.grasp(&vec![0.5; n]).unwrap();
            machine.grasp_complete().unwrap();
            machine.release().unwrap();
            machine.release_complete().unwrap();
            machine.abort();
            assert_eq!(*machine.state(), GraspState::Aborted);
        }
    }
    #[test]
    fn unsupported_profiles_are_explicit() {
        let mut machine = GraspMachine::new(Profile::G20);
        assert!(!machine.is_available());
        assert_eq!(
            machine.calibrate(),
            Err(GraspError::UnsupportedProfile(Profile::G20))
        );
    }
    #[test]
    fn fixed_rate_output_contact_hold_and_degraded_mode() {
        let mut machine = GraspMachine::new(Profile::O6).with_config(GraspConfig {
            allow_degraded_without_tactile: true,
            ..GraspConfig::default()
        });
        machine.calibrate().unwrap();
        machine.calibration_complete().unwrap();
        machine.start_approach(0, &[0.5; 6], &[0.9; 6]).unwrap();
        let mut t = telemetry(6);
        t.tactile_available = false;
        let first = machine.tick(50, &t).unwrap().unwrap();
        assert!(first.degraded);
        t.raw_touch = vec![20; 6];
        t.positions = first.command.positions;
        let next = machine.tick(100, &t).unwrap().unwrap();
        assert_eq!(next.contact, vec![true; 6]);
        assert_eq!(next.command.positions, t.positions);
    }
    #[test]
    fn disconnect_and_timeout_are_explainable() {
        let mut machine = GraspMachine::new(Profile::O6);
        machine.calibrate().unwrap();
        machine.calibration_complete().unwrap();
        machine.grasp(&[0.5; 6]).unwrap();
        assert_eq!(
            machine.tick(1, &GraspTelemetry::disconnected()),
            Err(GraspError::Failed(FailureReason::Disconnected))
        );
    }
}
