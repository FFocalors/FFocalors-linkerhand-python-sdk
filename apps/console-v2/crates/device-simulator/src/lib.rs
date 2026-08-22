//! Deterministic adapter for tests and demos, with explicit fault injection.
use console_contracts::*;
use device_adapter_api::{AdapterError, AdapterResult, DeviceAdapter};

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Fault {
    Connect,
    Send,
    Telemetry,
    Disconnect,
}

pub struct DeviceSimulator {
    id: String,
    connected: bool,
    joints: Vec<f64>,
    capabilities: DeviceCapabilities,
    sequence: u64,
    faults: Vec<Fault>,
    pub commands: Vec<JointTargetCommand>,
}
impl DeviceSimulator {
    pub fn new(id: impl Into<String>, joint_count: usize) -> Self {
        Self {
            id: id.into(),
            connected: false,
            joints: vec![0.0; joint_count],
            capabilities: DeviceCapabilities {
                schema_version: CURRENT_SCHEMA_VERSION,
                joint_count: joint_count as u8,
                supports_force_feedback: true,
                supports_vision: true,
                supported_profiles: ["O6", "L6", "L7", "L10", "L20"]
                    .into_iter()
                    .map(String::from)
                    .collect(),
            },
            sequence: 0,
            faults: vec![],
            commands: vec![],
        }
    }
    pub fn inject_fault(&mut self, fault: Fault) {
        if !self.faults.contains(&fault) {
            self.faults.push(fault);
        }
    }
    pub fn clear_faults(&mut self) {
        self.faults.clear();
    }
    fn take_fault(&mut self, fault: Fault) -> bool {
        self.faults
            .iter()
            .position(|f| *f == fault)
            .map(|i| {
                self.faults.remove(i);
                true
            })
            .unwrap_or(false)
    }
}
impl DeviceAdapter for DeviceSimulator {
    fn id(&self) -> &str {
        &self.id
    }
    fn connect(&mut self) -> AdapterResult<DeviceCapabilities> {
        if self.take_fault(Fault::Connect) {
            return Err(AdapterError::Transport("injected connect failure".into()));
        }
        self.connected = true;
        Ok(self.capabilities.clone())
    }
    fn disconnect(&mut self) -> AdapterResult<()> {
        if self.take_fault(Fault::Disconnect) {
            return Err(AdapterError::Transport(
                "injected disconnect failure".into(),
            ));
        }
        self.connected = false;
        Ok(())
    }
    fn is_connected(&self) -> bool {
        self.connected
    }
    fn capabilities(&self) -> Option<&DeviceCapabilities> {
        self.connected.then_some(&self.capabilities)
    }
    fn send_joint_target(&mut self, command: &JointTargetCommand) -> AdapterResult<()> {
        if !self.connected {
            return Err(AdapterError::NotConnected);
        }
        if self.take_fault(Fault::Send) {
            return Err(AdapterError::DeviceFault("injected send failure".into()));
        }
        if command.joints.len() != self.joints.len() {
            return Err(AdapterError::InvalidCommand("joint count mismatch".into()));
        }
        self.joints.clone_from(&command.joints);
        self.commands.push(command.clone());
        Ok(())
    }
    fn read_telemetry(&mut self, monotonic_time_ms: u64) -> AdapterResult<TelemetrySnapshot> {
        if !self.connected {
            return Err(AdapterError::NotConnected);
        }
        if self.take_fault(Fault::Telemetry) {
            return Err(AdapterError::Transport("injected telemetry failure".into()));
        }
        self.sequence += 1;
        Ok(TelemetrySnapshot {
            schema_version: CURRENT_SCHEMA_VERSION,
            device_id: self.id.clone(),
            sequence: self.sequence,
            monotonic_ms: monotonic_time_ms,
            joints: self.joints.clone(),
            forces: vec![0.0; self.joints.len()],
            connected: true,
        })
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    use device_adapter_api::DeviceAdapter;
    #[test]
    fn deterministic_and_faults() {
        let mut d = DeviceSimulator::new("sim", 2);
        assert!(d.connect().is_ok());
        let c = JointTargetCommand {
            schema_version: 1,
            command_id: "1".into(),
            source: CommandSource::Manual,
            joints: vec![1., 2.],
            duration_ms: None,
            final_command: false,
        };
        d.send_joint_target(&c).unwrap();
        assert_eq!(d.read_telemetry(4).unwrap().joints, vec![1., 2.]);
        d.inject_fault(Fault::Send);
        assert!(d.send_joint_target(&c).is_err());
    }
}
