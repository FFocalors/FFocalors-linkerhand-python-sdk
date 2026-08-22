//! Tauri assembly only. `RuntimeActor` is the single owner of AppRuntime and
//! the sidecar adapter; IPC commands never hold a mutex while doing I/O.
use app_runtime::AppRuntime;
use console_contracts::{
    AppError, ConnectionSnapshot, DeviceCapabilities, DeviceConfig, JointTargetCommand,
    OperationSnapshot, TelemetrySnapshot,
};
use serde::{Deserialize, Serialize};
use sidecar_client::{
    process::{ProcessConfig, SidecarProcessManager},
    SidecarDeviceAdapter,
};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{mpsc, Arc};
use std::thread;
use tauri::ipc::Channel;
use tauri::Manager;

fn app_error(code: &str, message: impl Into<String>, retryable: bool) -> AppError {
    AppError {
        code: code.into(),
        message: message.into(),
        retryable,
        details: None,
    }
}
fn map_error(value: impl std::fmt::Display) -> AppError {
    app_error("RUNTIME_ERROR", value.to_string(), true)
}

type Reply<T> = tokio::sync::oneshot::Sender<Result<T, AppError>>;
#[derive(Clone, Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct VectorCommand {
    values: Vec<f64>,
    #[allow(dead_code)]
    final_command: bool,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct ActionStateEvent {
    state: String,
    action_id: Option<String>,
    progress: f32,
    detail: Option<String>,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct GraspStateEvent {
    phase: String,
    failure: Option<GraspFailure>,
    tactile_available: bool,
    raw_touch: Option<Vec<u8>>,
    degraded: bool,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
struct GraspFailure {
    code: String,
    message: String,
}
#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct SidecarCheck {
    ok: bool,
    message: String,
    detail: Option<String>,
}
enum ActorRequest {
    Config {
        reply: Reply<DeviceConfig>,
    },
    Capabilities {
        reply: Reply<DeviceCapabilities>,
    },
    Connection {
        reply: Reply<ConnectionSnapshot>,
    },
    Connect {
        reply: Reply<ConnectionSnapshot>,
    },
    Disconnect {
        reply: Reply<ConnectionSnapshot>,
    },
    Submit {
        command: JointTargetCommand,
        reply: Reply<()>,
    },
    CancelMotionSource {
        source: console_contracts::CommandSource,
        reply: Reply<()>,
    },
    SetSpeed {
        command: VectorCommand,
        reply: Reply<()>,
    },
    SetTorque {
        command: VectorCommand,
        reply: Reply<()>,
    },
    Reconnect {
        reply: Reply<ConnectionSnapshot>,
    },
    SubscribeConnection {
        channel: Channel<ConnectionSnapshot>,
        reply: Reply<()>,
    },
    UnsubscribeConnection {
        channel_id: u32,
        reply: Reply<()>,
    },
    SubscribeOperation {
        channel: Channel<OperationSnapshot>,
        reply: Reply<()>,
    },
    UnsubscribeOperation {
        channel_id: u32,
        reply: Reply<()>,
    },
    ActionList {
        reply: Reply<Vec<console_contracts::ActionRecording>>,
    },
    ActionDelete {
        id: String,
        reply: Reply<()>,
    },
    ActionStartRecording {
        name: String,
        reply: Reply<()>,
    },
    ActionPauseRecording {
        reply: Reply<()>,
    },
    ActionResumeRecording {
        reply: Reply<()>,
    },
    ActionFinishRecording {
        reply: Reply<()>,
    },
    ActionCancelRecording {
        reply: Reply<()>,
    },
    ActionPlay {
        id: String,
        speed: f32,
        loop_enabled: bool,
        loop_count: Option<u32>,
        reply: Reply<()>,
    },
    ActionPause {
        reply: Reply<()>,
    },
    ActionResume {
        reply: Reply<()>,
    },
    ActionStop {
        reply: Reply<()>,
    },
    SubscribeAction {
        channel: Channel<ActionStateEvent>,
        reply: Reply<()>,
    },
    UnsubscribeAction {
        channel_id: u32,
        reply: Reply<()>,
    },
    GraspCalibrate {
        reply: Reply<()>,
    },
    GraspCompleteCalibration {
        reply: Reply<()>,
    },
    GraspApproach {
        reply: Reply<()>,
    },
    GraspStart {
        degraded: bool,
        reply: Reply<()>,
    },
    GraspRelease {
        reply: Reply<()>,
    },
    GraspAbort {
        reply: Reply<()>,
    },
    SubscribeGrasp {
        channel: Channel<GraspStateEvent>,
        reply: Reply<()>,
    },
    UnsubscribeGrasp {
        channel_id: u32,
        reply: Reply<()>,
    },
    GraspPresets {
        reply: Reply<Vec<console_contracts::GraspPreset>>,
    },
    Logs {
        limit: usize,
        reply: Reply<Vec<console_contracts::StructuredLogEntry>>,
    },
    Operation {
        reply: Reply<OperationSnapshot>,
    },
    ReadTelemetry {
        reply: Reply<TelemetrySnapshot>,
    },
    SubscribeTelemetry {
        channel: Channel<TelemetrySnapshot>,
        reply: Reply<()>,
    },
    UnsubscribeTelemetry {
        channel_id: u32,
        reply: Reply<()>,
    },
    Shutdown,
}

#[derive(Clone)]
pub struct RuntimeHandle {
    tx: mpsc::SyncSender<ActorRequest>,
    control_state: Arc<std::sync::atomic::AtomicU8>,
    shutdown_requested: Arc<AtomicBool>,
    stopped: Arc<AtomicBool>,
    sidecar: Arc<SidecarRuntimeInfo>,
}
pub struct RuntimeState(pub RuntimeHandle);

#[derive(Clone, Debug)]
struct SidecarRuntimeInfo {
    process: ProcessConfig,
    simulator: bool,
    selected_path: Option<PathBuf>,
}

impl RuntimeHandle {
    fn enqueue(&self, request: ActorRequest) -> Result<(), AppError> {
        self.tx.try_send(request).map_err(|error| match error {
            mpsc::TrySendError::Full(_) => {
                app_error("RUNTIME_BUSY", "runtime command queue is full", true)
            }
            mpsc::TrySendError::Disconnected(_) => {
                app_error("RUNTIME_CLOSED", "runtime actor is closed", false)
            }
        })
    }
    fn shutdown(&self) {
        self.shutdown_requested.store(true, Ordering::Release);
        let _ = self.tx.try_send(ActorRequest::Shutdown);
        let deadline = std::time::Instant::now() + std::time::Duration::from_millis(1900);
        while !self.stopped.load(Ordering::Acquire) && std::time::Instant::now() < deadline {
            thread::sleep(std::time::Duration::from_millis(10));
        }
    }

    fn sidecar_info(&self) -> SidecarRuntimeInfo {
        (*self.sidecar).clone()
    }
}

struct RuntimeActor {
    runtime: AppRuntime,
    rx: mpsc::Receiver<ActorRequest>,
    telemetry_channels: Vec<Channel<TelemetrySnapshot>>,
    connection_channels: Vec<Channel<ConnectionSnapshot>>,
    operation_channels: Vec<Channel<OperationSnapshot>>,
    action_channels: Vec<Channel<ActionStateEvent>>,
    grasp_channels: Vec<Channel<GraspStateEvent>>,
    latest: Option<TelemetrySnapshot>,
    control_state: Arc<std::sync::atomic::AtomicU8>,
    shutdown_requested: Arc<AtomicBool>,
    applied_control: u8,
    stopped: Arc<AtomicBool>,
}
impl RuntimeActor {
    fn run(mut self) {
        let mut next_telemetry = now_ms();
        loop {
            self.apply_control();
            if self.shutdown_requested.load(Ordering::Acquire) {
                self.shutdown();
                break;
            }
            match self.rx.recv_timeout(std::time::Duration::from_millis(5)) {
                Ok(ActorRequest::Shutdown) => {
                    self.shutdown();
                    break;
                }
                Ok(request) => self.handle(request),
                Err(mpsc::RecvTimeoutError::Timeout) => {}
                Err(mpsc::RecvTimeoutError::Disconnected) => {
                    self.shutdown();
                    break;
                }
            }
            self.apply_control();
            if self.shutdown_requested.load(Ordering::Acquire) {
                self.shutdown();
                break;
            }
            let now = now_ms();
            if now.saturating_sub(next_telemetry) >= 50 {
                next_telemetry = now;
                self.flush_motion(now);
                self.broadcast_operation();
                self.broadcast_action();
                self.broadcast_grasp();
                if !self.telemetry_channels.is_empty() || !self.grasp_channels.is_empty() {
                    self.sample_and_broadcast(now);
                }
            }
        }
    }
    fn handle(&mut self, request: ActorRequest) {
        match request {
            ActorRequest::Config { reply } => {
                let _ = reply.send(Ok(app_runtime::ui::DevicePort::get_config(&self.runtime)));
            }
            ActorRequest::Capabilities { reply } => {
                // Capabilities are a read-only model declaration until the
                // operator connects.  DeviceRuntime replaces it with the
                // adapter response after a successful explicit connect.
                let result = app_runtime::ui::DevicePort::get_capabilities(&self.runtime)
                    .ok_or_else(|| {
                        app_error(
                            "CAPABILITIES_UNAVAILABLE",
                            "capabilities are not available for this device configuration",
                            true,
                        )
                    });
                let _ = reply.send(result);
            }
            ActorRequest::Connection { reply } => {
                let _ = reply.send(Ok(app_runtime::ui::DevicePort::get_connection(
                    &self.runtime,
                )));
            }
            ActorRequest::Connect { reply } => {
                let result = self
                    .runtime
                    .connect()
                    .map(|_| app_runtime::ui::DevicePort::get_connection(&self.runtime))
                    .map_err(map_error);
                if let Ok(snapshot) = &result {
                    self.broadcast_connection(snapshot.clone());
                }
                let _ = reply.send(result);
            }
            ActorRequest::Reconnect { reply } => {
                let result = self
                    .runtime
                    .device
                    .reconnect()
                    .map(|_| self.runtime.device.snapshot())
                    .map_err(map_error);
                if let Ok(snapshot) = &result {
                    self.broadcast_connection(snapshot.clone());
                }
                let _ = reply.send(result);
            }
            ActorRequest::Disconnect { reply } => {
                let result = self
                    .runtime
                    .device
                    .disconnect()
                    .map(|_| app_runtime::ui::DevicePort::get_connection(&self.runtime))
                    .map_err(map_error);
                if let Ok(snapshot) = &result {
                    self.broadcast_connection(snapshot.clone());
                }
                let _ = reply.send(result);
            }
            ActorRequest::Submit { command, reply } => {
                if self.control_state.load(Ordering::Acquire) == 1 {
                    let _ = reply.send(Err(app_error(
                        "STOPPED",
                        "motion is locked after stop",
                        false,
                    )));
                    return;
                }
                let result = self
                    .runtime
                    .motion
                    .submit(command.clone())
                    .map_err(map_error);
                if result.is_ok()
                    && matches!(
                        self.runtime.actions.state(),
                        action_engine::PlaybackState::Recording
                            | action_engine::PlaybackState::RecordingPaused
                    )
                {
                    let _ = self
                        .runtime
                        .action_record_command(command.clone(), now_ms());
                }
                if result.is_ok() && command.final_command {
                    self.flush_motion(now_ms());
                }
                let _ = reply.send(result);
            }
            ActorRequest::SetSpeed { command, reply } => {
                let result = app_runtime::ui::DevicePort::set_speed(
                    &mut self.runtime,
                    command.values,
                    now_ms(),
                )
                .map_err(map_error);
                let _ = reply.send(result);
            }
            ActorRequest::SetTorque { command, reply } => {
                let result = app_runtime::ui::DevicePort::set_torque(
                    &mut self.runtime,
                    command.values,
                    now_ms(),
                )
                .map_err(map_error);
                let _ = reply.send(result);
            }
            ActorRequest::CancelMotionSource { source, reply } => {
                self.runtime.cancel_motion_source(source);
                let _ = reply.send(Ok(()));
            }
            ActorRequest::Operation { reply } => {
                let _ = reply.send(Ok(app_runtime::ui::MotionPort::get_operation(
                    &self.runtime,
                )));
            }
            ActorRequest::ReadTelemetry { reply } => {
                let result = self
                    .latest
                    .clone()
                    .or_else(|| self.runtime.sample_telemetry(now_ms()).ok())
                    .ok_or_else(|| {
                        app_error(
                            "TELEMETRY_UNAVAILABLE",
                            "telemetry is not available until the device is connected",
                            true,
                        )
                    });
                if let Ok(value) = &result {
                    self.latest = Some(value.clone());
                }
                let _ = reply.send(result);
            }
            ActorRequest::SubscribeTelemetry { channel, reply } => {
                if self.telemetry_channels.len() >= 8 {
                    let _ = reply.send(Err(app_error(
                        "RUNTIME_BUSY",
                        "telemetry subscriber limit reached",
                        true,
                    )));
                } else {
                    self.telemetry_channels.push(channel);
                    let _ = reply.send(Ok(()));
                }
            }
            ActorRequest::UnsubscribeTelemetry { channel_id, reply } => {
                self.telemetry_channels
                    .retain(|channel| channel.id() != channel_id);
                let _ = reply.send(Ok(()));
            }
            ActorRequest::SubscribeConnection { channel, reply } => {
                if self.connection_channels.len() < 8 {
                    let snapshot = self.runtime.device.snapshot();
                    let _ = channel.send(snapshot);
                    self.connection_channels.push(channel);
                    let _ = reply.send(Ok(()));
                } else {
                    let _ = reply.send(Err(app_error(
                        "RUNTIME_BUSY",
                        "connection subscriber limit reached",
                        true,
                    )));
                }
            }
            ActorRequest::UnsubscribeConnection { channel_id, reply } => {
                self.connection_channels.retain(|c| c.id() != channel_id);
                let _ = reply.send(Ok(()));
            }
            ActorRequest::SubscribeOperation { channel, reply } => {
                if self.operation_channels.len() < 8 {
                    self.operation_channels.push(channel);
                    let _ = reply.send(Ok(()));
                } else {
                    let _ = reply.send(Err(app_error(
                        "RUNTIME_BUSY",
                        "operation subscriber limit reached",
                        true,
                    )));
                }
            }
            ActorRequest::UnsubscribeOperation { channel_id, reply } => {
                self.operation_channels.retain(|c| c.id() != channel_id);
                let _ = reply.send(Ok(()));
            }
            ActorRequest::ActionList { reply } => {
                let _ = reply.send(Ok(self.runtime.action_list()));
            }
            ActorRequest::ActionDelete { id, reply } => {
                let _ = reply.send(self.runtime.action_delete(&id).map_err(map_error));
            }
            ActorRequest::ActionStartRecording { name, reply } => {
                self.runtime
                    .action_start_recording(format!("custom:{}", now_ms()), name, now_ms());
                let _ = reply.send(Ok(()));
            }
            ActorRequest::ActionPauseRecording { reply } => {
                let _ = reply.send(self.runtime.actions.pause_recording().map_err(map_error));
            }
            ActorRequest::ActionResumeRecording { reply } => {
                let _ = reply.send(self.runtime.actions.resume_recording().map_err(map_error));
            }
            ActorRequest::ActionFinishRecording { reply } => {
                let _ = reply.send(
                    self.runtime
                        .action_finish_recording()
                        .map(|_| ())
                        .map_err(map_error),
                );
            }
            ActorRequest::ActionCancelRecording { reply } => {
                let _ = reply.send(self.runtime.actions.cancel_recording().map_err(map_error));
            }
            ActorRequest::ActionPlay {
                id,
                speed,
                loop_enabled,
                loop_count,
                reply,
            } => {
                let result = if let Some(active) = self.runtime.motion.active_source() {
                    if !matches!(
                        active,
                        console_contracts::CommandSource::Playback
                            | console_contracts::CommandSource::Loop
                    ) {
                        Err(app_error(
                            "SOURCE_BUSY",
                            format!("motion source {active:?} is active"),
                            true,
                        ))
                    } else {
                        self.runtime
                            .action_play(&id, speed, loop_enabled, loop_count, now_ms())
                            .map_err(map_error)
                    }
                } else {
                    self.runtime
                        .action_play(&id, speed, loop_enabled, loop_count, now_ms())
                        .map_err(map_error)
                };
                let _ = reply.send(result);
            }
            ActorRequest::ActionPause { reply } => {
                let _ = reply.send(self.runtime.actions.pause_playback().map_err(map_error));
            }
            ActorRequest::ActionResume { reply } => {
                let _ = reply.send(self.runtime.actions.resume_playback().map_err(map_error));
            }
            ActorRequest::ActionStop { reply } => {
                self.runtime.action_stop();
                let _ = reply.send(Ok(()));
            }
            ActorRequest::SubscribeAction { channel, reply } => {
                if self.action_channels.len() < 8 {
                    self.action_channels.push(channel);
                    let _ = reply.send(Ok(()));
                } else {
                    let _ = reply.send(Err(app_error(
                        "RUNTIME_BUSY",
                        "action subscriber limit reached",
                        true,
                    )));
                }
            }
            ActorRequest::UnsubscribeAction { channel_id, reply } => {
                self.action_channels.retain(|c| c.id() != channel_id);
                let _ = reply.send(Ok(()));
            }
            ActorRequest::GraspCalibrate { reply } => {
                let _ = reply.send(self.runtime.grasp_calibrate(now_ms()).map_err(map_error));
            }
            ActorRequest::GraspCompleteCalibration { reply } => {
                let _ = reply.send(self.runtime.grasp_complete_calibration().map_err(map_error));
            }
            ActorRequest::GraspApproach { reply } => {
                let _ = reply.send(
                    self.runtime
                        .grasp_start_approach(now_ms())
                        .map_err(map_error),
                );
            }
            ActorRequest::GraspStart { degraded, reply } => {
                let _ = reply.send(
                    self.runtime
                        .grasp_start(degraded, now_ms())
                        .map_err(map_error),
                );
            }
            ActorRequest::GraspRelease { reply } => {
                let _ = reply.send(self.runtime.grasp_release().map_err(map_error));
            }
            ActorRequest::GraspAbort { reply } => {
                self.runtime.grasp.abort();
                let _ = reply.send(Ok(()));
            }
            ActorRequest::SubscribeGrasp { channel, reply } => {
                if self.grasp_channels.len() < 8 {
                    self.grasp_channels.push(channel);
                    let _ = reply.send(Ok(()));
                } else {
                    let _ = reply.send(Err(app_error(
                        "RUNTIME_BUSY",
                        "grasp subscriber limit reached",
                        true,
                    )));
                }
            }
            ActorRequest::UnsubscribeGrasp { channel_id, reply } => {
                self.grasp_channels.retain(|c| c.id() != channel_id);
                let _ = reply.send(Ok(()));
            }
            ActorRequest::GraspPresets { reply } => {
                let _ = reply.send(Ok(app_runtime::ui::GraspPort::list_presets(&self.runtime)));
            }
            ActorRequest::Logs { limit, reply } => {
                let _ = reply.send(Ok(app_runtime::ui::LogPort::list(
                    &self.runtime,
                    limit.min(512),
                )));
            }
            ActorRequest::Shutdown => {}
        }
    }
    fn apply_control(&mut self) {
        let desired = self.control_state.load(Ordering::Acquire);
        if desired == self.applied_control {
            return;
        }
        if desired == 2 && self.applied_control == 0 {
            // Preserve stop-before-unlock ordering even if both atomics were
            // changed while the actor was busy or the request queue was full.
            self.runtime.stop_all();
            self.applied_control = 1;
            return;
        }
        match desired {
            1 => self.runtime.stop_all(),
            2 => self.runtime.unlock(),
            _ => return,
        }
        self.applied_control = desired;
    }
    fn flush_motion(&mut self, now: u64) {
        if let Some(command) = self.runtime.action_tick(now) {
            let _ = self.runtime.motion.submit(command);
        }
        if let Ok(Some(command)) = self.runtime.grasp_tick(now) {
            let _ = self.runtime.motion.submit(command);
        }
        if let Some(command) = self.runtime.motion.tick(now) {
            let _ = self.runtime.device.send(&command);
        }
    }
    fn broadcast_connection(&mut self, value: ConnectionSnapshot) {
        self.connection_channels
            .retain(|channel| channel.send(value.clone()).is_ok());
    }
    fn operation_snapshot(&self) -> OperationSnapshot {
        app_runtime::ui::MotionPort::get_operation(&self.runtime)
    }
    fn broadcast_operation(&mut self) {
        let value = self.operation_snapshot();
        self.operation_channels
            .retain(|channel| channel.send(value.clone()).is_ok());
    }
    fn broadcast_action(&mut self) {
        use action_engine::PlaybackState;
        let state = self.runtime.actions.state();
        let (label, progress) = match state {
            PlaybackState::Recording => ("recording", 0.0),
            PlaybackState::RecordingPaused => ("recordingPaused", 0.0),
            PlaybackState::Playing => ("playing", self.runtime.actions.progress()),
            PlaybackState::Paused => ("paused", self.runtime.actions.progress()),
            PlaybackState::Completed => ("completed", 1.0),
            PlaybackState::Cancelled => ("cancelled", 0.0),
            PlaybackState::Idle => ("idle", 0.0),
        };
        let value = ActionStateEvent {
            state: label.into(),
            action_id: self.runtime.actions.current_action_id().map(str::to_owned),
            progress,
            detail: None,
        };
        self.action_channels
            .retain(|channel| channel.send(value.clone()).is_ok());
    }
    fn broadcast_grasp(&mut self) {
        use adaptive_grasp::GraspState;
        let phase = match self.runtime.grasp.state() {
            GraspState::Idle => "idle",
            GraspState::Calibrating => "calibrating",
            GraspState::Ready => "ready",
            GraspState::Approaching => "approach",
            GraspState::Grasping => "grasping",
            GraspState::Holding => "holding",
            GraspState::Releasing => "releasing",
            GraspState::Aborted => "aborted",
            GraspState::Failed => "failed",
        };
        let telemetry = self.latest.as_ref();
        let failure = self.runtime.grasp.failure().map(|reason| GraspFailure {
            code: format!("{reason:?}"),
            message: reason.operator_message().into(),
        });
        let value = GraspStateEvent {
            phase: phase.into(),
            failure,
            tactile_available: telemetry.is_some_and(|t| !t.raw_touch.is_empty()),
            raw_touch: telemetry.map(|t| t.raw_touch.clone()),
            degraded: self.runtime.grasp.degraded(),
        };
        self.grasp_channels
            .retain(|channel| channel.send(value.clone()).is_ok());
    }
    fn sample_and_broadcast(&mut self, now: u64) {
        let Ok(value) = self.runtime.sample_telemetry(now) else {
            return;
        };
        self.latest = Some(value.clone());
        self.telemetry_channels
            .retain(|channel| channel.send(value.clone()).is_ok());
    }
    fn shutdown(&mut self) {
        self.runtime.motion.stop_all();
        self.runtime.shutdown();
        self.stopped.store(true, Ordering::Release);
    }
}

fn simulator_enabled() -> bool {
    matches!(
        std::env::var("LINKERHAND_CONSOLE_SIMULATOR")
            .ok()
            .as_deref(),
        Some("1") | Some("true") | Some("TRUE") | Some("yes")
    )
}

fn safe_default_config() -> DeviceConfig {
    let mut config = DeviceConfig::new("linkerhand-o6", "LinkerHand O6");
    config.transport = console_contracts::Transport::Can {
        channel: "PCAN_USBBUS1".into(),
    };
    config.auto_reconnect = false;
    config
}

fn profile_for_model(model: &console_contracts::DeviceModel) -> adaptive_grasp::Profile {
    match model {
        console_contracts::DeviceModel::O6 => adaptive_grasp::Profile::O6,
        console_contracts::DeviceModel::L6 => adaptive_grasp::Profile::L6,
        console_contracts::DeviceModel::L7 => adaptive_grasp::Profile::L7,
        console_contracts::DeviceModel::L10 => adaptive_grasp::Profile::L10,
        console_contracts::DeviceModel::L20 => adaptive_grasp::Profile::L20,
        console_contracts::DeviceModel::G20 => adaptive_grasp::Profile::G20,
        console_contracts::DeviceModel::L21 => adaptive_grasp::Profile::L21,
        console_contracts::DeviceModel::L25 => adaptive_grasp::Profile::L25,
    }
}

fn normalize_config(mut config: DeviceConfig, simulator: bool) -> DeviceConfig {
    if simulator {
        config.transport = console_contracts::Transport::Can {
            channel: "fake".into(),
        };
    } else if matches!(
        config.transport,
        console_contracts::Transport::Can { ref channel } if channel.eq_ignore_ascii_case("fake")
    ) {
        config.transport = console_contracts::Transport::Can {
            channel: "PCAN_USBBUS1".into(),
        };
    }
    config
}

fn sidecar_candidates(explicit: Option<&Path>, roots: &[PathBuf]) -> Vec<PathBuf> {
    let mut values = Vec::new();
    if let Some(path) = explicit {
        values.push(path.to_path_buf());
    }
    for root in roots {
        values.extend([
            root.join("linkerhand-sidecar.exe"),
            root.join("linkerhand-sidecar-x86_64-pc-windows-msvc.exe"),
            root.join("binaries/linkerhand-sidecar.exe"),
            root.join("binaries/linkerhand-sidecar-x86_64-pc-windows-msvc.exe"),
            root.join("sidecar/linkerhand-sidecar.exe"),
        ]);
    }
    values
}

fn resolve_sidecar_path(explicit: Option<PathBuf>, roots: Vec<PathBuf>) -> Option<PathBuf> {
    sidecar_candidates(explicit.as_deref(), &roots)
        .into_iter()
        .find(|path| path.is_file())
}

fn sidecar_process(explicit: Option<PathBuf>, simulator: bool) -> (ProcessConfig, Option<PathBuf>) {
    if simulator {
        let script =
            PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../sidecar/linkerhand-bridge/main.py");
        return (ProcessConfig::fake(script), None);
    }
    let exe_dir = std::env::current_exe()
        .ok()
        .and_then(|path| path.parent().map(Path::to_path_buf));
    let mut roots = Vec::new();
    if let Some(dir) = exe_dir.clone() {
        roots.push(dir);
    }
    if let Ok(dir) = std::env::current_dir() {
        roots.push(dir);
    }
    let selected = resolve_sidecar_path(explicit, roots.clone());
    // Keep a deterministic, explainable missing path so a later explicit
    // connect reports a sidecar error rather than silently falling back to
    // Python from PATH.
    let program = selected
        .clone()
        .or_else(|| sidecar_candidates(None, &roots).into_iter().next())
        .unwrap_or_else(|| PathBuf::from("linkerhand-sidecar.exe"));
    (ProcessConfig::executable(program), selected)
}

fn spawn_runtime(
    config: DeviceConfig,
    process: ProcessConfig,
    simulator: bool,
    selected_path: Option<PathBuf>,
) -> RuntimeHandle {
    let mut runtime = AppRuntime::new(config.clone(), profile_for_model(&config.model));
    runtime.install_adapter(Box::new(SidecarDeviceAdapter::new(
        config,
        SidecarProcessManager::new(process.clone()),
    )));
    let (tx, rx) = mpsc::sync_channel(128);
    let control_state = Arc::new(std::sync::atomic::AtomicU8::new(0));
    let shutdown_requested = Arc::new(AtomicBool::new(false));
    let stopped = Arc::new(AtomicBool::new(false));
    let actor_control = Arc::clone(&control_state);
    let actor_shutdown = Arc::clone(&shutdown_requested);
    let actor_stopped = Arc::clone(&stopped);
    thread::Builder::new()
        .name("linkerhand-runtime-actor".into())
        .spawn(move || {
            RuntimeActor {
                runtime,
                rx,
                telemetry_channels: Vec::new(),
                connection_channels: Vec::new(),
                operation_channels: Vec::new(),
                action_channels: Vec::new(),
                grasp_channels: Vec::new(),
                latest: None,
                control_state: actor_control,
                shutdown_requested: actor_shutdown,
                applied_control: 0,
                stopped: actor_stopped,
            }
            .run()
        })
        .expect("spawn runtime actor");
    RuntimeHandle {
        tx,
        control_state,
        shutdown_requested,
        stopped,
        sidecar: Arc::new(SidecarRuntimeInfo {
            process,
            simulator,
            selected_path,
        }),
    }
}

async fn dispatch<T>(
    handle: RuntimeHandle,
    request: impl FnOnce(Reply<T>) -> ActorRequest,
) -> Result<T, AppError> {
    let (reply, receiver) = tokio::sync::oneshot::channel();
    handle.enqueue(request(reply))?;
    receiver
        .await
        .map_err(|_| app_error("RUNTIME_CLOSED", "runtime actor stopped", false))?
}

mod commands {
    use super::*;
    #[tauri::command]
    pub async fn config(state: tauri::State<'_, RuntimeState>) -> Result<DeviceConfig, AppError> {
        dispatch(state.0.clone(), |reply| ActorRequest::Config { reply }).await
    }
    #[tauri::command]
    pub async fn capabilities(
        state: tauri::State<'_, RuntimeState>,
    ) -> Result<DeviceCapabilities, AppError> {
        dispatch(state.0.clone(), |reply| ActorRequest::Capabilities {
            reply,
        })
        .await
    }
    pub(super) fn settings_path(app: &tauri::AppHandle) -> Result<std::path::PathBuf, AppError> {
        app.path()
            .app_config_dir()
            .map(|dir| dir.join("console-v2-settings.json"))
            .map_err(|error| app_error("CONFIG_PATH", error.to_string(), true))
    }
    pub(super) fn read_settings(path: &std::path::Path, fallback: DeviceConfig) -> DeviceConfig {
        std::fs::read(path)
            .ok()
            .and_then(|bytes| serde_json::from_slice::<DeviceConfig>(&bytes).ok())
            .unwrap_or(fallback)
    }

    pub(super) fn load_startup_config(app: &tauri::AppHandle, simulator: bool) -> DeviceConfig {
        let fallback = normalize_config(safe_default_config(), simulator);
        settings_path(app)
            .ok()
            .map(|path| normalize_config(read_settings(&path, fallback.clone()), simulator))
            .unwrap_or(fallback)
    }
    pub(super) fn persist_settings(
        path: &std::path::Path,
        config: &DeviceConfig,
    ) -> Result<(), AppError> {
        let parent = path
            .parent()
            .ok_or_else(|| app_error("CONFIG_PATH", "invalid app config path", false))?;
        std::fs::create_dir_all(parent)
            .map_err(|error| app_error("CONFIG_WRITE", error.to_string(), true))?;
        let temporary = path.with_extension("json.tmp");
        let bytes = serde_json::to_vec_pretty(config)
            .map_err(|error| app_error("CONFIG_WRITE", error.to_string(), false))?;
        std::fs::write(&temporary, bytes)
            .map_err(|error| app_error("CONFIG_WRITE", error.to_string(), true))?;
        if path.exists() {
            std::fs::remove_file(path)
                .map_err(|error| app_error("CONFIG_WRITE", error.to_string(), true))?;
        }
        std::fs::rename(&temporary, path)
            .map_err(|error| app_error("CONFIG_WRITE", error.to_string(), true))
    }
    #[tauri::command]
    pub async fn settings_load(
        app: tauri::AppHandle,
        state: tauri::State<'_, RuntimeState>,
    ) -> Result<DeviceConfig, AppError> {
        let path = settings_path(&app)?;
        let fallback = dispatch(state.0.clone(), |reply| ActorRequest::Config { reply }).await?;
        Ok(read_settings(&path, fallback))
    }
    #[tauri::command]
    pub async fn settings_save(
        app: tauri::AppHandle,
        config: DeviceConfig,
    ) -> Result<(), AppError> {
        let path = settings_path(&app)?;
        persist_settings(&path, &config)
    }
    #[tauri::command]
    pub async fn sidecar_self_check(
        state: tauri::State<'_, RuntimeState>,
    ) -> Result<SidecarCheck, AppError> {
        let info = state.0.sidecar_info();
        match SidecarProcessManager::new(info.process.clone()).probe() {
            Ok(()) => Ok(SidecarCheck {
                ok: true,
                message: if info.simulator {
                    "模拟 sidecar 已就绪"
                } else {
                    "sidecar 可执行文件与协议管道正常"
                }
                .into(),
                detail: Some(format!(
                    "{}；仅完成启动/关闭自检，硬件仍未连接且未完成 O6 实机验收",
                    info.selected_path
                        .as_deref()
                        .map(|path| path.display().to_string())
                        .unwrap_or_else(|| "未解析到安装包 sidecar".into())
                )),
            }),
            Err(error) => Ok(SidecarCheck {
                ok: false,
                message: if info.simulator {
                    "模拟 sidecar 不可用"
                } else {
                    "sidecar 不可用"
                }
                .into(),
                detail: Some(format!(
                    "{}；点击连接时将返回可解释错误。{}候选路径：{}",
                    error,
                    if info.simulator {
                        "显式开发模拟模式。"
                    } else {
                        ""
                    },
                    info.process.program.display()
                )),
            }),
        }
    }
    #[tauri::command]
    pub async fn connection(
        state: tauri::State<'_, RuntimeState>,
    ) -> Result<ConnectionSnapshot, AppError> {
        dispatch(state.0.clone(), |reply| ActorRequest::Connection { reply }).await
    }
    #[tauri::command]
    pub async fn connect(
        state: tauri::State<'_, RuntimeState>,
    ) -> Result<ConnectionSnapshot, AppError> {
        dispatch(state.0.clone(), |reply| ActorRequest::Connect { reply }).await
    }
    #[tauri::command]
    pub async fn disconnect(
        state: tauri::State<'_, RuntimeState>,
    ) -> Result<ConnectionSnapshot, AppError> {
        dispatch(state.0.clone(), |reply| ActorRequest::Disconnect { reply }).await
    }
    #[tauri::command]
    pub async fn reconnect(
        state: tauri::State<'_, RuntimeState>,
    ) -> Result<ConnectionSnapshot, AppError> {
        dispatch(state.0.clone(), |reply| ActorRequest::Reconnect { reply }).await
    }
    #[tauri::command]
    pub async fn set_joint_target(
        state: tauri::State<'_, RuntimeState>,
        command: JointTargetCommand,
    ) -> Result<(), AppError> {
        dispatch(state.0.clone(), |reply| ActorRequest::Submit {
            command,
            reply,
        })
        .await
    }
    #[tauri::command]
    pub async fn set_speed(
        state: tauri::State<'_, RuntimeState>,
        command: VectorCommand,
    ) -> Result<(), AppError> {
        dispatch(state.0.clone(), |reply| ActorRequest::SetSpeed {
            command,
            reply,
        })
        .await
    }
    #[tauri::command]
    pub async fn motion_cancel_source(
        state: tauri::State<'_, RuntimeState>,
        source: console_contracts::CommandSource,
    ) -> Result<(), AppError> {
        dispatch(state.0.clone(), |reply| ActorRequest::CancelMotionSource {
            source,
            reply,
        })
        .await
    }
    #[tauri::command]
    pub async fn set_torque(
        state: tauri::State<'_, RuntimeState>,
        command: VectorCommand,
    ) -> Result<(), AppError> {
        dispatch(state.0.clone(), |reply| ActorRequest::SetTorque {
            command,
            reply,
        })
        .await
    }
    #[tauri::command]
    pub async fn stop_all(state: tauri::State<'_, RuntimeState>) -> Result<(), AppError> {
        state.0.control_state.store(1, Ordering::Release);
        Ok(())
    }
    #[tauri::command]
    pub async fn unlock(state: tauri::State<'_, RuntimeState>) -> Result<(), AppError> {
        state.0.control_state.store(2, Ordering::Release);
        Ok(())
    }
    #[tauri::command]
    pub async fn operation(
        state: tauri::State<'_, RuntimeState>,
    ) -> Result<OperationSnapshot, AppError> {
        dispatch(state.0.clone(), |reply| ActorRequest::Operation { reply }).await
    }
    #[tauri::command]
    pub async fn telemetry_read(
        state: tauri::State<'_, RuntimeState>,
    ) -> Result<TelemetrySnapshot, AppError> {
        dispatch(state.0.clone(), |reply| ActorRequest::ReadTelemetry {
            reply,
        })
        .await
    }
    #[tauri::command]
    pub async fn telemetry_subscribe(
        state: tauri::State<'_, RuntimeState>,
        channel: Channel<TelemetrySnapshot>,
    ) -> Result<(), AppError> {
        dispatch(state.0.clone(), |reply| ActorRequest::SubscribeTelemetry {
            channel,
            reply,
        })
        .await
    }
    #[tauri::command]
    pub async fn telemetry_unsubscribe(
        state: tauri::State<'_, RuntimeState>,
        channel_id: u32,
    ) -> Result<(), AppError> {
        dispatch(state.0.clone(), |reply| {
            ActorRequest::UnsubscribeTelemetry { channel_id, reply }
        })
        .await
    }
    #[tauri::command]
    pub async fn connection_subscribe(
        state: tauri::State<'_, RuntimeState>,
        channel: Channel<ConnectionSnapshot>,
    ) -> Result<(), AppError> {
        dispatch(state.0.clone(), |reply| ActorRequest::SubscribeConnection {
            channel,
            reply,
        })
        .await
    }
    #[tauri::command]
    pub async fn connection_unsubscribe(
        state: tauri::State<'_, RuntimeState>,
        channel_id: u32,
    ) -> Result<(), AppError> {
        dispatch(state.0.clone(), |reply| {
            ActorRequest::UnsubscribeConnection { channel_id, reply }
        })
        .await
    }
    #[tauri::command]
    pub async fn operation_subscribe(
        state: tauri::State<'_, RuntimeState>,
        channel: Channel<OperationSnapshot>,
    ) -> Result<(), AppError> {
        dispatch(state.0.clone(), |reply| ActorRequest::SubscribeOperation {
            channel,
            reply,
        })
        .await
    }
    #[tauri::command]
    pub async fn operation_unsubscribe(
        state: tauri::State<'_, RuntimeState>,
        channel_id: u32,
    ) -> Result<(), AppError> {
        dispatch(state.0.clone(), |reply| {
            ActorRequest::UnsubscribeOperation { channel_id, reply }
        })
        .await
    }
    #[tauri::command]
    pub async fn action_list(
        state: tauri::State<'_, RuntimeState>,
    ) -> Result<Vec<console_contracts::ActionRecording>, AppError> {
        dispatch(state.0.clone(), |reply| ActorRequest::ActionList { reply }).await
    }
    #[tauri::command]
    pub async fn action_delete(
        state: tauri::State<'_, RuntimeState>,
        id: String,
    ) -> Result<(), AppError> {
        dispatch(state.0.clone(), |reply| ActorRequest::ActionDelete {
            id,
            reply,
        })
        .await
    }
    #[tauri::command]
    pub async fn action_start_recording(
        state: tauri::State<'_, RuntimeState>,
        name: String,
    ) -> Result<(), AppError> {
        dispatch(state.0.clone(), |reply| {
            ActorRequest::ActionStartRecording { name, reply }
        })
        .await
    }
    #[tauri::command]
    pub async fn action_pause_recording(
        state: tauri::State<'_, RuntimeState>,
    ) -> Result<(), AppError> {
        dispatch(state.0.clone(), |reply| {
            ActorRequest::ActionPauseRecording { reply }
        })
        .await
    }
    #[tauri::command]
    pub async fn action_resume_recording(
        state: tauri::State<'_, RuntimeState>,
    ) -> Result<(), AppError> {
        dispatch(state.0.clone(), |reply| {
            ActorRequest::ActionResumeRecording { reply }
        })
        .await
    }
    #[tauri::command]
    pub async fn action_finish_recording(
        state: tauri::State<'_, RuntimeState>,
    ) -> Result<(), AppError> {
        dispatch(state.0.clone(), |reply| {
            ActorRequest::ActionFinishRecording { reply }
        })
        .await
    }
    #[tauri::command]
    pub async fn action_cancel_recording(
        state: tauri::State<'_, RuntimeState>,
    ) -> Result<(), AppError> {
        dispatch(state.0.clone(), |reply| {
            ActorRequest::ActionCancelRecording { reply }
        })
        .await
    }
    #[tauri::command]
    pub async fn action_play(
        state: tauri::State<'_, RuntimeState>,
        id: String,
        speed: f32,
        loop_enabled: bool,
        loop_count: Option<u32>,
    ) -> Result<(), AppError> {
        dispatch(state.0.clone(), |reply| ActorRequest::ActionPlay {
            id,
            speed,
            loop_enabled,
            loop_count,
            reply,
        })
        .await
    }
    #[tauri::command]
    pub async fn action_pause(state: tauri::State<'_, RuntimeState>) -> Result<(), AppError> {
        dispatch(state.0.clone(), |reply| ActorRequest::ActionPause { reply }).await
    }
    #[tauri::command]
    pub async fn action_resume(state: tauri::State<'_, RuntimeState>) -> Result<(), AppError> {
        dispatch(state.0.clone(), |reply| ActorRequest::ActionResume {
            reply,
        })
        .await
    }
    #[tauri::command]
    pub async fn action_stop(state: tauri::State<'_, RuntimeState>) -> Result<(), AppError> {
        dispatch(state.0.clone(), |reply| ActorRequest::ActionStop { reply }).await
    }
    #[tauri::command]
    pub async fn action_subscribe(
        state: tauri::State<'_, RuntimeState>,
        channel: Channel<ActionStateEvent>,
    ) -> Result<(), AppError> {
        dispatch(state.0.clone(), |reply| ActorRequest::SubscribeAction {
            channel,
            reply,
        })
        .await
    }
    #[tauri::command]
    pub async fn action_unsubscribe(
        state: tauri::State<'_, RuntimeState>,
        channel_id: u32,
    ) -> Result<(), AppError> {
        dispatch(state.0.clone(), |reply| ActorRequest::UnsubscribeAction {
            channel_id,
            reply,
        })
        .await
    }
    #[tauri::command]
    pub async fn grasp_presets(
        state: tauri::State<'_, RuntimeState>,
    ) -> Result<Vec<console_contracts::GraspPreset>, AppError> {
        dispatch(state.0.clone(), |reply| ActorRequest::GraspPresets {
            reply,
        })
        .await
    }
    #[tauri::command]
    pub async fn grasp_calibrate(state: tauri::State<'_, RuntimeState>) -> Result<(), AppError> {
        dispatch(state.0.clone(), |reply| ActorRequest::GraspCalibrate {
            reply,
        })
        .await
    }
    #[tauri::command]
    pub async fn grasp_complete_calibration(
        state: tauri::State<'_, RuntimeState>,
    ) -> Result<(), AppError> {
        dispatch(state.0.clone(), |reply| {
            ActorRequest::GraspCompleteCalibration { reply }
        })
        .await
    }
    #[tauri::command]
    pub async fn grasp_approach(state: tauri::State<'_, RuntimeState>) -> Result<(), AppError> {
        dispatch(state.0.clone(), |reply| ActorRequest::GraspApproach {
            reply,
        })
        .await
    }
    #[tauri::command]
    pub async fn grasp_start(
        state: tauri::State<'_, RuntimeState>,
        degraded: bool,
    ) -> Result<(), AppError> {
        dispatch(state.0.clone(), |reply| ActorRequest::GraspStart {
            degraded,
            reply,
        })
        .await
    }
    #[tauri::command]
    pub async fn grasp_release(state: tauri::State<'_, RuntimeState>) -> Result<(), AppError> {
        dispatch(state.0.clone(), |reply| ActorRequest::GraspRelease {
            reply,
        })
        .await
    }
    #[tauri::command]
    pub async fn grasp_abort(state: tauri::State<'_, RuntimeState>) -> Result<(), AppError> {
        dispatch(state.0.clone(), |reply| ActorRequest::GraspAbort { reply }).await
    }
    #[tauri::command]
    pub async fn grasp_subscribe(
        state: tauri::State<'_, RuntimeState>,
        channel: Channel<GraspStateEvent>,
    ) -> Result<(), AppError> {
        dispatch(state.0.clone(), |reply| ActorRequest::SubscribeGrasp {
            channel,
            reply,
        })
        .await
    }
    #[tauri::command]
    pub async fn grasp_unsubscribe(
        state: tauri::State<'_, RuntimeState>,
        channel_id: u32,
    ) -> Result<(), AppError> {
        dispatch(state.0.clone(), |reply| ActorRequest::UnsubscribeGrasp {
            channel_id,
            reply,
        })
        .await
    }
    #[tauri::command]
    pub async fn logs_list(
        state: tauri::State<'_, RuntimeState>,
        limit: usize,
    ) -> Result<Vec<console_contracts::StructuredLogEntry>, AppError> {
        dispatch(state.0.clone(), |reply| ActorRequest::Logs { limit, reply }).await
    }
}

fn now_ms() -> u64 {
    static START: std::sync::OnceLock<std::time::Instant> = std::sync::OnceLock::new();
    START
        .get_or_init(std::time::Instant::now)
        .elapsed()
        .as_millis() as u64
}

pub fn run() {
    let shutdown_slot: Arc<std::sync::Mutex<Option<RuntimeHandle>>> =
        Arc::new(std::sync::Mutex::new(None));
    let shutdown_event = Arc::clone(&shutdown_slot);
    tauri::Builder::default()
        .setup(move |app| {
            let simulator = simulator_enabled();
            let config = commands::load_startup_config(app.handle(), simulator);
            let explicit = std::env::var_os("LINKERHAND_SIDECAR_PATH").map(PathBuf::from);
            let (process, selected_path) = sidecar_process(explicit, simulator);
            let handle = spawn_runtime(config, process, simulator, selected_path);
            app.manage(RuntimeState(handle.clone()));
            *shutdown_slot.lock().expect("shutdown slot poisoned") = Some(handle);
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            commands::config,
            commands::capabilities,
            commands::settings_load,
            commands::settings_save,
            commands::sidecar_self_check,
            commands::connection,
            commands::connect,
            commands::disconnect,
            commands::reconnect,
            commands::set_joint_target,
            commands::set_speed,
            commands::set_torque,
            commands::motion_cancel_source,
            commands::stop_all,
            commands::unlock,
            commands::operation,
            commands::telemetry_read,
            commands::telemetry_subscribe,
            commands::telemetry_unsubscribe,
            commands::connection_subscribe,
            commands::connection_unsubscribe,
            commands::operation_subscribe,
            commands::operation_unsubscribe,
            commands::action_list,
            commands::action_delete,
            commands::action_start_recording,
            commands::action_pause_recording,
            commands::action_resume_recording,
            commands::action_finish_recording,
            commands::action_cancel_recording,
            commands::action_play,
            commands::action_pause,
            commands::action_resume,
            commands::action_stop,
            commands::action_subscribe,
            commands::action_unsubscribe,
            commands::grasp_presets,
            commands::grasp_calibrate,
            commands::grasp_complete_calibration,
            commands::grasp_approach,
            commands::grasp_start,
            commands::grasp_release,
            commands::grasp_abort,
            commands::grasp_subscribe,
            commands::grasp_unsubscribe,
            commands::logs_list
        ])
        .build(tauri::generate_context!())
        .expect("error while building LinkerHand Console")
        .run(move |_app_handle, event| {
            if let tauri::RunEvent::Exit = event {
                if let Some(handle) = shutdown_event
                    .lock()
                    .expect("shutdown slot poisoned")
                    .take()
                {
                    handle.shutdown();
                }
            }
        });
}

#[cfg(test)]
mod tests {
    use super::*;
    use console_contracts::{CommandSource, CURRENT_SCHEMA_VERSION};
    use device_adapter_api::DeviceAdapter;
    use std::sync::{Arc, Mutex};
    use std::time::Duration;

    #[test]
    fn release_defaults_never_select_fake_transport_or_python() {
        let config = normalize_config(safe_default_config(), false);
        assert!(matches!(
            config.transport,
            console_contracts::Transport::Can { ref channel }
                if channel.eq_ignore_ascii_case("PCAN_USBBUS1")
        ));
        let (process, selected) = sidecar_process(
            Some(PathBuf::from("C:/missing/linkerhand-sidecar.exe")),
            false,
        );
        assert!(selected.is_none());
        assert_ne!(process.program, PathBuf::from("python"));
        assert!(!process.args.iter().any(|arg| arg == "--fake"));
    }

    #[test]
    fn simulator_is_explicit_and_forces_fake_transport() {
        let config = normalize_config(safe_default_config(), true);
        assert!(matches!(
            config.transport,
            console_contracts::Transport::Can { ref channel }
                if channel.eq_ignore_ascii_case("fake")
        ));
        let (process, selected) = sidecar_process(None, true);
        assert!(selected.is_none());
        assert_eq!(process.program, PathBuf::from("python"));
        assert!(process.args.iter().any(|arg| arg == "--fake"));
    }

    #[test]
    fn explicit_sidecar_path_has_priority_over_install_layout() {
        let root = std::env::temp_dir().join(format!(
            "linkerhand-console-v2-sidecar-candidates-{}",
            std::process::id()
        ));
        let explicit = root.join("injected-sidecar.exe");
        let portable = root.join("sidecar");
        std::fs::create_dir_all(&portable).unwrap();
        std::fs::write(&explicit, b"test").unwrap();
        std::fs::write(portable.join("linkerhand-sidecar.exe"), b"test").unwrap();
        let selected = resolve_sidecar_path(Some(explicit.clone()), vec![root.clone()]);
        assert_eq!(selected, Some(explicit));
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn missing_release_sidecar_is_deferred_until_connect() {
        let (process, selected) = sidecar_process(
            Some(std::env::temp_dir().join(format!(
                "linkerhand-console-v2-missing-{}.exe",
                std::process::id()
            ))),
            false,
        );
        assert!(selected.is_none());
        let manager = SidecarProcessManager::new(process);
        let error = manager
            .probe()
            .expect_err("missing sidecar must fail only when probed/connect");
        assert!(error.to_string().contains("sidecar process failed"));
    }

    #[test]
    fn settings_replace_existing_file_and_recover_from_corruption() {
        let directory = std::env::temp_dir().join(format!(
            "linkerhand-console-v2-settings-{}",
            std::process::id()
        ));
        let path = directory.join("console-v2-settings.json");
        let first = DeviceConfig::new("settings-1", "settings O6");
        let mut second = first.clone();
        second.device_id = "settings-2".into();
        commands::persist_settings(&path, &first).unwrap();
        commands::persist_settings(&path, &second).unwrap();
        assert_eq!(
            commands::read_settings(&path, first.clone()).device_id,
            "settings-2"
        );
        std::fs::write(&path, b"{not-json").unwrap();
        assert_eq!(
            commands::read_settings(&path, first.clone()).device_id,
            "settings-1"
        );
        let _ = std::fs::remove_dir_all(directory);
    }

    struct CapturingAdapter {
        inner: device_simulator::DeviceSimulator,
        writes: Arc<Mutex<Vec<JointTargetCommand>>>,
    }
    impl DeviceAdapter for CapturingAdapter {
        fn id(&self) -> &str {
            self.inner.id()
        }
        fn connect(&mut self) -> device_adapter_api::AdapterResult<DeviceCapabilities> {
            self.inner.connect()
        }
        fn disconnect(&mut self) -> device_adapter_api::AdapterResult<()> {
            self.inner.disconnect()
        }
        fn is_connected(&self) -> bool {
            self.inner.is_connected()
        }
        fn capabilities(&self) -> Option<&DeviceCapabilities> {
            self.inner.capabilities()
        }
        fn send_joint_target(
            &mut self,
            command: &JointTargetCommand,
        ) -> device_adapter_api::AdapterResult<()> {
            self.writes.lock().unwrap().push(command.clone());
            self.inner.send_joint_target(command)
        }
        fn read_telemetry(
            &mut self,
            now: u64,
        ) -> device_adapter_api::AdapterResult<TelemetrySnapshot> {
            self.inner.read_telemetry(now)
        }
        fn stop(&mut self) -> device_adapter_api::AdapterResult<()> {
            self.inner.stop()
        }
        fn unlock(&mut self) -> device_adapter_api::AdapterResult<()> {
            self.inner.unlock()
        }
        fn shutdown(&mut self) -> device_adapter_api::AdapterResult<()> {
            self.inner.shutdown()
        }
    }

    fn spawn_capturing_runtime() -> (RuntimeHandle, Arc<Mutex<Vec<JointTargetCommand>>>) {
        let config = DeviceConfig::new("capture", "capture O6");
        let writes = Arc::new(Mutex::new(Vec::new()));
        let mut runtime = AppRuntime::new(config, adaptive_grasp::Profile::O6);
        runtime.install_adapter(Box::new(CapturingAdapter {
            inner: device_simulator::DeviceSimulator::new("capture", 6),
            writes: writes.clone(),
        }));
        let (tx, rx) = mpsc::sync_channel(128);
        let control_state = Arc::new(std::sync::atomic::AtomicU8::new(0));
        let shutdown_requested = Arc::new(AtomicBool::new(false));
        let stopped = Arc::new(AtomicBool::new(false));
        let actor_control = control_state.clone();
        let actor_shutdown = shutdown_requested.clone();
        let actor_stopped = stopped.clone();
        thread::Builder::new()
            .name("capture-runtime-actor".into())
            .spawn(move || {
                RuntimeActor {
                    runtime,
                    rx,
                    telemetry_channels: Vec::new(),
                    connection_channels: Vec::new(),
                    operation_channels: Vec::new(),
                    action_channels: Vec::new(),
                    grasp_channels: Vec::new(),
                    latest: None,
                    control_state: actor_control,
                    shutdown_requested: actor_shutdown,
                    applied_control: 0,
                    stopped: actor_stopped,
                }
                .run()
            })
            .unwrap();
        (
            RuntimeHandle {
                tx,
                control_state,
                shutdown_requested,
                stopped,
                sidecar: Arc::new(SidecarRuntimeInfo {
                    process: ProcessConfig::fake("unused.py"),
                    simulator: true,
                    selected_path: None,
                }),
            },
            writes,
        )
    }

    fn command(id: &str, value: f64, final_command: bool) -> JointTargetCommand {
        JointTargetCommand {
            schema_version: CURRENT_SCHEMA_VERSION,
            command_id: id.into(),
            source: CommandSource::Manual,
            positions: vec![value; 6],
            duration_ms: None,
            final_command,
        }
    }

    fn source_command(
        source: CommandSource,
        id: &str,
        value: f64,
        final_command: bool,
    ) -> JointTargetCommand {
        JointTargetCommand {
            schema_version: CURRENT_SCHEMA_VERSION,
            command_id: id.into(),
            source,
            positions: vec![value; 6],
            duration_ms: None,
            final_command,
        }
    }

    #[test]
    fn actor_keeps_continuous_vision_source_and_sends_latest_at_20hz() {
        let (handle, writes) = spawn_capturing_runtime();
        let runtime = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .unwrap();
        runtime
            .block_on(dispatch(handle.clone(), |reply| ActorRequest::Connect {
                reply,
            }))
            .unwrap();
        runtime
            .block_on(dispatch(handle.clone(), |reply| ActorRequest::Submit {
                command: source_command(CommandSource::Vision, "vision-old", 0.1, false),
                reply,
            }))
            .unwrap();
        runtime
            .block_on(dispatch(handle.clone(), |reply| ActorRequest::Submit {
                command: source_command(CommandSource::Vision, "vision-latest", 0.9, false),
                reply,
            }))
            .unwrap();
        std::thread::sleep(Duration::from_millis(120));
        let operation = runtime
            .block_on(dispatch(handle.clone(), |reply| ActorRequest::Operation {
                reply,
            }))
            .unwrap();
        assert_eq!(operation.state, console_contracts::OperationState::Running);
        let writes = writes.lock().unwrap();
        assert!(writes
            .iter()
            .any(|command| command.command_id == "vision-latest"));
        assert!(
            writes.len() <= 2,
            "continuous input must not send every browser frame"
        );
        runtime
            .block_on(dispatch(handle.clone(), |reply| {
                ActorRequest::CancelMotionSource {
                    source: CommandSource::Vision,
                    reply,
                }
            }))
            .unwrap();
        let operation = runtime
            .block_on(dispatch(handle.clone(), |reply| ActorRequest::Operation {
                reply,
            }))
            .unwrap();
        assert_eq!(operation.state, console_contracts::OperationState::Idle);
        handle.shutdown();
    }

    #[test]
    fn actor_broadcasts_continuous_frames_and_stop_unlocks() {
        let handle = spawn_runtime(
            DeviceConfig::new("sim-1", "演示机械手 O6"),
            ProcessConfig::fake(
                PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                    .join("../sidecar/linkerhand-bridge/main.py"),
            ),
            true,
            None,
        );
        let runtime = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .unwrap();
        runtime
            .block_on(dispatch(handle.clone(), |reply| ActorRequest::Connect {
                reply,
            }))
            .unwrap();
        let (frames_tx, frames_rx) = mpsc::channel();
        let channel = Channel::new(move |body| {
            if let tauri::ipc::InvokeResponseBody::Json(json) = body {
                if let Ok(value) = serde_json::from_str::<TelemetrySnapshot>(&json) {
                    let _ = frames_tx.send(value);
                }
            }
            Ok(())
        });
        runtime
            .block_on(dispatch(handle.clone(), |reply| {
                ActorRequest::SubscribeTelemetry { channel, reply }
            }))
            .unwrap();
        let first = frames_rx.recv_timeout(Duration::from_secs(2)).unwrap();
        let second = frames_rx.recv_timeout(Duration::from_secs(2)).unwrap();
        assert!(second.sequence > first.sequence);
        runtime
            .block_on(dispatch(handle.clone(), |reply| ActorRequest::Submit {
                command: command("first", 0.1, false),
                reply,
            }))
            .unwrap();
        runtime
            .block_on(dispatch(handle.clone(), |reply| ActorRequest::Submit {
                command: command("latest", 0.8, false),
                reply,
            }))
            .unwrap();
        std::thread::sleep(Duration::from_millis(100));
        let latest = runtime
            .block_on(dispatch(handle.clone(), |reply| {
                ActorRequest::ReadTelemetry { reply }
            }))
            .unwrap();
        assert_eq!(latest.positions, vec![0.8; 6]);
        runtime
            .block_on(dispatch(handle.clone(), |reply| ActorRequest::Submit {
                command: command("final", 0.9, true),
                reply,
            }))
            .unwrap();
        handle.control_state.store(1, Ordering::Release);
        std::thread::sleep(Duration::from_millis(30));
        let stopped = runtime.block_on(dispatch(handle.clone(), |reply| ActorRequest::Submit {
            command: command("blocked", 0.2, false),
            reply,
        }));
        assert!(stopped.is_err());
        handle.control_state.store(2, Ordering::Release);
        std::thread::sleep(Duration::from_millis(30));
        runtime
            .block_on(dispatch(handle.clone(), |reply| ActorRequest::Submit {
                command: command("after-unlock", 0.3, true),
                reply,
            }))
            .unwrap();
        let started = std::time::Instant::now();
        handle.shutdown();
        assert!(started.elapsed() < Duration::from_secs(2));
    }

    #[test]
    fn atomic_shutdown_signal_survives_a_full_command_queue() {
        let handle = spawn_runtime(
            DeviceConfig::new("sim-1", "演示机械手 O6"),
            ProcessConfig::fake(
                PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                    .join("../sidecar/linkerhand-bridge/main.py"),
            ),
            true,
            None,
        );
        let mut filled = 0;
        for _ in 0..256 {
            let (reply, _receiver) = tokio::sync::oneshot::channel();
            if handle.tx.try_send(ActorRequest::Config { reply }).is_ok() {
                filled += 1;
            } else {
                break;
            }
        }
        assert!(filled > 0);
        handle.control_state.store(1, Ordering::Release);
        std::thread::sleep(Duration::from_millis(30));
        let runtime = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .unwrap();
        let command = command("saturated-stop", 0.2, false);
        let stopped = runtime.block_on(dispatch(handle.clone(), |reply| ActorRequest::Submit {
            command,
            reply,
        }));
        assert!(stopped.is_err());
        let started = std::time::Instant::now();
        handle.shutdown();
        assert!(started.elapsed() < Duration::from_secs(2));
        assert!(handle.stopped.load(Ordering::Acquire));
    }

    #[test]
    fn actor_records_and_replays_through_motion_engine() {
        let (handle, writes) = spawn_capturing_runtime();
        let runtime = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .unwrap();
        runtime
            .block_on(dispatch(handle.clone(), |reply| ActorRequest::Connect {
                reply,
            }))
            .unwrap();
        let (frames_tx, frames_rx) = mpsc::channel();
        let telemetry_channel = Channel::new(move |body| {
            if let tauri::ipc::InvokeResponseBody::Json(json) = body {
                if let Ok(value) = serde_json::from_str::<TelemetrySnapshot>(&json) {
                    let _ = frames_tx.send(value);
                }
            }
            Ok(())
        });
        runtime
            .block_on(dispatch(handle.clone(), |reply| {
                ActorRequest::SubscribeTelemetry {
                    channel: telemetry_channel,
                    reply,
                }
            }))
            .unwrap();
        let _ = frames_rx.recv_timeout(Duration::from_secs(2)).unwrap();
        runtime
            .block_on(dispatch(handle.clone(), |reply| {
                ActorRequest::ActionStartRecording {
                    name: "actor action".into(),
                    reply,
                }
            }))
            .unwrap();
        runtime
            .block_on(dispatch(handle.clone(), |reply| ActorRequest::Submit {
                command: command("recorded", 0.77, true),
                reply,
            }))
            .unwrap();
        writes.lock().unwrap().clear();
        runtime
            .block_on(dispatch(handle.clone(), |reply| {
                ActorRequest::ActionFinishRecording { reply }
            }))
            .unwrap();
        let actions = runtime
            .block_on(dispatch(handle.clone(), |reply| ActorRequest::ActionList {
                reply,
            }))
            .unwrap();
        let recorded = actions
            .iter()
            .find(|item| item.name == "actor action")
            .expect("recorded action is retained in session");
        runtime
            .block_on(dispatch(handle.clone(), |reply| ActorRequest::ActionPlay {
                id: recorded.id.clone(),
                speed: 1.0,
                loop_enabled: false,
                loop_count: None,
                reply,
            }))
            .unwrap();
        std::thread::sleep(Duration::from_millis(120));
        let replay = writes.lock().unwrap().clone();
        assert!(replay.iter().any(|item| {
            item.source == CommandSource::Playback
                && item.positions == vec![0.77; 6]
                && item.final_command
        }));
        let latest = runtime
            .block_on(dispatch(handle.clone(), |reply| {
                ActorRequest::ReadTelemetry { reply }
            }))
            .unwrap();
        assert_eq!(latest.positions, vec![0.77; 6]);
        assert_eq!(latest.raw_position, vec![196; 6]);
        handle.shutdown();
    }

    #[test]
    fn actor_grasp_uses_telemetry_and_stop_clears_controllers() {
        let (handle, writes) = spawn_capturing_runtime();
        let runtime = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .unwrap();
        runtime
            .block_on(dispatch(handle.clone(), |reply| ActorRequest::Connect {
                reply,
            }))
            .unwrap();
        let (events_tx, events_rx) = mpsc::channel();
        let grasp_channel = Channel::new(move |body| {
            if let tauri::ipc::InvokeResponseBody::Json(json) = body {
                if let Ok(value) = serde_json::from_str::<GraspStateEvent>(&json) {
                    let _ = events_tx.send(value);
                }
            }
            Ok(())
        });
        runtime
            .block_on(dispatch(handle.clone(), |reply| {
                ActorRequest::SubscribeGrasp {
                    channel: grasp_channel,
                    reply,
                }
            }))
            .unwrap();
        runtime
            .block_on(dispatch(handle.clone(), |reply| {
                ActorRequest::GraspCalibrate { reply }
            }))
            .unwrap();
        runtime
            .block_on(dispatch(handle.clone(), |reply| {
                ActorRequest::GraspCompleteCalibration { reply }
            }))
            .unwrap();
        runtime
            .block_on(dispatch(handle.clone(), |reply| {
                ActorRequest::GraspApproach { reply }
            }))
            .unwrap();
        runtime
            .block_on(dispatch(handle.clone(), |reply| ActorRequest::GraspStart {
                degraded: true,
                reply,
            }))
            .unwrap();
        let state = events_rx.recv_timeout(Duration::from_secs(2)).unwrap();
        assert!(matches!(
            state.phase.as_str(),
            "calibrating" | "ready" | "approach" | "grasping"
        ));
        std::thread::sleep(Duration::from_millis(120));
        let grasp_writes = writes.lock().unwrap().clone();
        assert!(grasp_writes.iter().any(|item| {
            item.source == CommandSource::Grasp
                && item.positions.len() == 6
                && item.positions.iter().all(|value| value.is_finite())
        }));
        handle.control_state.store(1, Ordering::Release);
        std::thread::sleep(Duration::from_millis(80));
        let writes_after_stop = writes.lock().unwrap().len();
        std::thread::sleep(Duration::from_millis(100));
        assert_eq!(writes.lock().unwrap().len(), writes_after_stop);
        assert!(runtime
            .block_on(dispatch(handle.clone(), |reply| ActorRequest::Submit {
                command: command("after-stop", 0.2, false),
                reply,
            }))
            .is_err());
        handle.shutdown();
    }
}
