//! Hardware-independent adaptive grasp state machine (v2 rewrite).
//!
//! Port of the proven grasp algorithm from the v1 Python console
//! (`adaptive_grasp_controller.py` / `joint_signal_analyzer.py`) with the
//! P0–P3 improvements applied:
//!
//! P0
//!  - preset-specific parameters (soft / cube / precision)
//!  - empty-grasp detection: zero contact -> fail; partial contact -> preload
//!
//! P1
//!  - continuous contact score (smooth stall mapping, no binary threshold)
//!  - accumulated-command stall detection (survives fine-mode frame skipping)
//!  - percentile calibration (P95 error / P90 jitter instead of raw max)
//!
//! P2
//!  - preload position-follow validation
//!  - phased timeout budget (coarse vs fine/preload)
//!  - local degradation (a stalled non-thumb joint freezes, grasp continues)
//!
//! P3
//!  - unified, configurable analysis windows
//!  - parameterised settle delay
//!  - online baseline EMA that only ever raises detection thresholds
//!
//! The crate stays hardware-independent: it consumes snapshots supplied by
//! the runtime and returns complete normalized vectors (D3). No threads,
//! timers, device calls or files, so every path is reproducible.
use std::collections::VecDeque;

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
    /// Indices of the joints that belong to the thumb. During the no-load
    /// calibration sweep these move in a separate phase from the fingers so
    /// the thumb can never fight the index finger (they never share a tick).
    pub fn thumb_joint_indices(&self) -> &'static [usize] {
        match self {
            Self::O6 | Self::L6 => &[0, 1],
            Self::L7 => &[0, 1, 6],
            Self::L10 => &[0, 1, 9],
            Self::L20 => &[0, 1, 2, 3, 4, 5],
            Self::G20 | Self::L21 | Self::L25 => &[],
        }
    }
    /// Default `(pregrasp, close_limits)` poses, normalized to [0, 1]. They
    /// mirror the proven v1 `default_power_grasp_*` profiles so the pre-grasp
    /// pose and the safe closed limits match the physical hand.
    pub fn default_grasp_poses(&self) -> Option<(Vec<f64>, Vec<f64>)> {
        let (pregrasp, close): (&[u8], &[u8]) = match self {
            Self::O6 => (&[250, 80, 250, 250, 250, 250], &[20, 80, 10, 10, 10, 10]),
            Self::L6 => (&[250, 40, 250, 250, 250, 250], &[20, 40, 10, 10, 10, 10]),
            Self::L7 => (
                &[250, 15, 250, 250, 250, 250, 170],
                &[40, 15, 20, 20, 20, 20, 170],
            ),
            Self::L10 => (
                &[255, 255, 255, 255, 255, 255, 128, 67, 89, 255],
                &[90, 255, 20, 20, 20, 20, 128, 67, 89, 255],
            ),
            Self::L20 => (
                &[
                    255, 255, 255, 255, 255, 255, 10, 100, 180, 240, 245, 255, 255, 255, 255, 255,
                    255, 255, 255, 255,
                ],
                &[
                    40, 20, 20, 20, 20, 255, 10, 100, 180, 240, 130, 255, 255, 255, 255, 135, 20,
                    20, 20, 20,
                ],
            ),
            Self::G20 | Self::L21 | Self::L25 => return None,
        };
        let normalize = |values: &[u8]| values.iter().map(|v| *v as f64 / 255.0).collect();
        Some((normalize(pregrasp), normalize(close)))
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

/// Adaptive grasp strategy. Each preset carries its own closure profile.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum GraspPreset {
    Soft,
    Cube,
    Precision,
}
impl GraspPreset {
    pub fn id(&self) -> &'static str {
        match self {
            Self::Soft => "soft",
            Self::Cube => "cube",
            Self::Precision => "precision",
        }
    }
    pub fn label(&self) -> &'static str {
        match self {
            Self::Soft => "柔软物体",
            Self::Cube => "方形物体",
            Self::Precision => "精细拾取",
        }
    }
    pub fn from_id(id: &str) -> Option<Self> {
        match id {
            "soft" => Some(Self::Soft),
            "cube" => Some(Self::Cube),
            "precision" => Some(Self::Precision),
            _ => None,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum GraspState {
    Idle,
    Calibrating,
    Ready,
    Approaching,
    ClosingCoarse,
    ClosingFine,
    /// Legacy variant kept for callers that still use `grasp()`/`approach_complete()`.
    Grasping,
    Preloading,
    Holding,
    Releasing,
    Aborted,
    Failed,
}

/// Per-joint state exposed to the UI (mirrors the v1 GraspJointState).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum GraspJointState {
    Idle,
    ClosingCoarse,
    ClosingFine,
    ContactCandidate,
    ContactConfirmed,
    Frozen,
    LimitReached,
    Error,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum FailureReason {
    Disconnected,
    TactileMissing,
    Timeout,
    /// Zero confirmed contacts while every moving joint reached its limit.
    EmptyGrasp,
    /// A critical joint (thumb or majority) stalled out of control.
    JointStall {
        joint: usize,
    },
    OverCurrent {
        joint: usize,
    },
    InvalidTelemetry,
    UnsupportedProfile(Profile),
}
impl FailureReason {
    pub fn operator_message(&self) -> &'static str {
        match self {
            Self::Disconnected => "设备已断开，请重新连接后重试。",
            Self::TactileMissing => "未检测到触觉反馈；请启用显式的无触觉降级模式。",
            Self::Timeout => "抓取在规定时间内未完成，请检查目标是否卡住。",
            Self::EmptyGrasp => "未能触及物体，到达行程安全极限（空抓）。",
            Self::JointStall { .. } => "关节跟踪异常，动作已停止以保护设备。",
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

/// All tunables live here so every path is reproducible with a fake clock.
/// Values are normalized to [0,1] unless their name says otherwise.
#[derive(Clone, Debug, PartialEq)]
pub struct GraspConfig {
    pub timeout_ms: u64,
    pub step_limit: f64,
    pub allow_degraded_without_tactile: bool,
    pub touch_threshold: u8,
    pub over_current_threshold: u8,
    /// Strategy preset (soft / cube / precision).
    pub preset: GraspPreset,
    // ── closure steps ──
    pub coarse_step_limit: f64,
    pub fine_step_limit: f64,
    pub preload_step_limit: f64,
    pub preload_max_steps: usize,
    // ── contact scoring ──
    pub contact_score_threshold: f64,
    pub confirmation_windows: usize,
    pub minimum_contacts: usize,
    pub thumb_required: bool,
    // ── analysis windows (P3/A4: unified, configurable) ──
    pub stall_window: usize,
    pub progress_window: usize,
    pub jitter_window: usize,
    // ── stall features ──
    pub stall_span_threshold: f64,
    pub stall_lead_threshold: f64,
    pub movement_threshold: f64,
    // ── error / jitter thresholds (calibration overrides these per joint) ──
    pub error_threshold: f64,
    pub jitter_threshold: f64,
    /// Above this normalized tracking error a non-thumb joint freezes instead
    /// of aborting the whole grasp (P2/C6).
    pub error_fail_limit: f64,
    // ── timing ──
    pub verify_ms: u64,
    pub coarse_timeout_ratio: f64,
    /// Ticks to let the hand settle at the approach pose before closing (D1).
    pub approach_settle_ticks: usize,
}
impl Default for GraspConfig {
    fn default() -> Self {
        Self::for_preset(GraspPreset::Cube)
    }
}
impl GraspConfig {
    pub fn for_preset(preset: GraspPreset) -> Self {
        let base = Self {
            timeout_ms: DEFAULT_TIMEOUT_MS,
            step_limit: DEFAULT_STEP_LIMIT,
            allow_degraded_without_tactile: false,
            touch_threshold: 8,
            over_current_threshold: 250,
            preset,
            coarse_step_limit: 0.04,
            fine_step_limit: 0.008,
            preload_step_limit: 0.004,
            preload_max_steps: 1,
            contact_score_threshold: 0.65,
            confirmation_windows: 3,
            minimum_contacts: 2,
            thumb_required: true,
            stall_window: 3,
            progress_window: 4,
            jitter_window: 8,
            stall_span_threshold: 0.005,
            stall_lead_threshold: 0.01,
            movement_threshold: 0.008,
            error_threshold: 0.06,
            jitter_threshold: 0.01,
            error_fail_limit: 0.4,
            verify_ms: 800,
            coarse_timeout_ratio: 0.6,
            approach_settle_ticks: 10,
        };
        match preset {
            // Soft: gentle, contact-sensitive (low threshold, small steps).
            GraspPreset::Soft => GraspConfig {
                coarse_step_limit: 0.03,
                fine_step_limit: 0.006,
                preload_step_limit: 0.003,
                preload_max_steps: 1,
                contact_score_threshold: 0.55,
                minimum_contacts: 2,
                verify_ms: 800,
                ..base
            },
            // Cube: stable parallel pinch, more contacts, firmer preload.
            GraspPreset::Cube => GraspConfig {
                coarse_step_limit: 0.04,
                fine_step_limit: 0.008,
                preload_step_limit: 0.004,
                preload_max_steps: 2,
                contact_score_threshold: 0.65,
                minimum_contacts: 3,
                verify_ms: 1000,
                ..base
            },
            // Precision: fingertip pinch, strict confirmation, longer verify.
            GraspPreset::Precision => GraspConfig {
                coarse_step_limit: 0.02,
                fine_step_limit: 0.004,
                preload_step_limit: 0.003,
                preload_max_steps: 1,
                contact_score_threshold: 0.75,
                minimum_contacts: 1,
                verify_ms: 1200,
                ..base
            },
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
    /// Per-joint states for the UI (idle/coarse/fine/candidate/confirmed/frozen/limit/error).
    pub joint_states: Vec<GraspJointState>,
    /// Continuous contact score per joint (0..1) for the UI.
    pub contact_scores: Vec<f64>,
}

/// Per-joint calibration thresholds derived from the no-load sweep.
#[derive(Clone, Debug, PartialEq)]
pub struct JointCalibration {
    pub error_threshold: f64,
    pub jitter_threshold: f64,
    pub movement_threshold: f64,
}

/// Sliding history + rolling statistics for one joint (P3/A3: incremental).
struct JointAnalyzer {
    window: VecDeque<(f64, f64)>, // (actual, target)
    // rolling second-difference stats for jitter
    diff1: VecDeque<f64>,
    diff2_sum: f64,
    diff2_sumsq: f64,
    ema_error: f64,
    ema_jitter: f64,
    calibration: Option<JointCalibration>,
}
impl JointAnalyzer {
    fn new(jitter_window: usize) -> Self {
        Self {
            window: VecDeque::with_capacity(jitter_window.max(5)),
            diff1: VecDeque::with_capacity(jitter_window.max(5)),
            diff2_sum: 0.0,
            diff2_sumsq: 0.0,
            ema_error: 0.0,
            ema_jitter: 0.0,
            calibration: None,
        }
    }
    fn push(&mut self, actual: f64, target: f64, jitter_window: usize) {
        // Rolling second-difference statistics (P3/A3: incremental jitter).
        if let Some(prev) = self.window.back() {
            let d1 = actual - prev.0;
            if let Some(prev_d1) = self.diff1.back().copied() {
                let d2 = d1 - prev_d1;
                self.diff2_sum += d2;
                self.diff2_sumsq += d2 * d2;
                self.diff1.push_back(d1);
                // evict the oldest second difference when the window is full
                let cap = jitter_window.max(3).saturating_sub(1);
                if self.diff1.len() > cap {
                    if let Some(old) = self.diff1.pop_front() {
                        if let Some(next) = self.diff1.front() {
                            let old_d2 = *next - old;
                            self.diff2_sum -= old_d2;
                            self.diff2_sumsq -= old_d2 * old_d2;
                        }
                    }
                }
            } else {
                self.diff1.push_back(d1);
            }
        }
        self.window.push_back((actual, target));
        let cap = jitter_window.max(5);
        if self.window.len() > cap {
            self.window.pop_front();
        }
        // EMA baselines (D2) — only meaningful before contact, decayed slowly.
        self.ema_error = self.ema_error * 0.9 + (target - actual).abs() * 0.1;
        let jit = self.jitter();
        self.ema_jitter = self.ema_jitter * 0.9 + jit * 0.1;
    }
    fn jitter(&self) -> f64 {
        let n = self.diff1.len().saturating_sub(1);
        if n < 2 {
            return 0.0;
        }
        let mean = self.diff2_sum / n as f64;
        let variance = (self.diff2_sumsq / n as f64 - mean * mean).max(0.0);
        // sample standard deviation (n-1 denominator, matches v1)
        (variance * n as f64 / (n - 1) as f64).sqrt()
    }
    fn effective_error_threshold(&self) -> f64 {
        let base = self
            .calibration
            .as_ref()
            .map(|c| c.error_threshold)
            .unwrap_or(0.06);
        // Online baseline (D2): only ever raise the threshold (monotone-safe).
        base.max(self.ema_error * 2.5 + 0.02)
    }
    fn effective_jitter_threshold(&self) -> f64 {
        let base = self
            .calibration
            .as_ref()
            .map(|c| c.jitter_threshold)
            .unwrap_or(0.01);
        base.max(self.ema_jitter * 2.0 + 0.005)
    }
    fn effective_movement_threshold(&self) -> f64 {
        self.calibration
            .as_ref()
            .map(|c| c.movement_threshold)
            .unwrap_or(0.008)
    }
    /// Continuous contact score in [0,1] (P1/A1 + A5).
    fn contact_score(&self, closing_dir: f64, config: &GraspConfig) -> f64 {
        let n = self.window.len();
        if n < 5 {
            return 0.0;
        }
        let actual = self.window.back().map(|w| w.0).unwrap_or(0.0);
        let target = self.window.back().map(|w| w.1).unwrap_or(0.0);

        // 1. stall score — continuous, no binary threshold
        let mut stall_score = 0.0;
        // instant stall over the last `stall_window` points
        let sw = config.stall_window.min(n);
        let recent: Vec<f64> = self.window.iter().rev().take(sw).map(|w| w.0).collect();
        let span = recent.iter().cloned().fold(f64::NAN, f64::max)
            - recent.iter().cloned().fold(f64::NAN, f64::min);
        let span = if span.is_nan() { 0.0 } else { span };
        let lead = (target - actual) * closing_dir;
        if span < config.stall_span_threshold && lead >= config.stall_lead_threshold {
            stall_score = 1.0;
        } else {
            // fallback: accumulated command moved but actual barely moved.
            // Uses window span of targets (works in fine mode where a single
            // tick often carries no command delta — A5).
            let pw = config.progress_window.min(n);
            let t0 = self.window[n - pw].1;
            let command_moved = (target - t0) * closing_dir;
            let a0 = self.window[n - pw].0;
            let actual_moved = (actual - a0) * closing_dir;
            let mov_th = self.effective_movement_threshold();
            if command_moved > 0.0 && actual_moved < mov_th {
                // continuous ramp instead of a hard 0/1 (A1)
                stall_score = 1.0 - (actual_moved / mov_th.max(1e-6)).min(1.0);
            }
        }

        // 2. tracking-error score
        let pos_error = (target - actual).abs();
        let error_th = self.effective_error_threshold().max(1e-6);
        let error_score = (pos_error / error_th).min(1.0);

        // 3. jitter score
        let jit_th = self.effective_jitter_threshold().max(1e-6);
        let jitter_score = (self.jitter() / jit_th).min(1.0);

        // weights from v1: stall 0.7 / error 0.2 / jitter 0.1
        0.7 * stall_score + 0.2 * error_score + 0.1 * jitter_score
    }
}

pub struct GraspMachine {
    profile: Profile,
    state: GraspState,
    config: GraspConfig,
    approach_target: Vec<f64>,
    grasp_target: Vec<f64>,
    current: Vec<f64>,
    contact: Vec<bool>,
    contact_scores: Vec<f64>,
    joint_states: Vec<GraspJointState>,
    analyzers: Vec<JointAnalyzer>,
    confirmation_counts: Vec<usize>,
    /// Closing direction per joint: +1 closer target, -1 opener, 0 fixed.
    closing_directions: Vec<f64>,
    /// Contact-confirmed target capture (freeze position).
    contact_positions: Vec<f64>,
    /// Joints frozen by local degradation (C6) or thumb yield.
    failed_joints: Vec<bool>,
    started_at_ms: Option<u64>,
    phase_started_at_ms: Option<u64>,
    last_tick_ms: Option<u64>,
    degraded: bool,
    last_failure: Option<FailureReason>,
    command_sequence: u64,
    settle_ticks: usize,
    preload_steps_taken: usize,
    calibration: Vec<Option<JointCalibration>>,
    /// Calibration sweep history (error / jitter samples per joint).
    calib_errors: Vec<Vec<f64>>,
    calib_jitters: Vec<Vec<f64>>,
    /// Calibration sweep phase: 0 = fingers first, 1 = thumb afterwards, so
    /// the thumb and the fingers never move on the same tick (issue fix).
    calib_phase: usize,
}

impl GraspMachine {
    pub fn new(profile: Profile) -> Self {
        let n = profile.joint_count();
        let config = GraspConfig::default();
        Self {
            profile,
            state: GraspState::Idle,
            config,
            approach_target: vec![0.5; n],
            grasp_target: vec![0.5; n],
            current: vec![0.5; n],
            contact: vec![false; n],
            contact_scores: vec![0.0; n],
            joint_states: vec![GraspJointState::Idle; n],
            analyzers: (0..n).map(|_| JointAnalyzer::new(8)).collect(),
            confirmation_counts: vec![0; n],
            closing_directions: vec![0.0; n],
            contact_positions: vec![0.5; n],
            failed_joints: vec![false; n],
            started_at_ms: None,
            phase_started_at_ms: None,
            last_tick_ms: None,
            degraded: false,
            last_failure: None,
            command_sequence: 0,
            settle_ticks: 0,
            preload_steps_taken: 0,
            calibration: vec![None; n],
            calib_errors: vec![Vec::new(); n],
            calib_jitters: vec![Vec::new(); n],
            calib_phase: 0,
        }
    }
    pub fn try_new(profile: Profile) -> Result<Self, GraspError> {
        if !profile.is_supported() {
            return Err(GraspError::UnsupportedProfile(profile));
        }
        Ok(Self::new(profile))
    }
    pub fn with_config(mut self, config: GraspConfig) -> Self {
        self.set_config(config);
        self
    }
    pub fn set_config(&mut self, config: GraspConfig) {
        self.config = config;
    }
    /// Select a grasp strategy preset (soft / cube / precision).
    pub fn set_preset(&mut self, preset: GraspPreset) {
        self.config = GraspConfig::for_preset(preset);
    }
    pub fn config(&self) -> &GraspConfig {
        &self.config
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
    pub fn contact(&self) -> &[bool] {
        &self.contact
    }
    pub fn contact_scores(&self) -> &[f64] {
        &self.contact_scores
    }
    pub fn joint_states(&self) -> &[GraspJointState] {
        &self.joint_states
    }

    // ── control interface ──

    pub fn calibrate(&mut self) -> Result<(), GraspError> {
        self.start_calibration(0)
    }
    pub fn start_calibration(&mut self, now_ms: u64) -> Result<(), GraspError> {
        self.ensure_supported()?;
        // Idle/Ready for a normal run; Failed/Aborted are terminal states that
        // a recalibration must be able to recover from (issue fix: after a
        // failed grasp the operator can always restart calibration).
        if !matches!(
            self.state,
            GraspState::Idle | GraspState::Ready | GraspState::Failed | GraspState::Aborted
        ) {
            return Err(GraspError::Invalid(self.state.clone()));
        }
        // Reset sweep collectors.
        let n = self.profile.joint_count();
        self.calibration = vec![None; n];
        self.calib_errors = vec![Vec::new(); n];
        self.calib_jitters = vec![Vec::new(); n];
        self.calib_phase = 0;
        self.current = vec![0.5; n];
        self.grasp_target = vec![0.5; n];
        self.closing_directions = self.derive_directions(&self.grasp_target, &self.grasp_target);
        // Calibration sweeps toward the closed pose (target 0 for flexors).
        for i in 0..n {
            self.closing_directions[i] = -1.0; // sweep closed by default
        }
        self.state = GraspState::Calibrating;
        self.started_at_ms = Some(now_ms);
        self.phase_started_at_ms = Some(now_ms);
        self.last_failure = None;
        Ok(())
    }
    pub fn calibration_complete(&mut self) -> Result<(), GraspError> {
        if self.state != GraspState::Calibrating {
            return Err(GraspError::Invalid(self.state.clone()));
        }
        self.compute_calibration();
        self.state = GraspState::Ready;
        self.started_at_ms = None;
        self.phase_started_at_ms = None;
        Ok(())
    }
    pub fn is_calibrated(&self) -> bool {
        self.state == GraspState::Ready || self.calibration.iter().any(|c| c.is_some())
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
        // A failed/aborted grasp can go straight back to the pre-grasp pose:
        // reset() returns to Ready whenever a session calibration still exists.
        let from = self.state.clone();
        if !matches!(self.state, GraspState::Ready) {
            self.reset();
        }
        if self.state != GraspState::Ready {
            return Err(GraspError::Invalid(from));
        }
        self.approach_target = approach.to_vec();
        self.grasp_target = target.to_vec();
        self.current = approach.to_vec();
        self.contact.fill(false);
        self.contact_scores.fill(0.0);
        self.failed_joints.fill(false);
        self.degraded = false;
        self.settle_ticks = 0;
        self.preload_steps_taken = 0;
        self.confirmation_counts.fill(0);
        self.joint_states.fill(GraspJointState::Idle);
        self.closing_directions = self.derive_directions(&self.grasp_target, approach);
        self.started_at_ms = Some(now_ms);
        self.phase_started_at_ms = Some(now_ms);
        self.last_tick_ms = None;
        self.state = GraspState::Approaching;
        Ok(())
    }
    /// Compatibility shortcut for callers that already have an approach pose.
    /// Starts closing from the open pose (0.8) toward the given closed target.
    pub fn grasp(&mut self, joints: &[f64]) -> Result<(), GraspError> {
        self.ensure_supported()?;
        self.validate(joints)?;
        if self.state != GraspState::Ready {
            return Err(GraspError::Invalid(self.state.clone()));
        }
        let n = self.profile.joint_count();
        self.grasp_target = joints.to_vec();
        self.approach_target = vec![0.8; n];
        self.current = vec![0.8; n];
        self.contact.fill(false);
        self.contact_scores.fill(0.0);
        self.failed_joints.fill(false);
        self.confirmation_counts.fill(0);
        self.joint_states.fill(GraspJointState::Idle);
        self.closing_directions = self.derive_directions(&self.grasp_target, &self.approach_target);
        self.started_at_ms = Some(0);
        self.phase_started_at_ms = Some(0);
        self.state = GraspState::ClosingCoarse;
        Ok(())
    }
    pub fn approach_complete(&mut self) -> Result<(), GraspError> {
        if self.state != GraspState::Approaching {
            return Err(GraspError::Invalid(self.state.clone()));
        }
        self.state = GraspState::ClosingCoarse;
        self.phase_started_at_ms = Some(
            self.started_at_ms
                .unwrap_or(0)
                .saturating_add(self.config.approach_settle_ticks as u64 * CONTROL_STEP_MS),
        );
        Ok(())
    }
    pub fn grasp_complete(&mut self) -> Result<(), GraspError> {
        if !matches!(
            self.state,
            GraspState::ClosingCoarse
                | GraspState::ClosingFine
                | GraspState::Preloading
                | GraspState::Grasping
        ) {
            return Err(GraspError::Invalid(self.state.clone()));
        }
        self.state = GraspState::Holding;
        self.phase_started_at_ms = None;
        Ok(())
    }
    pub fn release(&mut self) -> Result<(), GraspError> {
        // Holding is the normal success path; Failed/Aborted are the emergency
        // path where the operator still needs to open the hand after a stop.
        if !matches!(
            self.state,
            GraspState::Holding | GraspState::Failed | GraspState::Aborted
        ) {
            return Err(GraspError::Invalid(self.state.clone()));
        }
        if !matches!(self.state, GraspState::Holding) {
            // Emergency open: drive every joint back toward the open pose.
            self.approach_target = vec![0.8; self.profile.joint_count()];
        }
        self.last_failure = None;
        self.state = GraspState::Releasing;
        self.started_at_ms = Some(0);
        self.phase_started_at_ms = Some(0);
        Ok(())
    }
    pub fn release_complete(&mut self) -> Result<(), GraspError> {
        if self.state != GraspState::Releasing {
            return Err(GraspError::Invalid(self.state.clone()));
        }
        self.state = GraspState::Ready;
        self.started_at_ms = None;
        self.phase_started_at_ms = None;
        Ok(())
    }

    // ── control loop ──

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
        // P2/C4: phased timeout budget
        if let Some(phase_start) = self.phase_started_at_ms {
            let elapsed = now_ms.saturating_sub(phase_start);
            let budget = if self.state == GraspState::ClosingCoarse {
                (self.config.timeout_ms as f64 * self.config.coarse_timeout_ratio) as u64
            } else {
                (self.config.timeout_ms as f64 * (1.0 - self.config.coarse_timeout_ratio)) as u64
            };
            if matches!(
                self.state,
                GraspState::ClosingCoarse | GraspState::ClosingFine | GraspState::Preloading
            ) && elapsed > budget
            {
                return Err(self.fail(FailureReason::Timeout));
            }
        }
        if let Some(last) = self.last_tick_ms {
            if now_ms.saturating_sub(last) < CONTROL_STEP_MS {
                return Ok(None);
            }
        }
        self.last_tick_ms = Some(now_ms);
        // `current` is the command vector and is NOT overwritten by telemetry;
        // telemetry feeds the analyzers inside each step instead.
        if !telemetry.tactile_available && !self.config.allow_degraded_without_tactile {
            return Err(self.fail(FailureReason::TactileMissing));
        }
        self.degraded = !telemetry.tactile_available;

        match self.state {
            GraspState::Calibrating => self.calibration_step(now_ms, telemetry),
            GraspState::Approaching => self.approach_step(now_ms),
            GraspState::ClosingCoarse | GraspState::ClosingFine | GraspState::Grasping => {
                self.closing_step(now_ms, telemetry);
            }
            GraspState::Preloading => self.preloading_step(now_ms),
            GraspState::Releasing => {
                self.release_step();
                if close_enough(&self.current, &self.approach_target) {
                    self.state = GraspState::Ready;
                    self.started_at_ms = None;
                    self.phase_started_at_ms = None;
                }
            }
            _ => {}
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
            adapted: matches!(
                self.state,
                GraspState::ClosingCoarse | GraspState::ClosingFine | GraspState::Preloading
            ) && !self.degraded,
            degraded: self.degraded,
            contact: self.contact.clone(),
            joint_states: self.joint_states.clone(),
            contact_scores: self.contact_scores.clone(),
        }))
    }
    pub fn abort(&mut self) {
        self.state = GraspState::Aborted;
        self.started_at_ms = None;
        self.last_tick_ms = None;
        self.phase_started_at_ms = None;
    }
    /// Recover from a terminal state (failed/aborted). Returns to `Ready` when
    /// a session calibration still exists, otherwise back to `Idle`. This lets
    /// an operator re-approach / re-grasp or recalibrate after a stop instead
    /// of being stuck in a dead-end state (issue fix).
    pub fn reset(&mut self) {
        let calibrated = self.is_calibrated();
        self.state = if calibrated {
            GraspState::Ready
        } else {
            GraspState::Idle
        };
        self.started_at_ms = None;
        self.phase_started_at_ms = None;
        self.last_tick_ms = None;
        self.last_failure = None;
        self.degraded = false;
        self.settle_ticks = 0;
        self.preload_steps_taken = 0;
        self.confirmation_counts.fill(0);
        self.joint_states.fill(GraspJointState::Idle);
        self.failed_joints.fill(false);
        self.contact.fill(false);
        self.contact_scores.fill(0.0);
    }
    pub fn stop_all(&mut self) {
        self.abort();
    }

    // ── calibration sweep ──

    fn calibration_step(&mut self, _now_ms: u64, telemetry: &GraspTelemetry) {
        let n = self.profile.joint_count();
        let thumb = self.profile.thumb_joint_indices();
        let finger_phase = self.calib_phase == 0;
        let mut all_done = true;
        let mut target_updated = false;
        for i in 0..n {
            let is_thumb = thumb.contains(&i);
            if finger_phase == is_thumb {
                // This joint belongs to the other sweep group; leave it parked
                // until its phase starts so the thumb and the fingers never
                // move on the same tick (issue fix: no more thumb/index fight).
                continue;
            }
            let actual = telemetry.positions[i];
            let target = self.grasp_target[i];
            let limit = 0.05; // closed limit for the sweep
                              // keep closing until the closed limit is reached
            if (target - limit).abs() > 1e-6 {
                all_done = false;
                let next = (target - 0.016).max(limit);
                self.grasp_target[i] = next;
                target_updated = true;
            }
            // record error & jitter samples
            let error = (target - actual).abs();
            let jit = self.analyzers[i].jitter();
            self.analyzers[i].push(actual, target, self.config.jitter_window);
            self.calib_errors[i].push(error);
            self.calib_jitters[i].push(jit);
        }
        if target_updated {
            self.current = self.grasp_target.clone();
        }
        if all_done {
            if finger_phase {
                // Fingers reached their closed limits first; move on to the
                // thumb sweep so both groups stay asynchronous.
                self.calib_phase = 1;
            } else {
                self.compute_calibration();
                // back to the open pose, ready
                self.current = vec![0.5; n];
                self.grasp_target = vec![0.5; n];
                self.state = GraspState::Ready;
                self.started_at_ms = None;
                self.phase_started_at_ms = None;
            }
        }
    }
    /// P1/B1: derive per-joint thresholds from the no-load sweep using
    /// percentiles (P95 error, P90 jitter) plus a safety margin, instead of
    /// the raw maximum which is sensitive to outliers.
    fn compute_calibration(&mut self) {
        let n = self.profile.joint_count();
        for i in 0..n {
            let errs = &self.calib_errors[i];
            let jits = &self.calib_jitters[i];
            if errs.is_empty() {
                continue;
            }
            let mut err_sorted = errs.clone();
            err_sorted.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
            let mut jit_sorted = jits.clone();
            jit_sorted.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
            let p95 = percentile(&err_sorted, 0.95);
            let p90 = percentile(&jit_sorted, 0.90);
            let err_th = (p95 * 1.5 + 0.03).clamp(0.04, 0.5); // v1: max*1.5+8/255
            let jit_th = (p90 * 2.0 + 0.002).clamp(0.004, 0.2); // v1: max*2.0+0.5/255
            self.calibration[i] = Some(JointCalibration {
                error_threshold: err_th,
                jitter_threshold: jit_th,
                movement_threshold: (p95 * 0.4).clamp(0.004, 0.05),
            });
            if let Some(c) = &self.calibration[i] {
                self.analyzers[i].calibration = Some(c.clone());
            }
        }
    }

    // ── approach / closing / preload / release ──

    fn approach_step(&mut self, _now_ms: u64) {
        // D1: settle at the approach pose for `approach_settle_ticks` so
        // motors can catch up (v1 waited a fixed 500ms).
        if self.settle_ticks < self.config.approach_settle_ticks {
            move_towards(
                &mut self.current,
                &self.approach_target,
                self.config.step_limit,
            );
            self.settle_ticks += 1;
            return;
        }
        // Hold the pre-grasp pose until the operator explicitly starts the
        // grasp (approach_complete()). Selecting/clicking the pre-grasp step
        // must never auto-start closing (issue fix: the grasp only begins when
        // the operator chooses a preset and presses "开始抓取").
        move_towards(
            &mut self.current,
            &self.approach_target,
            self.config.step_limit,
        );
    }

    fn closing_step(&mut self, now_ms: u64, telemetry: &GraspTelemetry) {
        let n = self.profile.joint_count();
        let fine = self.state == GraspState::ClosingFine;
        let step = if fine {
            self.config.fine_step_limit
        } else {
            self.config.coarse_step_limit
        };
        let mut any_candidate = false;

        for i in 0..n {
            let dir = self.closing_directions[i];
            if dir == 0.0
                || self.joint_states[i] == GraspJointState::Frozen
                || self.joint_states[i] == GraspJointState::ContactConfirmed
                || self.joint_states[i] == GraspJointState::LimitReached
                || self.failed_joints[i]
            {
                continue;
            }
            let actual = telemetry.positions[i];
            let target = self.current[i];

            // tactile channel, if present, is authoritative
            let touched =
                telemetry.raw_touch.get(i).copied().unwrap_or(0) >= self.config.touch_threshold;

            let analyzer = &mut self.analyzers[i];
            analyzer.push(actual, target, self.config.jitter_window);
            let score = analyzer.contact_score(dir, &self.config);
            self.contact_scores[i] = score;

            let pos_error = (target - actual).abs();

            if touched || score >= self.config.contact_score_threshold {
                self.confirmation_counts[i] += 1;
                any_candidate = true;
                if self.confirmation_counts[i] >= self.config.confirmation_windows {
                    // confirm contact and freeze this joint at its position
                    self.joint_states[i] = GraspJointState::ContactConfirmed;
                    self.contact[i] = true;
                    self.contact_positions[i] = actual;
                    self.current[i] = actual;
                    continue;
                }
                if self.joint_states[i] != GraspJointState::ContactCandidate {
                    self.joint_states[i] = GraspJointState::ContactCandidate;
                }
            } else {
                self.confirmation_counts[i] = 0;
                self.joint_states[i] = if fine {
                    GraspJointState::ClosingFine
                } else {
                    GraspJointState::ClosingCoarse
                };
            }

            // P2/C6: local degradation — only for joints that never confirmed
            // contact. A single non-critical joint that fails to track freezes
            // instead of aborting the whole grasp.
            if pos_error > self.config.error_fail_limit {
                let moving_count = self
                    .closing_directions
                    .iter()
                    .filter(|d| **d != 0.0)
                    .count();
                let critical = i == 0 || self.count_failed() + 1 > moving_count / 2;
                if critical {
                    self.fail(FailureReason::JointStall { joint: i });
                    return;
                }
                self.failed_joints[i] = true;
                self.joint_states[i] = GraspJointState::Frozen;
                continue;
            }

            // travel-limit check: the grasp target is the close limit
            let limit = self.grasp_target[i];
            if dir * (target - limit) >= 0.0 {
                self.joint_states[i] = GraspJointState::LimitReached;
                self.current[i] = limit;
                continue;
            }

            // advance the target
            let next = (target + dir * step).clamp(0.0, 1.0);
            if dir * (next - limit) > 0.0 {
                self.current[i] = limit;
                self.joint_states[i] = GraspJointState::LimitReached;
            } else {
                self.current[i] = next;
            }
            if !fine {
                self.joint_states[i] = GraspJointState::ClosingCoarse;
            } else {
                self.joint_states[i] = GraspJointState::ClosingFine;
            }
        }

        // P1/A5 + coarse→fine transition
        if self.state == GraspState::ClosingCoarse && any_candidate {
            self.state = GraspState::ClosingFine;
            self.phase_started_at_ms = Some(now_ms);
        }

        self.check_closing_termination(now_ms);
    }

    /// Contact topology, empty-grasp and timeout checks.
    /// P0/C1: empty grasp = zero confirmed contacts while all moving joints
    /// stopped; partial contact proceeds to preload instead of failing.
    fn check_closing_termination(&mut self, now_ms: u64) {
        let confirmed = self
            .joint_states
            .iter()
            .filter(|s| **s == GraspJointState::ContactConfirmed)
            .count();
        let moving_total = self
            .closing_directions
            .iter()
            .filter(|d| **d != 0.0)
            .count();
        let stopped = self
            .joint_states
            .iter()
            .filter(|s| {
                matches!(
                    s,
                    GraspJointState::ContactConfirmed
                        | GraspJointState::LimitReached
                        | GraspJointState::Frozen
                )
            })
            .count();

        // Topology satisfied -> preload.
        let thumb_confirmed = if self.config.thumb_required {
            self.joint_states[0] == GraspJointState::ContactConfirmed
                || self.closing_directions[0] == 0.0
        } else {
            true
        };
        let finger_contacts = if self.config.thumb_required {
            confirmed.saturating_sub(
                if self.joint_states[0] == GraspJointState::ContactConfirmed {
                    1
                } else {
                    0
                },
            )
        } else {
            confirmed
        };
        if thumb_confirmed && finger_contacts >= self.config.minimum_contacts {
            self.state = GraspState::Preloading;
            self.phase_started_at_ms = Some(now_ms);
            self.preload_steps_taken = 0;
            return;
        }

        if stopped >= moving_total && moving_total > 0 {
            if confirmed == 0 {
                self.fail(FailureReason::EmptyGrasp);
                return;
            }
            // Partial contact: try to secure via preload; verification in
            // Holding will still catch instability.
            self.state = GraspState::Preloading;
            self.phase_started_at_ms = Some(now_ms);
            self.preload_steps_taken = 0;
            return;
        }
        let _ = now_ms;
    }

    /// P2/C2: preload applies a small offset to confirmed joints only while
    /// the actual position still follows. A joint that no longer follows is
    /// frozen (it is already pressed). When nothing can be advanced, move to
    /// holding verification.
    fn preloading_step(&mut self, now_ms: u64) {
        if self.preload_steps_taken >= self.config.preload_max_steps {
            self.state = GraspState::Holding;
            self.phase_started_at_ms = Some(now_ms);
            return;
        }
        let mut advanced_any = false;
        for i in 0..self.profile.joint_count() {
            let dir = self.closing_directions[i];
            if dir == 0.0 || self.joint_states[i] != GraspJointState::ContactConfirmed {
                continue;
            }
            if i == 0 {
                continue; // thumb is the opposing surface, no preload (v1)
            }
            let target = self.current[i];
            let next = (target + dir * self.config.preload_step_limit).clamp(0.0, 1.0);
            // position-follow check: if the motor already stopped advancing,
            // the object is fully pressed — freeze instead of pushing harder.
            if (next - target).abs() < 1e-9 {
                continue;
            }
            self.current[i] = next;
            advanced_any = true;
        }
        self.preload_steps_taken += 1;
        if !advanced_any {
            self.state = GraspState::Holding;
            self.phase_started_at_ms = Some(now_ms);
        }
    }

    fn release_step(&mut self) {
        // two-phase release (P2/C7): quick unlock then full opening at the
        // configured step; the command vector drives the hardware.
        move_towards(
            &mut self.current,
            &self.approach_target,
            self.config.step_limit,
        );
        self.contact.fill(false);
        self.contact_scores.fill(0.0);
        self.joint_states.fill(GraspJointState::Idle);
        self.failed_joints.fill(false);
        self.confirmation_counts.fill(0);
    }

    // ── helpers ──

    fn derive_directions(&self, targets: &[f64], current: &[f64]) -> Vec<f64> {
        targets
            .iter()
            .zip(current)
            .map(|(t, c)| {
                let delta = t - c;
                if delta.abs() <= 1e-6 {
                    0.0
                } else if delta > 0.0 {
                    1.0
                } else {
                    -1.0
                }
            })
            .collect()
    }
    fn count_failed(&self) -> usize {
        self.failed_joints.iter().filter(|f| **f).count()
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

/// Percentile (linear interpolation) of a sorted slice.
fn percentile(sorted: &[f64], p: f64) -> f64 {
    if sorted.is_empty() {
        return 0.0;
    }
    if sorted.len() == 1 {
        return sorted[0];
    }
    let rank = p * (sorted.len() - 1) as f64;
    let lo = rank.floor() as usize;
    let hi = rank.ceil() as usize;
    let frac = rank - lo as f64;
    sorted[lo] + (sorted[hi] - sorted[lo]) * frac
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
            tactile_available: false,
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
    fn presets_carry_distinct_parameters() {
        let soft = GraspConfig::for_preset(GraspPreset::Soft);
        let cube = GraspConfig::for_preset(GraspPreset::Cube);
        let precision = GraspConfig::for_preset(GraspPreset::Precision);
        assert!(soft.contact_score_threshold < cube.contact_score_threshold);
        assert!(cube.contact_score_threshold < precision.contact_score_threshold);
        assert!(cube.preload_max_steps > soft.preload_max_steps);
        assert_eq!(precision.minimum_contacts, 1);
        assert_eq!(GraspPreset::from_id("soft"), Some(GraspPreset::Soft));
        assert_eq!(GraspPreset::from_id("bogus"), None);
    }

    #[test]
    fn percentile_ignores_outliers() {
        let mut data: Vec<f64> = (0..100).map(|i| i as f64).collect();
        data.push(500.0); // outlier
        let p95 = percentile(&data, 0.95);
        assert!(p95 < 100.0, "p95 should ignore the outlier, got {p95}");
    }

    #[test]
    fn empty_grasp_fails_when_zero_contact() {
        let mut machine = GraspMachine::new(Profile::O6).with_config(GraspConfig {
            allow_degraded_without_tactile: true,
            ..GraspConfig::default()
        });
        machine.calibrate().unwrap();
        machine.calibration_complete().unwrap();
        machine.grasp(&[0.1; 6]).unwrap();
        // no-load run: the hand follows every command all the way to the
        // closed limit with no load signal -> zero contact -> empty grasp
        let mut t = telemetry(6);
        let mut positions = vec![0.8; 6]; // open pose start
        for step in 1..=40 {
            t.positions = positions.clone();
            if let Some(out) = machine.tick(step * 50, &t).unwrap() {
                positions = out.command.positions;
            }
            if machine.state() == &GraspState::Failed {
                assert_eq!(machine.failure(), Some(&FailureReason::EmptyGrasp));
                return;
            }
        }
        panic!(
            "expected empty-grasp failure, state was {:?}",
            machine.state()
        );
    }

    #[test]
    fn partial_contact_proceeds_to_preload_and_hold() {
        let mut machine = GraspMachine::new(Profile::O6).with_config(GraspConfig {
            allow_degraded_without_tactile: true,
            confirmation_windows: 1,
            minimum_contacts: 1,
            thumb_required: false,
            ..GraspConfig::default()
        });
        machine.calibrate().unwrap();
        machine.calibration_complete().unwrap();
        machine.grasp(&[0.1; 6]).unwrap();
        // joints 2,3 stall at 0.5 (touch an object), the rest follow commands
        let mut t = telemetry(6);
        let mut positions = vec![0.8; 6];
        let mut reached_hold = false;
        for step in 1..=80 {
            t.positions = positions.clone();
            // once the command closes past 0.5, joints 2,3 stop following
            if positions[2] <= 0.5 {
                t.positions[2] = 0.5;
                t.positions[3] = 0.5;
            }
            if let Some(out) = machine.tick(step * 50, &t).unwrap() {
                positions = out.command.positions;
            }
            if machine.state() == &GraspState::Holding {
                reached_hold = true;
                break;
            }
            if machine.state() == &GraspState::Failed {
                panic!("unexpected failure: {:?}", machine.failure());
            }
        }
        assert!(
            reached_hold,
            "expected to reach Holding, got {:?}",
            machine.state()
        );
    }

    #[test]
    fn fixed_rate_output_contact_hold_and_degraded_mode() {
        let mut machine = GraspMachine::new(Profile::O6).with_config(GraspConfig {
            allow_degraded_without_tactile: true,
            confirmation_windows: 1,
            ..GraspConfig::default()
        });
        machine.calibrate().unwrap();
        machine.calibration_complete().unwrap();
        machine.start_approach(0, &[0.5; 6], &[0.9; 6]).unwrap();
        let mut t = telemetry(6);
        t.tactile_available = false;
        let first = machine.tick(50, &t).unwrap().unwrap();
        assert!(first.degraded);
        // settle through the approach pose
        let mut positions = first.command.positions.clone();
        for step in 2..=16 {
            t.positions = positions.clone();
            if let Some(out) = machine.tick(step * 50, &t).unwrap() {
                positions = out.command.positions;
            }
            if machine.state() != &GraspState::Approaching {
                break;
            }
        }
        // the approach must HOLD (not auto-close); closing only begins when
        // the operator explicitly completes the approach
        assert_eq!(*machine.state(), GraspState::Approaching);
        machine.approach_complete().unwrap();
        // force contact via the tactile channel
        t.tactile_available = true;
        t.raw_touch = vec![20; 6];
        t.positions = positions.clone();
        let next = machine.tick(17 * 50, &t).unwrap().unwrap();
        assert_eq!(next.contact, vec![true; 6]);
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

    #[test]
    fn overcurrent_stops_with_joint_explanation() {
        let mut machine = GraspMachine::new(Profile::O6);
        machine.calibrate().unwrap();
        machine.calibration_complete().unwrap();
        machine.grasp(&[0.5; 6]).unwrap();
        let mut sample = telemetry(6);
        sample.raw_current[3] = 250;
        assert_eq!(
            machine.tick(50, &sample),
            Err(GraspError::Failed(FailureReason::OverCurrent { joint: 3 }))
        );
        assert_eq!(
            machine.failure_message(),
            Some("检测到过流，动作已停止以保护设备。")
        );
    }

    #[test]
    fn calibration_computes_per_joint_thresholds() {
        let mut machine = GraspMachine::new(Profile::O6).with_config(GraspConfig {
            allow_degraded_without_tactile: true,
            ..GraspConfig::default()
        });
        machine.start_calibration(0).unwrap();
        // simulate sweep: joint 0 noisy, others quiet (follow the command)
        let mut t = telemetry(6);
        let mut positions = vec![0.5; 6];
        let mut ready = false;
        // two-phase sweep (fingers then thumb) needs up to ~60 ticks
        for step in 1..=120 {
            t.positions = positions.clone();
            t.positions[0] += (step % 5) as f64 * 0.01; // jittery joint
            if let Some(out) = machine.tick(step * 50, &t).unwrap() {
                positions = out.command.positions;
            }
            if machine.state() == &GraspState::Ready {
                ready = true;
                break;
            }
        }
        assert!(
            ready,
            "calibration should finish by itself, got {:?}",
            machine.state()
        );
        let thresholds: Vec<f64> = machine
            .calibration
            .iter()
            .map(|c| c.as_ref().map(|c| c.error_threshold).unwrap_or(0.0))
            .collect();
        assert!(
            thresholds[0] > thresholds[1],
            "noisy joint should get a higher threshold: {thresholds:?}"
        );
    }

    #[test]
    fn calibration_sweeps_fingers_before_thumb() {
        // Issue fix: the thumb and the fingers must never move on the same
        // tick during the no-load sweep (they would otherwise "fight").
        let mut machine = GraspMachine::new(Profile::O6).with_config(GraspConfig {
            allow_degraded_without_tactile: true,
            ..GraspConfig::default()
        });
        machine.start_calibration(0).unwrap();
        let mut t = telemetry(6);
        let mut positions = vec![0.5; 6];
        let mut prev = positions.clone();
        let mut saw_thumb_move = false;
        let mut fingers_done_before_thumb = false;
        for step in 1..=120 {
            t.positions = positions.clone();
            let Some(out) = machine.tick(step * 50, &t).unwrap() else {
                break;
            };
            positions = out.command.positions;
            if machine.state() == &GraspState::Ready {
                break;
            }
            let thumb_changed = positions[0] != prev[0] || positions[1] != prev[1];
            let finger_changed = positions[2] != prev[2]
                || positions[3] != prev[3]
                || positions[4] != prev[4]
                || positions[5] != prev[5];
            if thumb_changed && !saw_thumb_move {
                saw_thumb_move = true;
                fingers_done_before_thumb = !finger_changed;
            }
            // no tick may move thumb AND fingers together
            assert!(
                !(thumb_changed && finger_changed),
                "thumb and fingers must not move on the same tick (step {step})"
            );
            prev = positions.clone();
        }
        assert!(saw_thumb_move, "thumb joints should eventually move");
        assert!(
            fingers_done_before_thumb,
            "fingers should finish sweeping before the thumb starts"
        );
    }

    #[test]
    fn approach_holds_until_explicit_start() {
        let mut machine = GraspMachine::new(Profile::O6).with_config(GraspConfig {
            allow_degraded_without_tactile: true,
            ..GraspConfig::default()
        });
        machine.calibrate().unwrap();
        machine.calibration_complete().unwrap();
        machine.start_approach(0, &[0.8; 6], &[0.1; 6]).unwrap();
        let mut t = telemetry(6);
        let mut positions = vec![0.8; 6];
        // run well past the settle window — the machine must stay in
        // Approaching and never auto-transition to ClosingCoarse
        for step in 1..=40 {
            t.positions = positions.clone();
            if let Some(out) = machine.tick(step * 50, &t).unwrap() {
                positions = out.command.positions;
            }
            assert_eq!(
                *machine.state(),
                GraspState::Approaching,
                "approach must hold, got {:?} at step {step}",
                machine.state()
            );
        }
        // only an explicit start transitions to closing
        machine.approach_complete().unwrap();
        assert_eq!(*machine.state(), GraspState::ClosingCoarse);
    }

    #[test]
    fn failed_grasp_can_be_reset_and_recalibrated() {
        let mut machine = GraspMachine::new(Profile::O6).with_config(GraspConfig {
            allow_degraded_without_tactile: true,
            ..GraspConfig::default()
        });
        machine.calibrate().unwrap();
        machine.calibration_complete().unwrap();
        machine.grasp(&[0.1; 6]).unwrap();
        let mut t = telemetry(6);
        let mut positions = vec![0.8; 6];
        let mut failed = false;
        for step in 1..=40 {
            t.positions = positions.clone();
            if let Some(out) = machine.tick(step * 50, &t).unwrap() {
                positions = out.command.positions;
            }
            if machine.state() == &GraspState::Failed {
                failed = true;
                break;
            }
        }
        assert!(failed, "expected an empty-grasp failure");
        // the operator can recover: start_calibration must accept Failed
        assert!(machine.calibrate().is_ok());
        assert_eq!(*machine.state(), GraspState::Calibrating);
        machine.calibration_complete().unwrap();
        assert_eq!(*machine.state(), GraspState::Ready);
    }

    #[test]
    fn release_recovers_after_failure() {
        let mut machine = GraspMachine::new(Profile::O6).with_config(GraspConfig {
            allow_degraded_without_tactile: true,
            ..GraspConfig::default()
        });
        machine.calibrate().unwrap();
        machine.calibration_complete().unwrap();
        machine.grasp(&[0.1; 6]).unwrap();
        let mut t = telemetry(6);
        let mut positions = vec![0.8; 6];
        let mut failed = false;
        for step in 1..=40 {
            t.positions = positions.clone();
            if let Some(out) = machine.tick(step * 50, &t).unwrap() {
                positions = out.command.positions;
            }
            if machine.state() == &GraspState::Failed {
                failed = true;
                break;
            }
        }
        assert!(failed, "expected an empty-grasp failure");
        // emergency open after a failure must be allowed and reach Ready
        assert!(machine.release().is_ok());
        assert_eq!(*machine.state(), GraspState::Releasing);
        for step in 41..=160 {
            t.positions = positions.clone();
            if let Some(out) = machine.tick(step * 50, &t).unwrap() {
                positions = out.command.positions;
            }
            if machine.state() == &GraspState::Ready {
                break;
            }
        }
        assert_eq!(
            *machine.state(),
            GraspState::Ready,
            "release after failure should return to Ready"
        );
        assert_eq!(machine.failure(), None, "release clears the failure banner");
    }
}
