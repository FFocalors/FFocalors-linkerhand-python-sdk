//! Canonical LinkerHand Console V2 public contract.
//!
//! Rust is the source of truth for the domain DTOs. `cargo run -p
//! console-contracts --bin generate-contracts` emits the checked-in TypeScript
//! projection used by the UI. The sidecar keeps raw byte vectors at this
//! boundary; all public position values are normalized to `0.0..=1.0`.
use serde::{Deserialize, Serialize};
use std::fmt;

pub const CURRENT_SCHEMA_VERSION: u16 = 1;
pub const RAW_MIN: u8 = 0;
pub const RAW_MAX: u8 = 255;

fn schema_version() -> u16 {
    CURRENT_SCHEMA_VERSION
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "UPPERCASE")]
pub enum DeviceModel {
    O6,
    L6,
    L7,
    L10,
    L20,
    G20,
    L21,
    L25,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum Hand {
    Left,
    Right,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(tag = "type", rename_all = "camelCase")]
pub enum Transport {
    Can { channel: String },
    Rs485 { port: String, baudrate: u32 },
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct DeviceConfig {
    #[serde(default = "schema_version")]
    pub schema_version: u16,
    pub device_id: String,
    pub name: String,
    pub model: DeviceModel,
    pub hand: Hand,
    pub transport: Transport,
    #[serde(default)]
    pub auto_reconnect: bool,
}

impl DeviceConfig {
    pub fn new(device_id: impl Into<String>, name: impl Into<String>) -> Self {
        Self {
            schema_version: CURRENT_SCHEMA_VERSION,
            device_id: device_id.into(),
            name: name.into(),
            model: DeviceModel::O6,
            hand: Hand::Left,
            transport: Transport::Can {
                channel: "fake".into(),
            },
            auto_reconnect: true,
        }
    }
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct RawRange {
    pub min: u8,
    pub max: u8,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct VectorCapability {
    pub length: u16,
    pub available: bool,
    pub range: RawRange,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct DeviceCapabilities {
    #[serde(default = "schema_version")]
    pub schema_version: u16,
    pub device_id: String,
    pub model: DeviceModel,
    pub hand: Hand,
    pub transport: Transport,
    pub joint_count: u16,
    pub position: VectorCapability,
    pub speed: VectorCapability,
    pub current: VectorCapability,
    pub torque: VectorCapability,
    pub touch: VectorCapability,
    pub speed_command_length: u16,
    pub current_command_length: Option<u16>,
    pub torque_command_length: Option<u16>,
    pub supported_operations: Vec<SidecarOperation>,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct ConnectionSnapshot {
    #[serde(default = "schema_version")]
    pub schema_version: u16,
    pub device_id: String,
    pub state: ConnectionState,
    pub attempt: u32,
    pub last_error: Option<AppError>,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub enum ConnectionState {
    Disconnected,
    Connecting,
    Connected,
    Reconnecting,
    Error,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct JointTargetCommand {
    #[serde(default = "schema_version")]
    pub schema_version: u16,
    pub command_id: String,
    pub source: CommandSource,
    /// Complete joint vector in normalized `0.0..=1.0` position units.
    pub positions: Vec<f64>,
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
    pub monotonic_time_ms: u64,
    pub positions: Vec<f64>,
    pub raw_position: Vec<u8>,
    pub raw_current: Vec<u8>,
    pub raw_speed: Vec<u8>,
    pub raw_touch: Vec<u8>,
    pub connected: bool,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub enum OperationState {
    Idle,
    Running,
    Stopping,
    Locked,
    Paused,
    Completed,
    Cancelled,
    Error,
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
    pub id: String,
    pub monotonic_time_ms: u64,
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

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct AppError {
    pub code: String,
    pub message: String,
    pub retryable: bool,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub details: Option<serde_json::Value>,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct ActionRecording {
    #[serde(default = "schema_version")]
    pub schema_version: u16,
    pub id: String,
    pub name: String,
    pub frames: Vec<JointTargetCommand>,
    pub duration_ms: u64,
    pub steps: u32,
    pub updated_at: String,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct VisionPoseProposal {
    #[serde(default = "schema_version")]
    pub schema_version: u16,
    pub id: String,
    pub label: String,
    pub confidence: f32,
    pub positions: Vec<f64>,
    #[serde(default)]
    pub expires_at_monotonic_ms: Option<u64>,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct GraspPreset {
    pub id: String,
    pub name: String,
    pub description: String,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub enum SidecarOperation {
    Connect,
    Disconnect,
    Capabilities,
    GetTelemetry,
    GetPosition,
    GetCurrent,
    GetSpeed,
    GetTouch,
    SetPosition,
    SetSpeed,
    SetCurrent,
    SetTorque,
    Stop,
    Unlock,
    Close,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct WireEnvelope<T> {
    pub schema_version: u16,
    pub message_type: MessageType,
    pub request_id: String,
    pub sequence: u64,
    pub monotonic_time_ms: u64,
    pub operation: SidecarOperation,
    pub payload: T,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum MessageType {
    Request,
    Command,
    Response,
    Event,
    Error,
}

pub fn normalized_to_raw(values: &[f64], expected: usize) -> Result<Vec<u8>, String> {
    if values.len() != expected {
        return Err(format!(
            "expected {expected} normalized values, got {}",
            values.len()
        ));
    }
    if values.iter().any(|v| !v.is_finite()) {
        return Err("normalized position must be finite".into());
    }
    Ok(values
        .iter()
        .map(|v| v.clamp(0.0, 1.0).mul_add(f64::from(RAW_MAX), 0.0).round() as u8)
        .collect())
}

pub fn raw_to_normalized(values: &[u8]) -> Vec<f64> {
    values
        .iter()
        .map(|v| f64::from(*v) / f64::from(RAW_MAX))
        .collect()
}

impl fmt::Display for ConnectionState {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
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
    fn normalized_raw_conversion_is_bounded_and_reversible_at_edges() {
        assert_eq!(
            normalized_to_raw(&[0., 0.5, 1.], 3).unwrap(),
            vec![0, 128, 255]
        );
        assert_eq!(raw_to_normalized(&[0, 255]), vec![0., 1.]);
        assert_eq!(normalized_to_raw(&[-1.1, 1.1], 2).unwrap(), vec![0, 255]);
        assert!(normalized_to_raw(&[f64::NAN], 1).is_err());
        assert!(normalized_to_raw(&[0.], 2).is_err());
    }
    #[test]
    fn wire_is_strictly_named_and_versioned() {
        let e = WireEnvelope {
            schema_version: 1,
            message_type: MessageType::Request,
            request_id: "r".into(),
            sequence: 1,
            monotonic_time_ms: 2,
            operation: SidecarOperation::GetTelemetry,
            payload: serde_json::json!({}),
        };
        let json = to_wire(&e).unwrap();
        assert!(
            json.contains("messageType")
                && json.contains("getTelemetry")
                && json.contains("monotonicTimeMs")
        );
        assert!(!json.contains("monotonic_time_ms"));
    }
    #[test]
    fn raw_capability_fixture_covers_all_supported_models() {
        let fixture: serde_json::Value = serde_json::from_str(include_str!(
            "../../../docs/contracts/raw-capabilities.json"
        ))
        .unwrap();
        assert_eq!(fixture["models"].as_object().unwrap().len(), 8);
        assert_eq!(fixture["rawRange"]["max"], 255);
    }
}
