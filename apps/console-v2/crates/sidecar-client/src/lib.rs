//! Strict sidecar NDJSON boundary and software stop state.
use console_contracts::{
    normalized_to_raw, raw_to_normalized, AppError, DeviceCapabilities, MessageType,
    SidecarOperation, WireEnvelope, CURRENT_SCHEMA_VERSION,
};
use serde::{de::DeserializeOwned, Deserialize, Serialize};
use std::time::Duration;
use thiserror::Error;

#[derive(Debug, Error, Clone, PartialEq, Eq)]
pub enum ProtocolError {
    #[error("stdout is not valid NDJSON: {0}")]
    InvalidJson(String),
    #[error("schema version {0} is unsupported")]
    Schema(u16),
    #[error("sequence must increase: {0}")]
    Sequence(u64),
    #[error("request id is empty")]
    EmptyRequestId,
    #[error("operation is missing or invalid")]
    InvalidOperation,
    #[error("message type is invalid")]
    InvalidMessageType,
    #[error("error payload is invalid")]
    InvalidErrorPayload,
    #[error("raw vector is invalid: {0}")]
    InvalidVector(String),
    #[error("stdout contamination")]
    StdoutContamination,
}

pub struct NdjsonFramer;
impl NdjsonFramer {
    pub fn encode<T: Serialize>(message: &WireEnvelope<T>) -> Result<String, serde_json::Error> {
        let mut line = serde_json::to_string(message)?;
        line.push('\n');
        Ok(line)
    }
    pub fn decode<T: DeserializeOwned>(line: &str) -> Result<WireEnvelope<T>, ProtocolError> {
        if line.trim().is_empty() {
            return Err(ProtocolError::InvalidJson("empty line".into()));
        }
        let msg = serde_json::from_str::<WireEnvelope<T>>(line.trim())
            .map_err(|e| ProtocolError::InvalidJson(e.to_string()))?;
        if msg.schema_version != CURRENT_SCHEMA_VERSION {
            return Err(ProtocolError::Schema(msg.schema_version));
        }
        if msg.request_id.is_empty() {
            return Err(ProtocolError::EmptyRequestId);
        }
        if !matches!(
            msg.message_type,
            MessageType::Request
                | MessageType::Command
                | MessageType::Response
                | MessageType::Event
                | MessageType::Error
        ) {
            return Err(ProtocolError::InvalidMessageType);
        }
        Ok(msg)
    }
    pub fn decode_error(line: &str) -> Result<WireEnvelope<ErrorPayload>, ProtocolError> {
        let msg = Self::decode::<ErrorPayload>(line)?;
        if msg.message_type != MessageType::Error {
            return Err(ProtocolError::InvalidErrorPayload);
        }
        if msg.payload.error.code.is_empty() || msg.payload.error.message.is_empty() {
            return Err(ProtocolError::InvalidErrorPayload);
        }
        Ok(msg)
    }
}

