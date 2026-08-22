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

/// A process-backed NDJSON client.  The child is never driven by an async
/// executor: stdin, stdout, stderr, and process reaping each have a small
/// dedicated OS thread.  This is important on Windows where a blocking pipe
/// read can otherwise stall the Tauri runtime.
pub mod process {
    use super::*;
    use std::collections::HashMap;
    use std::io::{BufRead, BufReader, Write};
    use std::path::PathBuf;
    use std::process::{Child, ChildStdin, Command, Stdio};
    use std::sync::atomic::{AtomicU64, Ordering};
    use std::sync::{mpsc, Arc, Mutex};
    use std::thread;

    #[derive(Debug, Error, Clone, PartialEq, Eq)]
    pub enum ProcessError {
        #[error("sidecar is not running")]
        NotRunning,
        #[error("sidecar process failed: {0}")]
        Spawn(String),
        #[error("sidecar request timed out")]
        Timeout,
        #[error("sidecar crashed: {0}")]
        Crashed(String),
        #[error("sidecar stdout contamination: {0}")]
        Contamination(String),
        #[error("sidecar protocol: {0}")]
        Protocol(String),
        #[error("sidecar returned {0}: {1}")]
        Remote(String, String),
        #[error("too many pending sidecar requests")]
        TooManyPending,
        #[error("sidecar write failed: {0}")]
        Write(String),
    }

    #[derive(Clone, Debug)]
    pub struct ProcessConfig {
        pub program: PathBuf,
        pub args: Vec<String>,
        pub working_dir: Option<PathBuf>,
        pub request_timeout: Duration,
        pub shutdown_timeout: Duration,
        pub max_pending: usize,
    }
    impl ProcessConfig {
        pub fn python(script: impl Into<PathBuf>) -> Self {
            Self {
                program: PathBuf::from("python"),
                args: vec![script.into().to_string_lossy().into_owned()],
                working_dir: None,
                request_timeout: Duration::from_secs(10),
                shutdown_timeout: Duration::from_millis(1500),
                max_pending: 64,
            }
        }
        pub fn fake(script: impl Into<PathBuf>) -> Self {
            let mut config = Self::python(script);
            config.args.push("--fake".into());
            config
        }
    }

    struct Pending {
        operation: SidecarOperation,
        sequence: u64,
        result: mpsc::Sender<Result<WireEnvelope<serde_json::Value>, ProcessError>>,
    }
    struct Inner {
        stdin: Option<ChildStdin>,
        child: Option<Child>,
        pending: HashMap<String, Pending>,
        last_response_sequence: u64,
        state: SidecarState,
        stderr_tail: String,
    }
    impl Inner {
        fn reject_all(&mut self, error: ProcessError) {
            let pending = std::mem::take(&mut self.pending);
            for (_, request) in pending {
                let _ = request.result.send(Err(error.clone()));
            }
        }
    }

