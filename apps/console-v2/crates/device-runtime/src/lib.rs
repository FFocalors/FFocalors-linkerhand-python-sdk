//! Connection state machine and adapter lifecycle management.
use console_contracts::{
    AppError, ConnectionSnapshot, ConnectionState, DeviceCapabilities, DeviceConfig,
    JointTargetCommand, TelemetrySnapshot,
};
use device_adapter_api::{AdapterError, DeviceAdapter};
use thiserror::Error;
#[derive(Debug, Error)]
pub enum RuntimeError {
    #[error("adapter: {0}")]
    Adapter(#[from] AdapterError),
    #[error("no adapter installed")]
    NoAdapter,
}
pub struct DeviceRuntime {
    config: DeviceConfig,
    state: ConnectionState,
    attempt: u32,
    last_error: Option<String>,
    capabilities: Option<DeviceCapabilities>,
    adapter: Option<Box<dyn DeviceAdapter>>,
}
impl DeviceRuntime {
    pub fn new(config: DeviceConfig) -> Self {
        Self {
            config,
            state: ConnectionState::Disconnected,
            attempt: 0,
            last_error: None,
            capabilities: None,
            adapter: None,
        }
    }
    pub fn install_adapter(&mut self, a: Box<dyn DeviceAdapter>) {
        self.adapter = Some(a);
    }
    pub fn state(&self) -> &ConnectionState {
        &self.state
    }
    pub fn config(&self) -> &DeviceConfig {
        &self.config
    }
    pub fn snapshot(&self) -> ConnectionSnapshot {
        ConnectionSnapshot {
            schema_version: 1,
            device_id: self.config.device_id.clone(),
            state: self.state.clone(),
            attempt: self.attempt,
            last_error: self.last_error.as_ref().map(|message| AppError {
                code: "DEVICE_ERROR".into(),
                message: message.clone(),
                retryable: true,
                details: None,
            }),
        }
    }
    pub fn connect(&mut self) -> Result<(), RuntimeError> {
        self.state = ConnectionState::Connecting;
        self.attempt += 1;
        let a = self.adapter.as_mut().ok_or(RuntimeError::NoAdapter)?;
        match a.connect() {
            Ok(c) => {
                self.capabilities = Some(c);
                self.state = ConnectionState::Connected;
                self.last_error = None;
                Ok(())
            }
            Err(e) => {
                self.state = ConnectionState::Error;
                self.last_error = Some(e.to_string());
                Err(e.into())
            }
        }
    }
    pub fn reconnect(&mut self) -> Result<(), RuntimeError> {
        self.state = ConnectionState::Reconnecting;
        self.connect()
    }
    pub fn disconnect(&mut self) -> Result<(), RuntimeError> {
        if let Some(a) = self.adapter.as_mut() {
            a.disconnect()?;
        }
        self.state = ConnectionState::Disconnected;
        self.capabilities = None;
        Ok(())
    }
    pub fn capabilities(&self) -> Option<&DeviceCapabilities> {
        self.capabilities.as_ref()
    }
    pub fn send(&mut self, c: &JointTargetCommand) -> Result<(), RuntimeError> {
        self.adapter
            .as_mut()
            .ok_or(RuntimeError::NoAdapter)?
            .send_joint_target(c)
            .map_err(Into::into)
    }
    pub fn telemetry(&mut self, now: u64) -> Result<TelemetrySnapshot, RuntimeError> {
        self.adapter
            .as_mut()
            .ok_or(RuntimeError::NoAdapter)?
            .read_telemetry(now)
            .map_err(Into::into)
    }
    pub fn stop(&mut self) -> Result<(), RuntimeError> {
        self.adapter
            .as_mut()
            .ok_or(RuntimeError::NoAdapter)?
            .stop()
            .map_err(Into::into)
    }
    pub fn unlock(&mut self) -> Result<(), RuntimeError> {
        self.adapter
            .as_mut()
            .ok_or(RuntimeError::NoAdapter)?
            .unlock()
            .map_err(Into::into)
    }
    pub fn shutdown(&mut self) -> Result<(), RuntimeError> {
        self.adapter
            .as_mut()
            .ok_or(RuntimeError::NoAdapter)?
            .shutdown()
            .map_err(Into::into)
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    use device_simulator::DeviceSimulator;
    #[test]
    fn lifecycle_and_reconnect() {
        let mut r = DeviceRuntime::new(DeviceConfig::new("s", "sim"));
        r.install_adapter(Box::new(DeviceSimulator::new("s", 2)));
        assert_eq!(*r.state(), ConnectionState::Disconnected);
        r.connect().unwrap();
        assert!(r.capabilities().is_some());
        r.disconnect().unwrap();
        assert_eq!(*r.state(), ConnectionState::Disconnected);
        r.reconnect().unwrap();
        assert_eq!(*r.state(), ConnectionState::Connected);
    }
}
