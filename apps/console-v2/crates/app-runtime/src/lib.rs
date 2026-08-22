//! Application coordinator. Dependencies are explicit typed ports, not a global event bus.
use action_engine::ActionEngine;
use adaptive_grasp::{GraspMachine, Profile};
use console_contracts::{DeviceConfig, JointTargetCommand, TelemetrySnapshot};
use device_adapter_api::DeviceAdapter;
use device_runtime::{DeviceRuntime, RuntimeError};
use motion_engine::{MotionEngine, MotionError};
use telemetry::TelemetryStore;
use thiserror::Error;

pub trait VisionPort: Send {
    fn cancel(&mut self);
}
pub trait SidecarPort: Send {
    fn cancel_requests(&mut self);
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
        self.telemetry.publish_status(t.clone());
        self.telemetry.publish_frame(t.clone());
        Ok(t)
    }
    pub fn stop_all(&mut self) {
        self.motion.stop_all();
        if let Some(v) = self.vision.as_mut() {
            v.cancel();
        }
        if let Some(s) = self.sidecar.as_mut() {
            s.cancel_requests();
        }
    }
}
