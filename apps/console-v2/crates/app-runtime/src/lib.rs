//! Application coordinator. Dependencies are explicit typed ports, not a global event bus.
use action_engine::ActionEngine;
use adaptive_grasp::{GraspMachine, Profile};
use console_contracts::{
    ActionRecording, ConnectionSnapshot, DeviceCapabilities, DeviceConfig, GraspPreset,
    JointTargetCommand, OperationSnapshot, TelemetrySnapshot, VisionPoseProposal,
};
use device_adapter_api::DeviceAdapter;
use device_runtime::{DeviceRuntime, RuntimeError};
use motion_engine::{MotionEngine, MotionError};
use structured_logging::LogStore;
use telemetry::TelemetryStore;
use thiserror::Error;

pub trait VisionPort: Send {
    fn cancel(&mut self);
}
pub trait SidecarPort: Send {
    fn stop(&mut self);
    fn unlock(&mut self);
    fn cancel_pending(&mut self);
}

/// UI-facing facade contracts. These methods deliberately use the same DTOs
/// projected to TypeScript; the sidecar port remains an internal dependency.
pub mod ui {
    use super::*;
    pub trait DevicePort {
        fn get_config(&self) -> DeviceConfig;
        fn get_capabilities(&self) -> Option<DeviceCapabilities>;
        fn get_connection(&self) -> ConnectionSnapshot;
        fn set_joint_target(
            &mut self,
            command: JointTargetCommand,
            now_ms: u64,
        ) -> Result<(), AppRuntimeError>;
        fn stop_all(&mut self);
        fn unlock(&mut self);
        fn set_speed(&mut self, values: Vec<f64>, now_ms: u64) -> Result<(), AppRuntimeError>;
        fn set_torque(&mut self, values: Vec<f64>, now_ms: u64) -> Result<(), AppRuntimeError>;
    }
    pub trait MotionPort {
        fn get_operation(&self) -> OperationSnapshot;
        fn run_action(&mut self, id: &str) -> Result<(), AppRuntimeError>;
        fn pause(&mut self) -> Result<(), AppRuntimeError>;
    }
    pub trait TelemetryPort {
        fn read(&self) -> Option<TelemetrySnapshot>;
        fn subscribe(&self, every_n_frames: usize) -> Vec<TelemetrySnapshot>;
    }
    pub trait ActionPort {
        fn list(&self) -> Vec<ActionRecording>;
        fn delete(&mut self, id: &str) -> Result<(), AppRuntimeError>;
    }
    pub trait GraspPort {
        fn list_presets(&self) -> Vec<GraspPreset>;
        fn run_preset(&mut self, id: &str) -> Result<(), AppRuntimeError>;
    }
    pub trait VisionPort {
        fn propose(&self, source: &str) -> Vec<VisionPoseProposal>;
        fn sync(&mut self, proposal: VisionPoseProposal) -> Result<(), AppRuntimeError>;
    }
    pub trait LogPort {
        fn list(&self, limit: usize) -> Vec<console_contracts::StructuredLogEntry>;
    }
}
pub trait DevicePort {
    type Error;
    fn connect(&mut self) -> Result<(), Self::Error>;
    fn disconnect(&mut self) -> Result<(), Self::Error>;
}
pub trait MotionPort {
    type Error;
    fn submit(&mut self, command: JointTargetCommand) -> Result<(), Self::Error>;
    fn stop_all(&mut self);
}
pub trait TelemetryPort {
    fn publish_status(&mut self, value: TelemetrySnapshot);
    fn publish_frame(&mut self, value: TelemetrySnapshot);
}
pub trait ActionPort {
    fn cancel(&mut self);
}
pub trait GraspPort {
    fn abort(&mut self);
}
pub trait LogPort {
    fn log(&mut self, entry: console_contracts::StructuredLogEntry);
}
impl DevicePort for DeviceRuntime {
    type Error = RuntimeError;
    fn connect(&mut self) -> Result<(), Self::Error> {
        DeviceRuntime::connect(self)
    }
    fn disconnect(&mut self) -> Result<(), Self::Error> {
        DeviceRuntime::disconnect(self)
    }
}
impl MotionPort for MotionEngine {
    type Error = MotionError;
    fn submit(&mut self, command: JointTargetCommand) -> Result<(), Self::Error> {
        MotionEngine::submit(self, command)
    }
    fn stop_all(&mut self) {
        MotionEngine::stop_all(self);
    }
}
impl TelemetryPort for TelemetryStore {
    fn publish_status(&mut self, value: TelemetrySnapshot) {
        TelemetryStore::publish_status(self, value);
    }
    fn publish_frame(&mut self, value: TelemetrySnapshot) {
        TelemetryStore::publish_frame(self, value);
    }
}
impl ActionPort for ActionEngine {
    fn cancel(&mut self) {
        ActionEngine::cancel(self);
    }
}
impl GraspPort for GraspMachine {
    fn abort(&mut self) {
        GraspMachine::abort(self);
    }
}
impl LogPort for LogStore {
    fn log(&mut self, entry: console_contracts::StructuredLogEntry) {
        LogStore::push(self, entry);
    }
}
#[derive(Debug, Error)]
pub enum AppRuntimeError {
    #[error("device: {0}")]
    Device(#[from] RuntimeError),
    #[error("motion: {0}")]
    Motion(#[from] MotionError),
    #[error("unsupported: {0}")]
    Unsupported(String),
}
pub struct AppRuntime {
    pub device: DeviceRuntime,
    pub motion: MotionEngine,
    pub telemetry: TelemetryStore,
    pub actions: ActionEngine,
    pub grasp: GraspMachine,
    pub logs: LogStore,
    saved_actions: Vec<ActionRecording>,
    vision: Option<Box<dyn VisionPort>>,
    sidecar: Option<Box<dyn SidecarPort>>,
}
impl AppRuntime {
    pub fn new(config: DeviceConfig, profile: Profile) -> Self {
        let mut actions = ActionEngine::new();
        let _ = actions.install_builtin_presets(profile.model(), profile.joint_count());
        Self {
            device: DeviceRuntime::new(config),
            motion: MotionEngine::new(),
            telemetry: TelemetryStore::new(64, 256),
            actions,
            grasp: GraspMachine::new(profile),
            logs: LogStore::new(1024),
            saved_actions: Vec::new(),
            vision: None,
            sidecar: None,
        }
    }
    pub fn install_adapter(&mut self, a: Box<dyn DeviceAdapter>) {
        self.device.install_adapter(a);
    }
    pub fn install_vision(&mut self, p: Box<dyn VisionPort>) {
        self.vision = Some(p);
    }
    pub fn install_sidecar(&mut self, p: Box<dyn SidecarPort>) {
        self.sidecar = Some(p);
    }
    pub fn connect(&mut self) -> Result<(), AppRuntimeError> {
        self.device.connect().map_err(Into::into)
    }
    pub fn submit_motion(
        &mut self,
        c: JointTargetCommand,
        now_ms: u64,
    ) -> Result<Option<JointTargetCommand>, AppRuntimeError> {
        self.motion.submit(c)?;
        Ok(self.motion.tick(now_ms))
    }
    pub fn sample_telemetry(&mut self, now_ms: u64) -> Result<TelemetrySnapshot, AppRuntimeError> {
        let t = self
            .device
            .telemetry(now_ms)
            .map_err(AppRuntimeError::Device)?;
        TelemetryPort::publish_status(&mut self.telemetry, t.clone());
        TelemetryPort::publish_frame(&mut self.telemetry, t.clone());
        Ok(t)
    }
    pub fn set_speed(&mut self, values: Vec<f64>) -> Result<(), AppRuntimeError> {
        let expected = self
            .device
            .capabilities()
            .ok_or_else(|| AppRuntimeError::Unsupported("device is not connected".into()))?
            .speed_command_length as usize;
        let raw = console_contracts::normalized_to_raw(&values, expected)
            .map_err(AppRuntimeError::Unsupported)?;
        self.device.set_speed(&raw).map_err(AppRuntimeError::Device)
    }
    pub fn set_torque(&mut self, values: Vec<f64>) -> Result<(), AppRuntimeError> {
        let expected = self
            .device
            .capabilities()
            .and_then(|c| c.torque_command_length)
            .ok_or_else(|| AppRuntimeError::Unsupported("torque is not available".into()))?
            as usize;
        let raw = console_contracts::normalized_to_raw(&values, expected)
            .map_err(AppRuntimeError::Unsupported)?;
        self.device.set_torque(&raw).map_err(AppRuntimeError::Device)
    }
    pub fn action_start_recording(&mut self, id: String, name: String, now_ms: u64) {
        self.actions.start_recording_at(id, name, now_ms);
    }
    pub fn action_record_command(&mut self, command: JointTargetCommand, now_ms: u64) -> Result<(), AppRuntimeError> {
        self.actions.record_at(now_ms, command).map_err(|e| AppRuntimeError::Unsupported(e.to_string()))
    }
    pub fn action_finish_recording(&mut self) -> Result<ActionRecording, AppRuntimeError> {
        let recording = self.actions.finish_recording().map_err(|e| AppRuntimeError::Unsupported(e.to_string()))?;
        self.saved_actions.retain(|item| item.id != recording.id);
        self.saved_actions.push(recording.clone());
        Ok(recording)
    }
    pub fn action_list(&self) -> Vec<ActionRecording> {
        self.actions.list().into_iter().chain(self.saved_actions.clone()).collect()
    }
    pub fn action_play(&mut self, id: &str, speed: f32, loop_count: Option<u32>, now_ms: u64) -> Result<(), AppRuntimeError> {
        let recording = self.action_list().into_iter().find(|item| item.id == id)
            .ok_or_else(|| AppRuntimeError::Unsupported(format!("action {id} not found")))?;
        self.actions.set_loop(loop_count.is_some(), loop_count);
        self.actions.play_at(recording, now_ms).map_err(|e| AppRuntimeError::Unsupported(e.to_string()))?;
        self.actions.set_speed(speed).map_err(|e| AppRuntimeError::Unsupported(e.to_string()))
    }
    pub fn action_delete(&mut self, id: &str) -> Result<(), AppRuntimeError> {
        let before = self.saved_actions.len();
        self.saved_actions.retain(|item| item.id != id);
        if self.actions.unregister_preset(id) || before != self.saved_actions.len() { Ok(()) } else { Err(AppRuntimeError::Unsupported(format!("action {id} not found"))) }
    }
    pub fn action_tick(&mut self, now_ms: u64) -> Option<JointTargetCommand> { self.actions.tick(now_ms) }
    pub fn action_stop(&mut self) {
        self.actions.cancel();
        self.motion.cancel_source(console_contracts::CommandSource::Playback);
        self.motion.cancel_source(console_contracts::CommandSource::Loop);
    }
    pub fn grasp_calibrate(&mut self, now_ms: u64) -> Result<(), AppRuntimeError> {
        self.grasp.start_calibration(now_ms).map_err(|e| AppRuntimeError::Unsupported(e.to_string()))
    }
    pub fn grasp_complete_calibration(&mut self) -> Result<(), AppRuntimeError> { self.grasp.calibration_complete().map_err(|e| AppRuntimeError::Unsupported(e.to_string())) }
    pub fn grasp_start_approach(&mut self, now_ms: u64) -> Result<(), AppRuntimeError> {
        let current = self.telemetry.latest().map(|t| t.positions.clone()).unwrap_or_else(|| vec![0.5; self.grasp.profile().joint_count()]);
        let target = vec![0.8; self.grasp.profile().joint_count()];
        self.grasp.start_approach(now_ms, &current, &target).map_err(|e| AppRuntimeError::Unsupported(e.to_string()))
    }
    pub fn grasp_start(&mut self, degraded: bool, _now_ms: u64) -> Result<(), AppRuntimeError> {
        let config = adaptive_grasp::GraspConfig { allow_degraded_without_tactile: degraded, ..adaptive_grasp::GraspConfig::default() };
        self.grasp.set_config(config);
        self.grasp.approach_complete().map_err(|e| AppRuntimeError::Unsupported(e.to_string()))
    }
    pub fn grasp_release(&mut self) -> Result<(), AppRuntimeError> { self.grasp.release().map_err(|e| AppRuntimeError::Unsupported(e.to_string())) }
    pub fn grasp_tick(&mut self, now_ms: u64) -> Result<Option<JointTargetCommand>, AppRuntimeError> {
        let Some(t) = self.telemetry.latest() else { return Ok(None) };
        let sample = adaptive_grasp::GraspTelemetry { connected: t.connected, tactile_available: !t.raw_touch.is_empty(), raw_touch: t.raw_touch.clone(), raw_current: t.raw_current.clone(), positions: t.positions.clone() };
        Ok(self.grasp.tick(now_ms, &sample).map_err(|e| AppRuntimeError::Unsupported(e.to_string()))?.map(|o| o.command))
    }
    pub fn stop_all(&mut self) {
        MotionPort::stop_all(&mut self.motion);
        ActionPort::cancel(&mut self.actions);
        GraspPort::abort(&mut self.grasp);
        if let Some(v) = self.vision.as_mut() {
            v.cancel();
        }
        if let Some(s) = self.sidecar.as_mut() {
            s.stop();
            s.cancel_pending();
        }
        let _ = self.device.stop();
    }
    pub fn unlock(&mut self) {
        self.motion.unlock();
        let _ = self.device.unlock();
        if let Some(s) = self.sidecar.as_mut() {
            s.unlock();
        }
    }
    pub fn shutdown(&mut self) {
        let _ = self.device.shutdown();
    }
}

impl ui::DevicePort for AppRuntime {
    fn get_config(&self) -> DeviceConfig {
        self.device.config().clone()
    }
    fn get_capabilities(&self) -> Option<DeviceCapabilities> {
        self.device.capabilities().cloned()
    }
    fn get_connection(&self) -> ConnectionSnapshot {
        self.device.snapshot()
    }
    fn set_joint_target(
        &mut self,
        command: JointTargetCommand,
        now_ms: u64,
    ) -> Result<(), AppRuntimeError> {
        if let Some(committed) = self.submit_motion(command, now_ms)? {
            self.device.send(&committed)?;
        }
        Ok(())
    }
    fn stop_all(&mut self) {
        AppRuntime::stop_all(self);
    }
    fn unlock(&mut self) {
        AppRuntime::unlock(self);
    }
    fn set_speed(&mut self, values: Vec<f64>, _now_ms: u64) -> Result<(), AppRuntimeError> { self.set_speed(values) }
    fn set_torque(&mut self, values: Vec<f64>, _now_ms: u64) -> Result<(), AppRuntimeError> { self.set_torque(values) }
}

impl ui::MotionPort for AppRuntime {
    fn get_operation(&self) -> OperationSnapshot {
        let state = if self.motion.is_locked() {
            console_contracts::OperationState::Locked
        } else if self.motion.active_source().is_some() {
            console_contracts::OperationState::Running
        } else {
            console_contracts::OperationState::Idle
        };
        OperationSnapshot {
            schema_version: console_contracts::CURRENT_SCHEMA_VERSION,
            operation_id: "motion".into(),
            kind: "motion".into(),
            state,
            progress: 0.0,
            detail: None,
        }
    }
    fn run_action(&mut self, _id: &str) -> Result<(), AppRuntimeError> {
        self.action_play(_id, 1.0, None, 0)
    }
    fn pause(&mut self) -> Result<(), AppRuntimeError> {
        Err(AppRuntimeError::Unsupported(
            "pause is not part of the motion contract".into(),
        ))
    }
}

impl ui::TelemetryPort for AppRuntime {
    fn read(&self) -> Option<TelemetrySnapshot> {
        self.telemetry.latest().cloned()
    }
    fn subscribe(&self, every_n_frames: usize) -> Vec<TelemetrySnapshot> {
        self.telemetry
            .subscribe_frames(&telemetry::TelemetrySubscription::new(every_n_frames))
            .into_iter()
            .cloned()
            .collect()
    }
}

impl ui::ActionPort for AppRuntime {
    fn list(&self) -> Vec<ActionRecording> {
        self.action_list()
    }
    fn delete(&mut self, id: &str) -> Result<(), AppRuntimeError> { self.action_delete(id) }
}

impl ui::GraspPort for AppRuntime {
    fn list_presets(&self) -> Vec<GraspPreset> {
        vec![
            GraspPreset { id: "soft".into(), name: "柔软物体".into(), description: "低力度包络抓取".into() },
            GraspPreset { id: "cube".into(), name: "方形物体".into(), description: "稳定的平行夹持".into() },
            GraspPreset { id: "precision".into(), name: "精细拾取".into(), description: "指尖精确定位".into() },
        ]
    }
    fn run_preset(&mut self, _id: &str) -> Result<(), AppRuntimeError> {
        if self.grasp.is_available() { Ok(()) } else { Err(AppRuntimeError::Unsupported("该型号暂不支持智能自适应抓取。".into())) }
    }
}

impl ui::VisionPort for AppRuntime {
    fn propose(&self, _source: &str) -> Vec<VisionPoseProposal> {
        Vec::new()
    }
    fn sync(&mut self, proposal: VisionPoseProposal) -> Result<(), AppRuntimeError> {
        let command = JointTargetCommand {
            schema_version: console_contracts::CURRENT_SCHEMA_VERSION,
            command_id: proposal.id,
            source: console_contracts::CommandSource::Vision,
            positions: proposal.positions,
            duration_ms: None,
            final_command: true,
        };
        ui::DevicePort::set_joint_target(self, command, 0)
    }
}

impl ui::LogPort for AppRuntime {
    fn list(&self, limit: usize) -> Vec<console_contracts::StructuredLogEntry> {
        self.logs.page(None, limit, None).entries
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use console_contracts::{CommandSource, CURRENT_SCHEMA_VERSION};
    use device_simulator::DeviceSimulator;
    use std::sync::{Arc, Mutex};

    struct FakeVision(Arc<Mutex<u32>>);
    impl VisionPort for FakeVision {
        fn cancel(&mut self) {
            *self.0.lock().unwrap() += 1;
        }
    }
    struct FakeSidecar(Arc<Mutex<u32>>);
    impl SidecarPort for FakeSidecar {
        fn stop(&mut self) {
            *self.0.lock().unwrap() += 1;
        }
        fn unlock(&mut self) {
            *self.0.lock().unwrap() += 1;
        }
        fn cancel_pending(&mut self) {
            *self.0.lock().unwrap() += 1;
        }
    }
    fn command(source: CommandSource) -> JointTargetCommand {
        JointTargetCommand {
            schema_version: CURRENT_SCHEMA_VERSION,
            command_id: "stop-me".into(),
            source,
            positions: vec![0.0; 6],
            duration_ms: None,
            final_command: false,
        }
    }
    #[test]
    fn stop_all_cancels_each_software_operation_and_locks() {
        let vision_count = Arc::new(Mutex::new(0));
        let sidecar_count = Arc::new(Mutex::new(0));
        let mut runtime = AppRuntime::new(DeviceConfig::new("sim", "sim"), Profile::O6);
        runtime.install_vision(Box::new(FakeVision(vision_count.clone())));
        runtime.install_sidecar(Box::new(FakeSidecar(sidecar_count.clone())));
        runtime.install_adapter(Box::new(DeviceSimulator::new("sim", 6)));
        runtime.connect().unwrap();
        runtime.actions.start_recording("a", "a");
        runtime
            .actions
            .record(command(CommandSource::Playback))
            .unwrap();
        let recording = runtime.actions.finish_recording().unwrap();
        runtime.actions.play(recording).unwrap();
        runtime.grasp.calibrate().unwrap();
        runtime.grasp.calibration_complete().unwrap();
        runtime.grasp.grasp(&[0.0; 6]).unwrap();
        runtime.grasp.grasp_complete().unwrap();
        runtime
            .motion
            .submit(command(CommandSource::Vision))
            .unwrap();
        runtime.stop_all();
        assert_eq!(*vision_count.lock().unwrap(), 1);
        assert_eq!(*sidecar_count.lock().unwrap(), 2);
        assert_eq!(
            *runtime.actions.state(),
            action_engine::PlaybackState::Cancelled
        );
        assert_eq!(*runtime.grasp.state(), adaptive_grasp::GraspState::Aborted);
        assert!(runtime.motion.is_locked());
        assert!(!runtime.motion.has_pending());
        for source in [
            CommandSource::Vision,
            CommandSource::RockPaperScissors,
            CommandSource::Playback,
            CommandSource::Loop,
            CommandSource::Grasp,
        ] {
            assert!(runtime.motion.cancelled_sources().contains(&source));
        }
        runtime.unlock();
        assert!(!runtime.motion.is_locked());
    }
}