    pub struct SidecarProcessManager {
        config: ProcessConfig,
        inner: Arc<Mutex<Inner>>,
        next_sequence: AtomicU64,
        next_request: AtomicU64,
    }
    impl SidecarProcessManager {
        pub fn new(config: ProcessConfig) -> Self {
            Self {
                config,
                inner: Arc::new(Mutex::new(Inner {
                    stdin: None,
                    child: None,
                    pending: HashMap::new(),
                    last_response_sequence: 0,
                    state: SidecarState::NotStarted,
                    stderr_tail: String::new(),
                })),
                next_sequence: AtomicU64::new(0),
                next_request: AtomicU64::new(0),
            }
        }
        pub fn state(&self) -> SidecarState {
            self.inner.lock().unwrap().state.clone()
        }
        pub fn shutdown_timeout(&self) -> Duration {
            self.config.shutdown_timeout
        }
        pub fn start(&self) -> Result<(), ProcessError> {
            {
                let mut inner = self.inner.lock().unwrap();
                if matches!(inner.state, SidecarState::Running) {
                    return Ok(());
                }
                let mut command = Command::new(&self.config.program);
                command
                    .args(&self.config.args)
                    .stdin(Stdio::piped())
                    .stdout(Stdio::piped())
                    .stderr(Stdio::piped());
                if let Some(dir) = &self.config.working_dir {
                    command.current_dir(dir);
                }
                let mut child = command
                    .spawn()
                    .map_err(|e| ProcessError::Spawn(e.to_string()))?;
                let stdin = child
                    .stdin
                    .take()
                    .ok_or_else(|| ProcessError::Spawn("sidecar stdin unavailable".into()))?;
                let stdout = child
                    .stdout
                    .take()
                    .ok_or_else(|| ProcessError::Spawn("sidecar stdout unavailable".into()))?;
                let stderr = child
                    .stderr
                    .take()
                    .ok_or_else(|| ProcessError::Spawn("sidecar stderr unavailable".into()))?;
                inner.stdin = Some(stdin);
                inner.child = Some(child);
                inner.state = SidecarState::Running;
                inner.last_response_sequence = 0;
                inner.stderr_tail.clear();
                Self::spawn_stdout(Arc::clone(&self.inner), stdout);
                Self::spawn_stderr(Arc::clone(&self.inner), stderr);
            }
            Ok(())
        }
        fn spawn_stdout(inner: Arc<Mutex<Inner>>, stdout: impl std::io::Read + Send + 'static) {
            thread::Builder::new()
                .name("linkerhand-sidecar-stdout".into())
                .spawn(move || {
                    let reader = BufReader::new(stdout);
                    for line in reader.lines() {
                        match line {
                            Ok(line) if line.trim().is_empty() => continue,
                            Ok(line) => Self::route_line(&inner, &line),
                            Err(error) => {
                                Self::mark_dead(&inner, ProcessError::Crashed(error.to_string()));
                                break;
                            }
                        }
                    }
                    let state = inner.lock().unwrap().state.clone();
                    if matches!(state, SidecarState::Running) {
                        Self::mark_dead(&inner, ProcessError::Crashed("stdout closed".into()));
                    }
                })
                .expect("spawn stdout thread");
        }
        fn spawn_stderr(inner: Arc<Mutex<Inner>>, stderr: impl std::io::Read + Send + 'static) {
            thread::Builder::new()
                .name("linkerhand-sidecar-stderr".into())
                .spawn(move || {
                    let reader = BufReader::new(stderr);
                    for line in reader.lines().map_while(Result::ok) {
                        let mut guard = inner.lock().unwrap();
                        if guard.stderr_tail.len() > 4096 {
                            guard.stderr_tail.clear();
                        }
                        guard.stderr_tail.push_str(&line);
                        guard.stderr_tail.push('\n');
                    }
                })
                .expect("spawn stderr thread");
        }
        fn mark_dead(inner: &Arc<Mutex<Inner>>, error: ProcessError) {
            let mut guard = inner.lock().unwrap();
            if matches!(guard.state, SidecarState::Running) {
                guard.state = SidecarState::Crashed;
                guard.stdin = None;
                guard.reject_all(error);
            }
        }
        fn route_line(inner: &Arc<Mutex<Inner>>, line: &str) {
            let message = match NdjsonFramer::decode::<serde_json::Value>(line) {
                Ok(message) => message,
                Err(error) => {
                    Self::mark_dead(inner, ProcessError::Contamination(error.to_string()));
                    return;
                }
            };
            if !matches!(
                message.message_type,
                MessageType::Response | MessageType::Error
            ) {
                Self::mark_dead(
                    inner,
                    ProcessError::Protocol(
                        "sidecar stdout message must be response or error".into(),
                    ),
                );
                return;
            }
            let mut guard = inner.lock().unwrap();
            if message.sequence <= guard.last_response_sequence {
                let previous = guard.last_response_sequence;
                guard.reject_all(ProcessError::Protocol(format!(
                    "response sequence {} is not greater than {}",
                    message.sequence, previous
                )));
                return;
            }
            guard.last_response_sequence = message.sequence;
            let Some(pending) = guard.pending.remove(&message.request_id) else {
                return;
            };
            if pending.operation != message.operation {
                let _ = pending.result.send(Err(ProcessError::Protocol(
                    "response request ordering or operation mismatch".into(),
                )));
                return;
            }
            if message.message_type == MessageType::Error {
                match serde_json::from_value::<ErrorPayload>(message.payload.clone()) {
                    Ok(payload) => {
                        let _ = pending.result.send(Err(ProcessError::Remote(
                            payload.error.code,
                            payload.error.message,
                        )));
                    }
                    Err(error) => {
                        let _ = pending
                            .result
                            .send(Err(ProcessError::Protocol(error.to_string())));
                    }
                }
            } else {
                let _ = pending.result.send(Ok(message));
            }
        }
        pub fn request(
            &self,
            operation: SidecarOperation,
            payload: serde_json::Value,
        ) -> Result<WireEnvelope<serde_json::Value>, ProcessError> {
            self.request_timed(operation, payload, self.config.request_timeout)
        }
        pub fn request_timed(
            &self,
            operation: SidecarOperation,
            payload: serde_json::Value,
            timeout: Duration,
        ) -> Result<WireEnvelope<serde_json::Value>, ProcessError> {
            if !matches!(self.state(), SidecarState::Running) {
                return Err(ProcessError::NotRunning);
            }
            let sequence = self.next_sequence.fetch_add(1, Ordering::Relaxed) + 1;
            let request_id = format!(
                "rust-{}",
                self.next_request.fetch_add(1, Ordering::Relaxed) + 1
            );
            let (sender, receiver) = mpsc::channel();
            let message = WireEnvelope {
                schema_version: CURRENT_SCHEMA_VERSION,
                message_type: MessageType::Command,
                request_id: request_id.clone(),
                sequence,
                monotonic_time_ms: monotonic_ms(),
                operation: operation.clone(),
                payload,
            };
            let mut guard = self.inner.lock().unwrap();
            if guard.pending.len() >= self.config.max_pending {
                return Err(ProcessError::TooManyPending);
            }
            let line = NdjsonFramer::encode(&message)
                .map_err(|e| ProcessError::Protocol(e.to_string()))?;
            guard.pending.insert(
                request_id,
                Pending {
                    operation,
                    sequence,
                    result: sender,
                },
            );
            if let Err(error) = guard
                .stdin
                .as_mut()
                .ok_or(ProcessError::NotRunning)
                .and_then(|stdin| {
                    stdin
                        .write_all(line.as_bytes())
                        .and_then(|_| stdin.flush())
                        .map_err(|e| ProcessError::Write(e.to_string()))
                })
            {
                guard.pending.remove(&message.request_id);
                return Err(error);
            }
            drop(guard);
            match receiver.recv_timeout(timeout) {
                Ok(result) => result,
                Err(mpsc::RecvTimeoutError::Timeout) => {
                    let mut guard = self.inner.lock().unwrap();
                    guard.pending.retain(|_, p| p.sequence != sequence);
                    guard.state = SidecarState::TimedOut;
                    guard.reject_all(ProcessError::Timeout);
                    Err(ProcessError::Timeout)
                }
                Err(mpsc::RecvTimeoutError::Disconnected) => {
                    Err(ProcessError::Crashed("response channel closed".into()))
                }
            }
        }
        pub fn restart(&self) -> Result<(), ProcessError> {
            self.close();
            self.start()
        }
        pub fn close(&self) {
            let mut guard = self.inner.lock().unwrap();
            if let Some(mut child) = guard.child.take() {
                let _ = child.kill();
                let _ = child.wait();
            }
            guard.stdin = None;
            guard.state = SidecarState::Stopped;
            guard.reject_all(ProcessError::Crashed("sidecar closed".into()));
        }
        /// Send the protocol close on a short deadline, then terminate the
        /// child regardless of whether the bridge or SDK is stuck.
        pub fn close_bounded(&self, timeout: Duration) {
            let protocol_deadline = timeout.min(Duration::from_millis(1500));
            let _ = self.request_timed(
                SidecarOperation::Close,
                serde_json::json!({}),
                protocol_deadline,
            );
            self.close();
        }
    }
    impl Drop for SidecarProcessManager {
        fn drop(&mut self) {
            self.close();
        }
    }
    fn monotonic_ms() -> u64 {
        static START: std::sync::OnceLock<std::time::Instant> = std::sync::OnceLock::new();
        START
            .get_or_init(std::time::Instant::now)
            .elapsed()
            .as_millis() as u64
    }
    #[cfg(test)]
    mod tests {
        use super::*;
        #[test]
        fn stdout_request_and_event_are_rejected_as_responses() {
            let manager = SidecarProcessManager::new(ProcessConfig::python("missing.py"));
            manager.inner.lock().unwrap().state = SidecarState::Running;
            let envelope = WireEnvelope {
                schema_version: CURRENT_SCHEMA_VERSION,
                message_type: MessageType::Command,
                request_id: "r".into(),
                sequence: 1,
                monotonic_time_ms: 1,
                operation: SidecarOperation::GetTelemetry,
                payload: serde_json::json!({}),
            };
            let line = serde_json::to_string(&envelope).unwrap();
            SidecarProcessManager::route_line(&manager.inner, &line);
            assert_eq!(manager.state(), SidecarState::Crashed);
        }
    }
}