/// Adapter seam between normalized public positions and sidecar raw bytes.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RawVectorMapper {
    pub position_length: usize,
}
impl RawVectorMapper {
    pub fn from_capabilities(capabilities: &DeviceCapabilities) -> Self {
        Self {
            position_length: capabilities.position.length as usize,
        }
    }
    pub fn encode_positions(&self, positions: &[f64]) -> Result<Vec<u8>, ProtocolError> {
        normalized_to_raw(positions, self.position_length).map_err(ProtocolError::InvalidVector)
    }
    pub fn decode_positions(&self, raw: &[u8]) -> Result<Vec<f64>, ProtocolError> {
        if raw.len() != self.position_length {
            return Err(ProtocolError::InvalidVector(format!(
                "expected {} raw positions, got {}",
                self.position_length,
                raw.len()
            )));
        }
        Ok(raw_to_normalized(raw))
    }
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct ErrorPayload {
    pub error: AppError,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum SidecarState {
    NotStarted,
    Running,
    TimedOut,
    Crashed,
    Stopped,
}

#[derive(Clone, Debug)]
pub struct SidecarConfig {
    pub startup_timeout: Duration,
    pub request_timeout: Duration,
}
impl Default for SidecarConfig {
    fn default() -> Self {
        Self {
            startup_timeout: Duration::from_secs(5),
            request_timeout: Duration::from_secs(10),
        }
    }
}

#[derive(Clone, Debug)]
pub struct SidecarSession {
    pub config: SidecarConfig,
    pub state: SidecarState,
    last_sequence: u64,
    write_locked: bool,
}
impl SidecarSession {
    pub fn new(config: SidecarConfig) -> Self {
        Self {
            config,
            state: SidecarState::NotStarted,
            last_sequence: 0,
            write_locked: false,
        }
    }
    pub fn started(&mut self) {
        self.state = SidecarState::Running;
        self.write_locked = false;
    }
    pub fn timeout(&mut self) {
        self.state = SidecarState::TimedOut;
    }
    pub fn crashed(&mut self) {
        self.state = SidecarState::Crashed;
    }
    pub fn stop(&mut self) {
        self.write_locked = true;
    }
    pub fn unlock(&mut self) {
        self.write_locked = false;
    }
    pub fn is_write_locked(&self) -> bool {
        self.write_locked
    }
    pub fn close(&mut self) {
        self.state = SidecarState::Stopped;
    }
    pub fn ingest<T: DeserializeOwned>(
        &mut self,
        line: &str,
    ) -> Result<WireEnvelope<T>, ProtocolError> {
        let msg = NdjsonFramer::decode(line)?;
        if msg.sequence <= self.last_sequence {
            return Err(ProtocolError::Sequence(msg.sequence));
        }
        self.last_sequence = msg.sequence;
        if msg.operation == SidecarOperation::Stop {
            self.stop();
        }
        if msg.operation == SidecarOperation::Unlock {
            self.unlock();
        }
        if msg.operation == SidecarOperation::Close {
            self.close();
        }
        Ok(msg)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn msg(seq: u64, operation: SidecarOperation) -> WireEnvelope<serde_json::Value> {
        WireEnvelope {
            schema_version: 1,
            message_type: MessageType::Response,
            request_id: "r1".into(),
            sequence: seq,
            monotonic_time_ms: 4,
            operation,
            payload: serde_json::json!({"ok":true}),
        }
    }
    #[test]
    fn framing_is_one_line_camel_case() {
        let s = NdjsonFramer::encode(&msg(1, SidecarOperation::GetTelemetry)).unwrap();
        assert_eq!(s.matches('\n').count(), 1);
        assert!(
            s.contains("messageType") && s.contains("requestId") && s.contains("monotonicTimeMs")
        );
        assert!(NdjsonFramer::decode::<serde_json::Value>(&s).is_ok());
    }
    #[test]
    fn rejects_bad_order_schema_and_contamination() {
        let mut s = SidecarSession::new(Default::default());
        s.started();
        assert!(s
            .ingest::<serde_json::Value>(
                &NdjsonFramer::encode(&msg(1, SidecarOperation::GetTelemetry)).unwrap()
            )
            .is_ok());
        assert!(matches!(
            s.ingest::<serde_json::Value>(
                &NdjsonFramer::encode(&msg(1, SidecarOperation::GetTelemetry)).unwrap()
            ),
            Err(ProtocolError::Sequence(_))
        ));
        assert!(matches!(
            NdjsonFramer::decode::<serde_json::Value>("diagnostic noise"),
            Err(ProtocolError::InvalidJson(_))
        ));
        let mut bad = msg(2, SidecarOperation::GetTelemetry);
        bad.schema_version = 99;
        assert!(matches!(
            NdjsonFramer::decode::<serde_json::Value>(&NdjsonFramer::encode(&bad).unwrap()),
            Err(ProtocolError::Schema(99))
        ));
    }
    #[test]
    fn stop_and_unlock_are_explicit_software_state() {
        let mut s = SidecarSession::new(Default::default());
        s.started();
        s.stop();
        assert!(s.is_write_locked());
        s.unlock();
        assert!(!s.is_write_locked());
        s.close();
        assert_eq!(s.state, SidecarState::Stopped);
    }
    #[test]
    fn raw_mapper_round_trips_capability_length_and_edges() {
        let capabilities = DeviceCapabilities {
            schema_version: 1,
            device_id: "d".into(),
            model: console_contracts::DeviceModel::O6,
            hand: console_contracts::Hand::Left,
            transport: console_contracts::Transport::Can {
                channel: "fake".into(),
            },
            joint_count: 2,
            position: console_contracts::VectorCapability {
                length: 2,
                available: true,
                range: console_contracts::RawRange { min: 0, max: 255 },
            },
            speed: console_contracts::VectorCapability {
                length: 2,
                available: true,
                range: console_contracts::RawRange { min: 0, max: 255 },
            },
            current: console_contracts::VectorCapability {
                length: 2,
                available: true,
                range: console_contracts::RawRange { min: 0, max: 255 },
            },
            torque: console_contracts::VectorCapability {
                length: 2,
                available: true,
                range: console_contracts::RawRange { min: 0, max: 255 },
            },
            touch: console_contracts::VectorCapability {
                length: 2,
                available: true,
                range: console_contracts::RawRange { min: 0, max: 255 },
            },
            speed_command_length: 2,
            current_command_length: None,
            torque_command_length: Some(2),
            supported_operations: vec![],
        };
        let mapper = RawVectorMapper::from_capabilities(&capabilities);
        assert_eq!(mapper.encode_positions(&[0., 1.]).unwrap(), vec![0, 255]);
        assert_eq!(mapper.decode_positions(&[0, 255]).unwrap(), vec![0., 1.]);
        assert!(mapper.decode_positions(&[0]).is_err());
    }
}
