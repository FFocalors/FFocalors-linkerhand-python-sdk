//! Sidecar process/protocol boundary. It does not launch or assume Python.
use console_contracts::{WireEnvelope, CURRENT_SCHEMA_VERSION};
use serde::{de::DeserializeOwned, Serialize};
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
        Ok(msg)
    }
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
}
impl SidecarSession {
    pub fn new(config: SidecarConfig) -> Self {
        Self {
            config,
            state: SidecarState::NotStarted,
            last_sequence: 0,
        }
    }
    pub fn started(&mut self) {
        self.state = SidecarState::Running;
    }
    pub fn timeout(&mut self) {
        self.state = SidecarState::TimedOut;
    }
    pub fn crashed(&mut self) {
        self.state = SidecarState::Crashed;
    }
    pub fn stop(&mut self) {
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
        Ok(msg)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn msg(seq: u64) -> WireEnvelope<serde_json::Value> {
        WireEnvelope {
            schema_version: 1,
            message_type: "vision.result".into(),
            request_id: "r1".into(),
            sequence: seq,
            monotonic_time_ms: 4,
            operation: Some("vision".into()),
            payload: serde_json::json!({"ok":true}),
        }
    }
    #[test]
    fn framing_is_one_line_camel_case() {
        let s = NdjsonFramer::encode(&msg(1)).unwrap();
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
            .ingest::<serde_json::Value>(&NdjsonFramer::encode(&msg(1)).unwrap())
            .is_ok());
        assert!(matches!(
            s.ingest::<serde_json::Value>(&NdjsonFramer::encode(&msg(1)).unwrap()),
            Err(ProtocolError::Sequence(_))
        ));
        assert!(matches!(
            NdjsonFramer::decode::<serde_json::Value>("diagnostic noise"),
            Err(ProtocolError::InvalidJson(_))
        ));
        let mut bad = msg(2);
        bad.schema_version = 99;
        assert!(matches!(
            NdjsonFramer::decode::<serde_json::Value>(&NdjsonFramer::encode(&bad).unwrap()),
            Err(ProtocolError::Schema(99))
        ));
    }
}
