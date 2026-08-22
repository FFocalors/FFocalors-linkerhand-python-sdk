//! Application coordinator. Dependencies are explicit typed ports, not a global event bus.
use action_engine::ActionEngine;
use adaptive_grasp::{GraspMachine, Profile};
use console_contracts::{DeviceConfig, JointTargetCommand, TelemetrySnapshot};
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
    fn cancel_requests(&mut self);
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
}
pub struct AppRuntime {
    pub device: DeviceRuntime,
    pub motion: MotionEngine,
    pub telemetry: TelemetryStore,
    pub actions: ActionEngine,
    pub grasp: GraspMachine,
    vision: Option<Box<dyn VisionPort>>,
    sidecar: Option<Box<dyn SidecarPort>>,
}
impl AppRuntime {
    pub fn new(config: DeviceConfig, profile: Profile) -> Self {
        Self {
            device: DeviceRuntime::new(config),
            motion: MotionEngine::new(),
            telemetry: TelemetryStore::new(64, 256),
            actions: ActionEngine::new(),
            grasp: GraspMachine::new(profile),
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
    pub fn stop_all(&mut self) {
        MotionPort::stop_all(&mut self.motion);
        ActionPort::cancel(&mut self.actions);
        GraspPort::abort(&mut self.grasp);
        if let Some(v) = self.vision.as_mut() {
            v.cancel();
        }
        if let Some(s) = self.sidecar.as_mut() {
            s.cancel_requests();
        }
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
        fn cancel_requests(&mut self) {
            *self.0.lock().unwrap() += 1;
        }
    }
    fn command(source: CommandSource) -> JointTargetCommand {
        JointTargetCommand {
            schema_version: CURRENT_SCHEMA_VERSION,
            command_id: "stop-me".into(),
            source,
            joints: vec![0.0; 6],
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
        assert_eq!(*sidecar_count.lock().unwrap(), 1);
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
    }
}
