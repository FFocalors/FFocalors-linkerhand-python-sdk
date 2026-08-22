//! Stable wire contracts shared by the console runtime and adapters.
use serde::{Deserialize, Serialize};
use std::fmt;

pub const CURRENT_SCHEMA_VERSION: u16 = 1;

fn schema_version() -> u16 {
    CURRENT_SCHEMA_VERSION
}

/// The only cross-process envelope. Payloads remain typed by each protocol.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct WireEnvelope<T> {
    #[serde(default = "schema_version")]
    pub schema_version: u16,
    pub message_type: String,
    pub request_id: String,
    pub sequence: u64,
    pub monotonic_time_ms: u64,
    #[serde(default)]
    pub operation: Option<String>,
    pub payload: T,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct DeviceConfig {
    #[serde(default = "schema_version")]
    pub schema_version: u16,
    pub device_id: String,
    pub name: String,
    #[serde(default = "default_host")]
    pub host: String,
    #[serde(default = "default_port")]
    pub port: u16,
    #[serde(default)]
    pub auto_reconnect: bool,
}
fn default_host() -> String {
    "127.0.0.1".into()
}
fn default_port() -> u16 {
    5000
}
impl DeviceConfig {
    pub fn new(device_id: impl Into<String>, name: impl Into<String>) -> Self {
        Self {
            schema_version: CURRENT_SCHEMA_VERSION,
            device_id: device_id.into(),
            name: name.into(),
            host: default_host(),
            port: default_port(),
            auto_reconnect: true,
        }
    }
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct DeviceCapabilities {
    #[serde(default = "schema_version")]
    pub schema_version: u16,
    pub joint_count: u8,
    #[serde(default)]
    pub supports_force_feedback: bool,
    #[serde(default)]
    pub supports_vision: bool,
    #[serde(default)]
    pub supported_profiles: Vec<String>,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct ConnectionSnapshot {
    #[serde(default = "schema_version")]
    pub schema_version: u16,
    pub device_id: String,
    pub state: ConnectionState,
    pub attempt: u32,
    pub last_error: Option<String>,
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub enum ConnectionState {
    Disconnected,
    Connecting,
    Connected,
    Reconnecting,
    Faulted,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct JointTargetCommand {
    #[serde(default = "schema_version")]
    pub schema_version: u16,
    pub command_id: String,
    pub source: CommandSource,
    pub joints: Vec<f64>,
    #[serde(default)]
    pub duration_ms: Option<u64>,
    #[serde(default)]
    pub final_command: bool,
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub enum CommandSource {
    Manual,
    Preset,
    Playback,
    Loop,
    Vision,
    RockPaperScissors,
    Grasp,
    Safety,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct TelemetrySnapshot {
    #[serde(default = "schema_version")]
    pub schema_version: u16,
    pub device_id: String,
    pub sequence: u64,
    pub monotonic_ms: u64,
    pub joints: Vec<f64>,
    #[serde(default)]
    pub forces: Vec<f64>,
    pub connected: bool,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub enum OperationState {
    Idle,
    Running,
    Stopping,
    Completed,
    Cancelled,
    Faulted,
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct OperationSnapshot {
    #[serde(default = "schema_version")]
    pub schema_version: u16,
    pub operation_id: String,
    pub kind: String,
    pub state: OperationState,
    pub progress: f32,
    #[serde(default)]
    pub detail: Option<String>,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct StructuredLogEntry {
    #[serde(default = "schema_version")]
    pub schema_version: u16,
    pub sequence: u64,
    pub monotonic_ms: u64,
    pub level: LogLevel,
    pub event: String,
    pub message: String,
    #[serde(default)]
    pub fields: serde_json::Value,
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq, PartialOrd, Ord)]
#[serde(rename_all = "lowercase")]
pub enum LogLevel {
    Trace,
    Debug,
    Info,
    Warn,
    Error,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq, thiserror::Error)]
#[serde(rename_all = "camelCase")]
pub enum AppError {
    #[error("invalid request: {message}")]
    InvalidRequest { message: String },
    #[error("device unavailable: {message}")]
    DeviceUnavailable { message: String },
    #[error("operation cancelled")]
    Cancelled,
    #[error("timeout after {timeout_ms} ms")]
    Timeout {
        #[serde(rename = "timeoutMs")]
        timeout_ms: u64,
    },
    #[error("protocol error: {message}")]
    Protocol { message: String },
    #[error("internal error: {message}")]
    Internal { message: String },
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct ActionRecording {
    #[serde(default = "schema_version")]
    pub schema_version: u16,
    pub action_id: String,
    pub name: String,
    pub frames: Vec<JointTargetCommand>,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct VisionPoseProposal {
    #[serde(default = "schema_version")]
    pub schema_version: u16,
    pub proposal_id: String,
    pub confidence: f32,
    pub joints: Vec<f64>,
    #[serde(default)]
    pub expires_at_monotonic_ms: Option<u64>,
}

impl fmt::Display for ConnectionState {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{:?}", self)
    }
}

pub fn to_wire<T: Serialize>(value: &T) -> Result<String, serde_json::Error> {
    serde_json::to_string(value)
}
pub fn from_wire<T: for<'de> Deserialize<'de>>(value: &str) -> Result<T, serde_json::Error> {
    serde_json::from_str(value)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn wire_is_camel_case_and_versioned() {
        let c = DeviceConfig::new("d1", "Desk hand");
        let json = to_wire(&c).unwrap();
        assert!(json.contains("deviceId") && json.contains("schemaVersion"));
        assert!(!json.contains("device_id"));
        assert_eq!(from_wire::<DeviceConfig>(&json).unwrap(), c);
    }
    #[test]
    fn snapshot_round_trip() {
        let s = TelemetrySnapshot {
            schema_version: CURRENT_SCHEMA_VERSION,
            device_id: "d".into(),
            sequence: 3,
            monotonic_ms: 9,
            joints: vec![1.0],
            forces: vec![],
            connected: true,
        };
        assert_eq!(
            from_wire::<TelemetrySnapshot>(&to_wire(&s).unwrap()).unwrap(),
            s
        );
    }
    #[test]
    fn envelope_snapshot_has_stable_transport_fields() {
        let e = WireEnvelope {
            schema_version: CURRENT_SCHEMA_VERSION,
            message_type: "telemetry.snapshot".into(),
            request_id: "r1".into(),
            sequence: 8,
            monotonic_time_ms: 42,
            operation: Some("sample".into()),
            payload: serde_json::json!({"ok":true}),
        };
        let json = to_wire(&e).unwrap();
        for field in [
            "schemaVersion",
            "messageType",
            "requestId",
            "monotonicTimeMs",
            "operation",
            "payload",
        ] {
            assert!(json.contains(field), "missing {field}");
        }
        assert!(!json.contains("monotonic_time_ms"));
    }
}
