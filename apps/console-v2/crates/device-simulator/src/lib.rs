//! Deterministic adapter for tests and demos, covering every supported model.
use console_contracts::*;
use device_adapter_api::{AdapterError, AdapterResult, DeviceAdapter};

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Fault {
    Connect,
    Send,
    Telemetry,
    Disconnect,
}

fn model_lengths(
    model: &DeviceModel,
) -> (
    usize,
    usize,
    usize,
    usize,
    usize,
    Option<usize>,
    Option<usize>,
) {
    match model {
        DeviceModel::O6 | DeviceModel::L6 => (6, 6, 6, 6, 6, None, Some(6)),
        DeviceModel::L7 => (7, 7, 7, 7, 7, None, Some(7)),
        DeviceModel::L10 => (10, 10, 10, 10, 10, None, Some(10)),
        DeviceModel::L20 => (20, 20, 5, 20, 5, Some(5), None),
        DeviceModel::G20 => (20, 20, 20, 20, 5, None, Some(5)),
        DeviceModel::L21 | DeviceModel::L25 => (25, 25, 21, 25, 25, None, Some(5)),
    }
}
fn vector(length: usize, available: bool) -> VectorCapability {
    VectorCapability {
        length: length as u16,
        available,
        range: RawRange {
            min: RAW_MIN,
            max: RAW_MAX,
        },
    }
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
        Self::with_model(id, DeviceModel::O6, joint_count)
    }
    pub fn for_model(id: impl Into<String>, model: DeviceModel) -> Self {
        let count = model_lengths(&model).0;
        Self::with_model(id, model, count)
    }
    fn with_model(id: impl Into<String>, model: DeviceModel, joint_count: usize) -> Self {
        let id = id.into();
        let (position, speed, current, touch, speed_command, current_command, torque_command) =
            model_lengths(&model);
        let transport = Transport::Can {
            channel: "fake".into(),
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
        Self {
            id: id.clone(),
            connected: false,
            joints: vec![0.0; joint_count],
            capabilities: DeviceCapabilities {
                schema_version: CURRENT_SCHEMA_VERSION,
                device_id: id,
                model,
                hand: Hand::Left,
                transport,
                joint_count: joint_count as u16,
                position: vector(position, true),
                speed: vector(speed, true),
                current: vector(current, true),
                torque: vector(torque_command.unwrap_or(0), torque_command.is_some()),
                touch: vector(touch, true),
                speed_command_length: speed_command as u16,
                current_command_length: current_command.map(|v| v as u16),
                torque_command_length: torque_command.map(|v| v as u16),
                supported_operations,
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
        if command.positions.len() != self.joints.len()
            || command
                .positions
                .iter()
                .any(|v| !v.is_finite() || !(0.0..=1.0).contains(v))
        {
            return Err(AdapterError::InvalidCommand(
                "normalized position vector mismatch".into(),
            ));
        }
        self.joints.clone_from(&command.positions);
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
        let raw = normalized_to_raw(&self.joints, self.joints.len())
            .map_err(AdapterError::InvalidCommand)?;
        Ok(TelemetrySnapshot {
            schema_version: CURRENT_SCHEMA_VERSION,
            device_id: self.id.clone(),
            sequence: self.sequence,
            monotonic_time_ms,
            positions: self.joints.clone(),
            raw_position: raw,
            raw_current: vec![0; self.capabilities.current.length as usize],
            raw_speed: vec![0; self.capabilities.speed.length as usize],
            raw_touch: vec![0; self.capabilities.touch.length as usize],
            connected: true,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn deterministic_and_faults() {
        let mut d = DeviceSimulator::new("sim", 2);
        d.connect().unwrap();
        let c = JointTargetCommand {
            schema_version: 1,
            command_id: "1".into(),
            source: CommandSource::Manual,
            positions: vec![0.1, 0.2],
            duration_ms: None,
            final_command: false,
        };
        d.send_joint_target(&c).unwrap();
        assert_eq!(d.read_telemetry(4).unwrap().positions, vec![0.1, 0.2]);
        d.inject_fault(Fault::Send);
        assert!(d.send_joint_target(&c).is_err());
    }
    #[test]
    fn all_models_have_their_raw_lengths() {
        for model in [
            DeviceModel::O6,
            DeviceModel::L6,
            DeviceModel::L7,
            DeviceModel::L10,
            DeviceModel::L20,
            DeviceModel::G20,
            DeviceModel::L21,
            DeviceModel::L25,
        ] {
            let mut d = DeviceSimulator::for_model("sim", model);
            let c = d.connect().unwrap();
            assert_eq!(c.joint_count as usize, c.position.length as usize);
        }
    }
}
