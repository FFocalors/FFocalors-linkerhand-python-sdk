//! Replaceable hardware boundary. No runtime or transport assumptions leak out.
use console_contracts::{DeviceCapabilities, JointTargetCommand, TelemetrySnapshot};
use thiserror::Error;

#[derive(Debug, Error, Clone, PartialEq, Eq)]
pub enum AdapterError {
    #[error("not connected")]
    NotConnected,
    #[error("transport: {0}")]
    Transport(String),
    #[error("unsupported: {0}")]
    Unsupported(String),
    #[error("invalid command: {0}")]
    InvalidCommand(String),
    #[error("device fault: {0}")]
    DeviceFault(String),
}

pub type AdapterResult<T> = Result<T, AdapterError>;

pub trait DeviceAdapter: Send {
    fn id(&self) -> &str;
    fn connect(&mut self) -> AdapterResult<DeviceCapabilities>;
    fn disconnect(&mut self) -> AdapterResult<()>;
    fn is_connected(&self) -> bool;
    fn capabilities(&self) -> Option<&DeviceCapabilities>;
    fn send_joint_target(&mut self, command: &JointTargetCommand) -> AdapterResult<()>;
    fn read_telemetry(&mut self, monotonic_time_ms: u64) -> AdapterResult<TelemetrySnapshot>;
    /// Software stop barrier. Adapters with a transport-level stop command
    /// override this; simulators keep the no-op default.
    fn stop(&mut self) -> AdapterResult<()> { Ok(()) }
    fn unlock(&mut self) -> AdapterResult<()> { Ok(()) }
}
