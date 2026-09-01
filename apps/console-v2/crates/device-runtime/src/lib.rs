//! Connection state machine and adapter lifecycle management.
use console_contracts::{
    AppError, ConnectionSnapshot, ConnectionState, DeviceCapabilities, DeviceConfig,
    JointTargetCommand, TelemetrySnapshot,
};
use device_adapter_api::{AdapterError, DeviceAdapter};
use thiserror::Error;

fn vector(length: usize, available: bool) -> console_contracts::VectorCapability {
    console_contracts::VectorCapability {
        length: length as u16,
        available,
        range: console_contracts::RawRange {
            min: console_contracts::RAW_MIN,
            max: console_contracts::RAW_MAX,
        },
    }
}

/// Return the model's offline capability declaration without touching the
/// adapter.  This keeps the workspace readable before an operator explicitly
/// connects a device; a successful connect replaces it with the adapter's
/// authoritative capabilities.
pub fn offline_capabilities(config: &DeviceConfig) -> DeviceCapabilities {
    use console_contracts::{DeviceModel, SidecarOperation};
    let (joints, position, speed, current, touch, speed_command, current_command, torque_command) =
        match config.model {
            DeviceModel::O6 | DeviceModel::L6 => (6, 6, 6, 6, 6, 6, None, Some(6)),
            DeviceModel::L7 => (7, 7, 7, 7, 7, 7, None, Some(7)),
            DeviceModel::L10 => (10, 10, 10, 10, 10, 10, None, Some(10)),
            DeviceModel::L20 => (20, 20, 20, 5, 20, 5, Some(5), None),
            DeviceModel::G20 => (20, 20, 20, 20, 20, 5, None, Some(5)),
            DeviceModel::L21 | DeviceModel::L25 => (25, 25, 25, 21, 25, 25, None, Some(5)),
        };
    let mut supported_operations = vec![
        SidecarOperation::Connect,
        SidecarOperation::Disconnect,
        SidecarOperation::Capabilities,
        SidecarOperation::GetTelemetry,
        SidecarOperation::GetPosition,
        SidecarOperation::GetCurrent,
        SidecarOperation::GetSpeed,
        SidecarOperation::GetTouch,
        SidecarOperation::SetPosition,
        SidecarOperation::SetSpeed,
        SidecarOperation::Stop,
        SidecarOperation::Unlock,
        SidecarOperation::Close,
    ];
    if current_command.is_some() {
        supported_operations.push(SidecarOperation::SetCurrent);
    }
    if torque_command.is_some() {
        supported_operations.push(SidecarOperation::SetTorque);
    }
    DeviceCapabilities {
        schema_version: console_contracts::CURRENT_SCHEMA_VERSION,
        device_id: config.device_id.clone(),
        model: config.model.clone(),
        hand: config.hand.clone(),
        transport: config.transport.clone(),
        joint_count: joints,
        position: vector(position, true),
        speed: vector(speed, true),
        current: vector(current, true),
        torque: vector(torque_command.unwrap_or(0), torque_command.is_some()),
        touch: vector(touch, true),
        speed_command_length: speed_command,
        current_command_length: current_command,
        torque_command_length: torque_command.map(|value| value as u16),
        supported_operations,
    }
}
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
        let capabilities = offline_capabilities(&config);
        Self {
            config,
            state: ConnectionState::Disconnected,
            attempt: 0,
            last_error: None,
            capabilities: Some(capabilities),
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
        let Some(a) = self.adapter.as_mut() else {
            self.state = ConnectionState::Error;
            self.last_error = Some(RuntimeError::NoAdapter.to_string());
            return Err(RuntimeError::NoAdapter);
        };
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
        Ok(())
    }
    pub fn capabilities(&self) -> Option<&DeviceCapabilities> {
        self.capabilities.as_ref()
    }
    /// A send/read against a dropped transport surfaces the real state: if the
    /// adapter reports NotConnected the runtime must stop claiming "connected"
    /// so the UI disables motion controls and the operator can reconnect.
    /// Without this, every later joint target keeps failing with
    /// "adapter: not connected" while the UI still shows 已连接.
    fn mark_disconnected_if_adapter_says_so(&mut self, error: &RuntimeError) {
        if matches!(error, RuntimeError::Adapter(AdapterError::NotConnected)) {
            self.state = ConnectionState::Disconnected;
            self.last_error = Some(error.to_string());
        }
    }
    pub fn send(&mut self, c: &JointTargetCommand) -> Result<(), RuntimeError> {
        let result = self
            .adapter
            .as_mut()
            .ok_or(RuntimeError::NoAdapter)?
            .send_joint_target(c)
            .map_err(Into::into);
        if let Err(error) = &result {
            self.mark_disconnected_if_adapter_says_so(error);
        }
        result
    }
    pub fn set_speed(&mut self, values: &[u8]) -> Result<(), RuntimeError> {
        let result = self
            .adapter
            .as_mut()
            .ok_or(RuntimeError::NoAdapter)?
            .set_speed(values)
            .map_err(Into::into);
        if let Err(error) = &result {
            self.mark_disconnected_if_adapter_says_so(error);
        }
        result
    }
    pub fn set_torque(&mut self, values: &[u8]) -> Result<(), RuntimeError> {
        let result = self
            .adapter
            .as_mut()
            .ok_or(RuntimeError::NoAdapter)?
            .set_torque(values)
            .map_err(Into::into);
        if let Err(error) = &result {
            self.mark_disconnected_if_adapter_says_so(error);
        }
        result
    }
    pub fn telemetry(&mut self, now: u64) -> Result<TelemetrySnapshot, RuntimeError> {
        let result = self
            .adapter
            .as_mut()
            .ok_or(RuntimeError::NoAdapter)?
            .read_telemetry(now)
            .map_err(Into::into);
        if let Err(error) = &result {
            self.mark_disconnected_if_adapter_says_so(error);
        }
        result
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
    use device_adapter_api::AdapterResult;
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

    #[test]
    fn offline_capabilities_do_not_connect_or_require_an_adapter() {
        let runtime = DeviceRuntime::new(DeviceConfig::new("offline", "offline"));
        assert_eq!(*runtime.state(), ConnectionState::Disconnected);
        assert_eq!(runtime.capabilities().unwrap().joint_count, 6);
    }

    #[test]
    fn explicit_connect_is_the_only_operation_that_requires_hardware() {
        let mut runtime = DeviceRuntime::new(DeviceConfig::new("offline", "offline"));
        assert!(matches!(runtime.connect(), Err(RuntimeError::NoAdapter)));
        assert_eq!(*runtime.state(), ConnectionState::Error);
    }

    #[test]
    fn offline_matrix_matches_raw_capability_snapshot_for_every_model() {
        use console_contracts::DeviceModel;
        let expected = [
            (DeviceModel::O6, 6, 6, 6, 6, 6, None, Some(6)),
            (DeviceModel::L6, 6, 6, 6, 6, 6, None, Some(6)),
            (DeviceModel::L7, 7, 7, 7, 7, 7, None, Some(7)),
            (DeviceModel::L10, 10, 10, 10, 10, 10, None, Some(10)),
            (DeviceModel::L20, 20, 20, 5, 20, 5, Some(5), None),
            (DeviceModel::G20, 20, 20, 20, 20, 5, None, Some(5)),
            (DeviceModel::L21, 25, 25, 21, 25, 25, None, Some(5)),
            (DeviceModel::L25, 25, 25, 21, 25, 25, None, Some(5)),
        ];
        for (model, position, speed, current, touch, speed_command, current_command, torque) in
            expected
        {
            let mut config = DeviceConfig::new("offline", "offline");
            config.model = model;
            let actual = offline_capabilities(&config);
            assert_eq!(actual.position.length as usize, position);
            assert_eq!(actual.speed.length as usize, speed);
            assert_eq!(actual.current.length as usize, current);
            assert_eq!(actual.touch.length as usize, touch);
            assert_eq!(actual.speed_command_length as usize, speed_command);
            assert_eq!(
                actual.current_command_length.map(usize::from),
                current_command
            );
            assert_eq!(actual.torque_command_length.map(usize::from), torque);
        }
    }

    /// Adapter whose transport "drops" after connect: sends/reads report
    /// NotConnected while the runtime would otherwise keep claiming connected.
    struct DroppingAdapter(DeviceSimulator, bool);
    impl DeviceAdapter for DroppingAdapter {
        fn id(&self) -> &str {
            "dropping"
        }
        fn connect(&mut self) -> AdapterResult<DeviceCapabilities> {
            self.0.connect()
        }
        fn disconnect(&mut self) -> AdapterResult<()> {
            self.0.disconnect()
        }
        fn is_connected(&self) -> bool {
            self.0.is_connected()
        }
        fn capabilities(&self) -> Option<&DeviceCapabilities> {
            self.0.capabilities()
        }
        fn send_joint_target(&mut self, _command: &JointTargetCommand) -> AdapterResult<()> {
            if self.1 {
                Err(AdapterError::NotConnected)
            } else {
                Ok(())
            }
        }
        fn read_telemetry(&mut self, monotonic_time_ms: u64) -> AdapterResult<TelemetrySnapshot> {
            if self.1 {
                Err(AdapterError::NotConnected)
            } else {
                self.0.read_telemetry(monotonic_time_ms)
            }
        }
    }

    #[test]
    fn not_connected_on_send_drops_the_runtime_to_disconnected() {
        use console_contracts::{JointTargetCommand, CURRENT_SCHEMA_VERSION};
        let mut runtime = DeviceRuntime::new(DeviceConfig::new("s", "sim"));
        runtime.install_adapter(Box::new(DroppingAdapter(
            DeviceSimulator::new("s", 2),
            false,
        )));
        runtime.connect().unwrap();
        assert_eq!(*runtime.state(), ConnectionState::Connected);
        // transport drops -> next send fails and the runtime must stop
        // reporting connected so the UI disables motion and shows 未连接
        runtime.adapter = Some(Box::new(DroppingAdapter(
            DeviceSimulator::new("s", 2),
            true,
        )));
        let command = JointTargetCommand {
            schema_version: CURRENT_SCHEMA_VERSION,
            command_id: "drop-me".into(),
            source: console_contracts::CommandSource::Manual,
            positions: vec![0.5; 2],
            duration_ms: None,
            final_command: false,
        };
        assert!(runtime.send(&command).is_err());
        assert_eq!(*runtime.state(), ConnectionState::Disconnected);
        assert!(runtime.last_error.is_some());
    }
}