/// Concrete adapter translating the frozen normalized contract to the
/// sidecar's byte-vector protocol.
pub struct SidecarDeviceAdapter {
    config: console_contracts::DeviceConfig,
    manager: process::SidecarProcessManager,
    capabilities: Option<DeviceCapabilities>,
    connected: bool,
    telemetry_sequence: u64,
}
impl SidecarDeviceAdapter {
    pub fn new(
        config: console_contracts::DeviceConfig,
        manager: process::SidecarProcessManager,
    ) -> Self {
        Self {
            config,
            manager,
            capabilities: None,
            connected: false,
            telemetry_sequence: 0,
        }
    }
    pub fn manager(&self) -> &process::SidecarProcessManager {
        &self.manager
    }
    pub fn stop(&self) -> Result<(), device_adapter_api::AdapterError> {
        self.manager
            .request_timed(
                SidecarOperation::Stop,
                serde_json::json!({}),
                Duration::from_millis(500),
            )
            .map(|_| ())
            .map_err(map_process_error)
    }
    pub fn unlock(&self) -> Result<(), device_adapter_api::AdapterError> {
        self.manager
            .request_timed(
                SidecarOperation::Unlock,
                serde_json::json!({}),
                Duration::from_millis(500),
            )
            .map(|_| ())
            .map_err(map_process_error)
    }
    pub fn close(&self) {
        // Ask the bridge to flush/close first; the process manager remains the
        // bounded fallback if the bridge is already crashed or unresponsive.
        let _ = self.command(SidecarOperation::Close, serde_json::json!({}));
        self.manager.close();
    }
    pub fn shutdown_bounded(&mut self, timeout: Duration) {
        self.manager
            .close_bounded(timeout.min(self.manager.shutdown_timeout()));
        self.connected = false;
        self.capabilities = None;
    }
    fn command(
        &self,
        operation: SidecarOperation,
        payload: serde_json::Value,
    ) -> Result<WireEnvelope<serde_json::Value>, device_adapter_api::AdapterError> {
        self.manager
            .request(operation, payload)
            .map_err(map_process_error)
    }
    fn capabilities_from(
        value: serde_json::Value,
        config: &console_contracts::DeviceConfig,
    ) -> Result<DeviceCapabilities, device_adapter_api::AdapterError> {
        let obj = value
            .as_object()
            .ok_or_else(|| invalid("capabilities payload must be an object"))?;
        let number = |name: &str| {
            obj.get(name)
                .and_then(serde_json::Value::as_u64)
                .ok_or_else(|| invalid(format!("capabilities missing {name}")))
        };
        let optional = |name: &str| {
            obj.get(name)
                .and_then(|v| if v.is_null() { None } else { v.as_u64() })
                .map(|v| v as u16)
        };
        let vector = |name: &str, length: u16, available: bool| {
            let range = obj
                .get(name)
                .and_then(|v| v.get("range"))
                .and_then(|v| serde_json::from_value(v.clone()).ok())
                .unwrap_or(console_contracts::RawRange { min: 0, max: 255 });
            console_contracts::VectorCapability {
                length,
                available,
                range,
            }
        };
        let position_length = number("positionLength")? as u16;
        let speed_length = number("speedLength")? as u16;
        let current_length = number("currentLength")? as u16;
        let torque_command = optional("torqueCommandLength");
        let current_command = optional("currentCommandLength");
        let supported_operations = obj
            .get("supportedOperations")
            .and_then(|v| v.as_array())
            .map(|items| {
                items
                    .iter()
                    .filter_map(|v| serde_json::from_value(v.clone()).ok())
                    .collect()
            })
            .unwrap_or_default();
        Ok(DeviceCapabilities {
            schema_version: CURRENT_SCHEMA_VERSION,
            device_id: config.device_id.clone(),
            model: config.model.clone(),
            hand: config.hand.clone(),
            transport: config.transport.clone(),
            joint_count: position_length,
            position: vector("position", position_length, true),
            speed: vector("speed", speed_length, true),
            current: vector("current", current_length, true),
            torque: vector(
                "torque",
                torque_command.unwrap_or(0),
                torque_command.is_some(),
            ),
            touch: vector("touch", position_length, true),
            speed_command_length: number("speedCommandLength")? as u16,
            current_command_length: current_command,
            torque_command_length: torque_command,
            supported_operations,
        })
    }
}
fn invalid(message: impl Into<String>) -> device_adapter_api::AdapterError {
    device_adapter_api::AdapterError::InvalidCommand(message.into())
}
fn map_process_error(error: process::ProcessError) -> device_adapter_api::AdapterError {
    match error {
        process::ProcessError::Remote(code, message) if code == "UNSUPPORTED_CAPABILITY" => {
            device_adapter_api::AdapterError::Unsupported(message)
        }
        process::ProcessError::Remote(code, _message) if code == "NOT_CONNECTED" => {
            device_adapter_api::AdapterError::NotConnected
        }
        process::ProcessError::Timeout => {
            device_adapter_api::AdapterError::Transport("sidecar request timed out".into())
        }
        process::ProcessError::Remote(code, message) => {
            device_adapter_api::AdapterError::Transport(format!("{code}: {message}"))
        }
        other => device_adapter_api::AdapterError::Transport(other.to_string()),
    }
}
impl device_adapter_api::DeviceAdapter for SidecarDeviceAdapter {
    fn id(&self) -> &str {
        &self.config.device_id
    }
    fn connect(&mut self) -> device_adapter_api::AdapterResult<DeviceCapabilities> {
        self.manager.start().map_err(map_process_error)?;
        let transport =
            serde_json::to_value(&self.config.transport).map_err(|e| invalid(e.to_string()))?;
        let payload = serde_json::json!({"deviceId": self.config.device_id, "model": self.config.model, "hand": self.config.hand, "transport": transport, "mode": if matches!(self.config.transport, console_contracts::Transport::Can { ref channel } if channel == "fake") { "fake" } else { "real" }});
        self.command(SidecarOperation::Connect, payload)?;
        let result = self.command(SidecarOperation::Capabilities, serde_json::json!({}))?;
        let capabilities = Self::capabilities_from(result.payload, &self.config)?;
        self.capabilities = Some(capabilities.clone());
        self.connected = true;
        Ok(capabilities)
    }
    fn disconnect(&mut self) -> device_adapter_api::AdapterResult<()> {
        if self.connected {
            self.command(SidecarOperation::Disconnect, serde_json::json!({}))?;
        }
        self.connected = false;
        self.capabilities = None;
        Ok(())
    }
    fn is_connected(&self) -> bool {
        self.connected
    }
    fn capabilities(&self) -> Option<&DeviceCapabilities> {
        self.capabilities.as_ref()
    }
    fn send_joint_target(
        &mut self,
        command: &console_contracts::JointTargetCommand,
    ) -> device_adapter_api::AdapterResult<()> {
        if !self.connected {
            return Err(device_adapter_api::AdapterError::NotConnected);
        }
        let length = self
            .capabilities
            .as_ref()
            .map(|c| c.position.length as usize)
            .ok_or(device_adapter_api::AdapterError::NotConnected)?;
        let raw = normalized_to_raw(&command.positions, length)
            .map_err(device_adapter_api::AdapterError::InvalidCommand)?;
        self.command(
            SidecarOperation::SetPosition,
            serde_json::json!({"positions": raw}),
        )?;
        Ok(())
    }
    fn set_speed(&mut self, values: &[u8]) -> device_adapter_api::AdapterResult<()> {
        if !self.connected {
            return Err(device_adapter_api::AdapterError::NotConnected);
        }
        let expected = self
            .capabilities
            .as_ref()
            .map(|c| c.speed_command_length as usize)
            .ok_or(device_adapter_api::AdapterError::NotConnected)?;
        if values.len() != expected {
            return Err(invalid(format!(
                "speed vector expects {expected}, got {}",
                values.len()
            )));
        }
        self.command(
            SidecarOperation::SetSpeed,
            serde_json::json!({"speeds": values}),
        )?;
        Ok(())
    }
    fn set_torque(&mut self, values: &[u8]) -> device_adapter_api::AdapterResult<()> {
        if !self.connected {
            return Err(device_adapter_api::AdapterError::NotConnected);
        }
        let expected = self
            .capabilities
            .as_ref()
            .and_then(|c| c.torque_command_length)
            .ok_or_else(|| device_adapter_api::AdapterError::Unsupported("setTorque".into()))?
            as usize;
        if values.len() != expected {
            return Err(invalid(format!(
                "torque vector expects {expected}, got {}",
                values.len()
            )));
        }
        self.command(
            SidecarOperation::SetTorque,
            serde_json::json!({"torques": values}),
        )?;
        Ok(())
    }
    fn read_telemetry(
        &mut self,
        monotonic_time_ms: u64,
    ) -> device_adapter_api::AdapterResult<console_contracts::TelemetrySnapshot> {
        if !self.connected {
            return Err(device_adapter_api::AdapterError::NotConnected);
        }
        let payload = self
            .command(SidecarOperation::GetTelemetry, serde_json::json!({}))?
            .payload;
        let get = |name: &str| -> Result<Vec<u8>, device_adapter_api::AdapterError> {
            payload
                .get(name)
                .and_then(|v| v.as_array())
                .ok_or_else(|| invalid(format!("telemetry missing {name}")))
                .and_then(|values| {
                    values
                        .iter()
                        .map(|v| {
                            v.as_u64().map(|n| n as u8).ok_or_else(|| {
                                invalid(format!("telemetry {name} contains non-byte"))
                            })
                        })
                        .collect()
                })
        };
        let raw_position = get("position")?;
        let positions = raw_to_normalized(&raw_position);
        let raw_current = get("current")?;
        let raw_speed = get("speed")?;
        let raw_touch = get("touch")?;
        self.telemetry_sequence = self.telemetry_sequence.saturating_add(1);
        Ok(console_contracts::TelemetrySnapshot {
            schema_version: CURRENT_SCHEMA_VERSION,
            device_id: self.config.device_id.clone(),
            sequence: self.telemetry_sequence,
            monotonic_time_ms,
            positions,
            raw_position,
            raw_current,
            raw_speed,
            raw_touch,
            connected: true,
        })
    }
    fn stop(&mut self) -> device_adapter_api::AdapterResult<()> {
        SidecarDeviceAdapter::stop(self)
    }
    fn unlock(&mut self) -> device_adapter_api::AdapterResult<()> {
        SidecarDeviceAdapter::unlock(self)
    }
    fn shutdown(&mut self) -> device_adapter_api::AdapterResult<()> {
        let timeout = self.manager.shutdown_timeout();
        self.shutdown_bounded(timeout);
        Ok(())
    }
}
impl Drop for SidecarDeviceAdapter {
    fn drop(&mut self) {
        self.shutdown_bounded(Duration::from_secs(2));
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

    #[test]
    fn fake_python_sidecar_round_trip_and_stop_unlock() {
        use device_adapter_api::DeviceAdapter;
        let script = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../../sidecar/linkerhand-bridge/main.py");
        let mut config = process::ProcessConfig::fake(script);
        config.request_timeout = Duration::from_secs(5);
        let manager = process::SidecarProcessManager::new(config);
        let device_config = console_contracts::DeviceConfig::new("fake-1", "fake");
        let mut adapter = SidecarDeviceAdapter::new(device_config, manager);
        let capabilities = adapter.connect().expect("fake sidecar connects");
        assert_eq!(capabilities.joint_count, 6);
        let command = console_contracts::JointTargetCommand {
            schema_version: CURRENT_SCHEMA_VERSION,
            command_id: "set-1".into(),
            source: console_contracts::CommandSource::Manual,
            positions: vec![0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
            duration_ms: None,
            final_command: true,
        };
        device_adapter_api::DeviceAdapter::send_joint_target(&mut adapter, &command).unwrap();
        let telemetry =
            device_adapter_api::DeviceAdapter::read_telemetry(&mut adapter, 42).unwrap();
        assert_eq!(telemetry.positions, command.positions);
        adapter.stop().unwrap();
        assert!(
            device_adapter_api::DeviceAdapter::send_joint_target(&mut adapter, &command).is_err()
        );
        adapter.unlock().unwrap();
        device_adapter_api::DeviceAdapter::send_joint_target(&mut adapter, &command).unwrap();
        device_adapter_api::DeviceAdapter::disconnect(&mut adapter).unwrap();
        adapter.close();
    }
    #[test]
    fn fake_process_bounded_protocol_close() {
        let script = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../../sidecar/linkerhand-bridge/main.py");
        let manager = process::SidecarProcessManager::new(process::ProcessConfig::fake(script));
        manager.start().unwrap();
        let started = std::time::Instant::now();
        manager.close_bounded(Duration::from_secs(2));
        assert!(started.elapsed() < Duration::from_secs(2));
        assert_eq!(manager.state(), SidecarState::Stopped);
    }
    #[test]
    fn timeout_then_restart_is_bounded() {
        let mut config = process::ProcessConfig::python("-c");
        config.args = vec!["-c".into(), "import time; time.sleep(5)".into()];
        config.request_timeout = Duration::from_millis(50);
        let manager = process::SidecarProcessManager::new(config);
        manager.start().unwrap();
        let result = manager.request(SidecarOperation::GetTelemetry, serde_json::json!({}));
        assert!(matches!(result, Err(process::ProcessError::Timeout)));
        assert_eq!(manager.state(), SidecarState::TimedOut);
        manager.restart().unwrap();
        assert_eq!(manager.state(), SidecarState::Running);
        manager.close_bounded(Duration::from_millis(100));
    }
}
