//! Tauri assembly only. `RuntimeActor` is the single owner of AppRuntime and
//! the sidecar adapter; IPC commands never hold a mutex while doing I/O.
use app_runtime::AppRuntime;
use console_contracts::{
    AppError, ConnectionSnapshot, DeviceCapabilities, DeviceConfig, JointTargetCommand, LogLevel,
    OperationSnapshot, StructuredLogEntry, TelemetrySnapshot, CURRENT_SCHEMA_VERSION,
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

fn trusted_camera_origin(uri: &str) -> bool {
    [
        "http://tauri.localhost",
        "https://tauri.localhost",
        "tauri://localhost",
        "http://127.0.0.1:1420",
        "http://localhost:1420",
    ]
    .iter()
    .any(|origin| uri == *origin || uri.starts_with(&format!("{origin}/")))
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct CameraPermissionStatus {
    pub state: String,
    pub origin: Option<String>,
    pub detail: Option<String>,
}

#[cfg(windows)]
fn camera_permission_status(
    app: &tauri::AppHandle,
    reset_denied: bool,
) -> Result<CameraPermissionStatus, String> {
    use std::time::Duration;
    use webview2_com::Microsoft::Web::WebView2::Win32::{
        ICoreWebView2Profile4, ICoreWebView2_13, COREWEBVIEW2_PERMISSION_KIND_CAMERA,
        COREWEBVIEW2_PERMISSION_STATE_DEFAULT, COREWEBVIEW2_PERMISSION_STATE_DENY,
    };
    use webview2_com::{
        GetNonDefaultPermissionSettingsCompletedHandler, SetPermissionStateCompletedHandler,
    };
    use windows::core::{Interface, PCWSTR, PWSTR};
    use windows::Win32::System::Com::CoTaskMemFree;

    let Some(window) = app.get_webview_window("main") else {
        return Err("主窗口 WebView 不可用".into());
    };
    let (tx, rx) = mpsc::channel::<Result<CameraPermissionStatus, String>>();
    let with_webview_result = window.with_webview(move |webview| {
        let setup_result = (|| -> Result<(), String> {
            let controller = webview.controller();
            let core_webview = unsafe { controller.CoreWebView2() }
                .map_err(|error| format!("获取 WebView2 失败：{error}"))?;
            let core_webview_13: ICoreWebView2_13 = core_webview
                .cast()
                .map_err(|error| format!("当前 WebView2 不支持 profile API：{error}"))?;
            let profile = unsafe { core_webview_13.Profile() }
                .map_err(|error| format!("获取 WebView2 profile 失败：{error}"))?;
            let profile4: ICoreWebView2Profile4 = profile
                .cast()
                .map_err(|error| format!("当前 WebView2 不支持 profile 权限 API：{error}"))?;
            let callback_tx = tx.clone();
            let callback_profile = profile4.clone();
            let callback = GetNonDefaultPermissionSettingsCompletedHandler::create(Box::new(
                move |completed, settings| {
                    let result = (|| -> Result<(), String> {
                        completed
                            .map_err(|error| format!("查询 WebView2 摄像头权限失败：{error}"))?;
                        let Some(settings) = settings else {
                            callback_tx
                                .send(Ok(CameraPermissionStatus {
                                    state: "default".into(),
                                    origin: None,
                                    detail: None,
                                }))
                                .map_err(|_| "摄像头权限查询结果接收方已关闭".to_string())?;
                            return Ok(());
                        };
                        let mut count = 0_u32;
                        unsafe { settings.Count(&mut count) }
                            .map_err(|error| format!("读取 WebView2 权限数量失败：{error}"))?;
                        for index in 0..count {
                            let setting = unsafe { settings.GetValueAtIndex(index) }
                                .map_err(|error| format!("读取 WebView2 权限条目失败：{error}"))?;
                            let mut kind = Default::default();
                            unsafe { setting.PermissionKind(&mut kind) }
                                .map_err(|error| format!("读取 WebView2 权限类型失败：{error}"))?;
                            if kind != COREWEBVIEW2_PERMISSION_KIND_CAMERA {
                                continue;
                            }
                            let mut raw_origin = PWSTR::null();
                            unsafe { setting.PermissionOrigin(&mut raw_origin) }
                                .map_err(|error| format!("读取 WebView2 权限来源失败：{error}"))?;
                            let origin_result = unsafe { raw_origin.to_string() };
                            unsafe {
                                CoTaskMemFree(Some(raw_origin.0 as *const _));
                            }
                            let origin = origin_result
                                .map_err(|error| format!("解析 WebView2 权限来源失败：{error}"))?;
                            if !trusted_camera_origin(&origin) {
                                continue;
                            }
                            let mut state = Default::default();
                            unsafe { setting.PermissionState(&mut state) }.map_err(|error| {
                                format!("读取 WebView2 摄像头权限状态失败：{error}")
                            })?;
                            let state_name = camera_permission_state_name(state);
                            if reset_denied && state == COREWEBVIEW2_PERMISSION_STATE_DENY {
                                let origin_units: Vec<u16> =
                                    origin.encode_utf16().chain(std::iter::once(0)).collect();
                                let origin_ptr = PCWSTR(origin_units.as_ptr());
                                let callback_origin = origin.clone();
                                let tx = callback_tx.clone();
                                let reset_callback = SetPermissionStateCompletedHandler::create(
                                    Box::new(move |result| {
                                        let status = result
                                            .map(|_| CameraPermissionStatus {
                                                state: "default".into(),
                                                origin: Some(callback_origin),
                                                detail: None,
                                            })
                                            .map_err(|error| {
                                                format!("重置 WebView2 摄像头权限失败：{error}")
                                            });
                                        tx.send(status)
                                            .map_err(|_| windows::core::Error::from_win32())?;
                                        Ok(())
                                    }),
                                );
                                unsafe {
                                    callback_profile.SetPermissionState(
                                        COREWEBVIEW2_PERMISSION_KIND_CAMERA,
                                        origin_ptr,
                                        COREWEBVIEW2_PERMISSION_STATE_DEFAULT,
                                        &reset_callback,
                                    )
                                }
                                .map_err(|error| {
                                    format!("提交 WebView2 摄像头权限重置失败：{error}")
                                })?;
                            } else {
                                callback_tx
                                    .send(Ok(CameraPermissionStatus {
                                        state: state_name.into(),
                                        origin: Some(origin),
                                        detail: None,
                                    }))
                                    .map_err(|_| "摄像头权限查询结果接收方已关闭".to_string())?;
                            }
                            return Ok(());
                        }
                        callback_tx
                            .send(Ok(CameraPermissionStatus {
                                state: "default".into(),
                                origin: None,
                                detail: None,
                            }))
                            .map_err(|_| "摄像头权限查询结果接收方已关闭".to_string())?;
                        Ok(())
                    })();
                    if let Err(error) = result {
                        let _ = callback_tx.send(Err(error));
                    }
                    Ok(())
                },
            ));
            unsafe { profile4.GetNonDefaultPermissionSettings(&callback) }
                .map_err(|error| format!("查询 WebView2 摄像头权限失败：{error}"))?;
            Ok(())
        })();
        if let Err(error) = setup_result {
            let _ = tx.send(Err(error));
        }
    });
    with_webview_result.map_err(|error| format!("访问主窗口 WebView 失败：{error}"))?;
    rx.recv_timeout(Duration::from_secs(5))
        .map_err(|_| "等待 WebView2 摄像头权限结果超时".to_string())?
}

#[cfg(not(windows))]
fn camera_permission_status(
    _app: &tauri::AppHandle,
    _reset_denied: bool,
) -> Result<CameraPermissionStatus, String> {
    Err("当前平台没有 WebView2 摄像头权限 API".into())
}

#[cfg(windows)]
fn camera_permission_state_name(
    state: webview2_com::Microsoft::Web::WebView2::Win32::COREWEBVIEW2_PERMISSION_STATE,
) -> &'static str {
    use webview2_com::Microsoft::Web::WebView2::Win32::{
        COREWEBVIEW2_PERMISSION_STATE_ALLOW, COREWEBVIEW2_PERMISSION_STATE_DEFAULT,
        COREWEBVIEW2_PERMISSION_STATE_DENY,
    };
    if state == COREWEBVIEW2_PERMISSION_STATE_DENY {
        "deny"
    } else if state == COREWEBVIEW2_PERMISSION_STATE_ALLOW {
        "allow"
    } else if state == COREWEBVIEW2_PERMISSION_STATE_DEFAULT {
        "default"
    } else {
        "unknown"
    }
}

#[cfg(windows)]
fn install_camera_permission_handler(app: &tauri::AppHandle) {
    use std::ffi::c_void;
    use webview2_com::Microsoft::Web::WebView2::Win32::{
        COREWEBVIEW2_PERMISSION_KIND_CAMERA, COREWEBVIEW2_PERMISSION_KIND_MICROPHONE,
        COREWEBVIEW2_PERMISSION_KIND_UNKNOWN_PERMISSION, COREWEBVIEW2_PERMISSION_STATE_ALLOW,
        COREWEBVIEW2_PERMISSION_STATE_DENY,
    };
    use webview2_com::PermissionRequestedEventHandler;
    use windows::core::PWSTR;
    use windows::Win32::System::Com::CoTaskMemFree;

    let Some(window) = app.get_webview_window("main") else {
        eprintln!("camera permission handler: main webview is not available");
        return;
    };
    if let Err(error) = window.with_webview(|webview| {
        let controller = webview.controller();
        let Ok(core_webview) = (unsafe { controller.CoreWebView2() }) else {
            eprintln!("camera permission handler: WebView2 handle is unavailable");
            return;
        };
        let mut token = 0_i64;
        let result = unsafe {
            core_webview.add_PermissionRequested(
                &PermissionRequestedEventHandler::create(Box::new(|_, args| {
                    let Some(args) = args else {
                        return Ok(());
                    };
                    let mut kind = Default::default();
                    args.PermissionKind(&mut kind)?;

                    if kind == COREWEBVIEW2_PERMISSION_KIND_CAMERA {
                        let mut raw_uri = PWSTR::null();
                        args.Uri(&mut raw_uri)?;
                        let uri_result = raw_uri.to_string();
                        CoTaskMemFree(Some(raw_uri.0 as *const c_void));
                        let uri = uri_result?;
                        let state = if trusted_camera_origin(&uri) {
                            COREWEBVIEW2_PERMISSION_STATE_ALLOW
                        } else {
                            COREWEBVIEW2_PERMISSION_STATE_DENY
                        };
                        args.SetState(state)?;
                    } else if kind == COREWEBVIEW2_PERMISSION_KIND_MICROPHONE
                        || kind == COREWEBVIEW2_PERMISSION_KIND_UNKNOWN_PERMISSION
                    {
                        // The console never needs microphone or unknown permissions.
                        args.SetState(COREWEBVIEW2_PERMISSION_STATE_DENY)?;
                    }
                    Ok(())
                })),
                &mut token,
            )
        };
        if let Err(error) = result {
            eprintln!("camera permission handler registration failed: {error}");
        }
    }) {
        eprintln!("camera permission handler setup failed: {error}");
    }
}

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
    /// Per-joint adaptive states for the UI (idle/coarse/fine/candidate/confirmed/frozen/limit/error).
    joints: Vec<GraspJointEvent>,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct GraspJointEvent {
    index: usize,
    state: String,
    contact_score: f32,
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
#[derive(Clone, Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct LogRecord {
    level: LogLevel,
    event: String,
    message: String,
    #[serde(default)]
    fields: serde_json::Value,
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
    ActionPlayFrames {
        id: String,
        name: String,
        frames: Vec<JointTargetCommand>,
        speed: f32,
        loop_enabled: bool,
        loop_count: Option<u32>,
        direction: String,
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
        preset: String,
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
    RecordLog {
        entry: LogRecord,
        reply: Reply<()>,
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
    simulator: bool,
    log_sequence: u64,
    /// Last telemetry sampling error, for change-aware logging.
    telemetry_error: Option<String>,
}
impl RuntimeActor {
    fn log(
        &mut self,
        monotonic_time_ms: u64,
        level: LogLevel,
        event: &str,
        message: &str,
        fields: serde_json::Value,
    ) {
        self.log_sequence = self.log_sequence.wrapping_add(1);
        self.runtime.logs.push(StructuredLogEntry {
            schema_version: CURRENT_SCHEMA_VERSION,
            id: format!("{monotonic_time_ms}-{}", self.log_sequence),
            monotonic_time_ms,
            level,
            event: event.into(),
            message: message.into(),
            fields,
        });
    }
    fn log_result<T>(
        &mut self,
        result: &Result<T, AppError>,
        now: u64,
        event: &str,
        message: &str,
        fields: serde_json::Value,
    ) {
        match result {
            Ok(_) => self.log(now, LogLevel::Info, &format!("{event}.success"), message, fields),
            Err(error) => self.log(now, LogLevel::Error, &format!("{event}.failed"), &error.message, serde_json::json!({ "error": error.message, "code": error.code, "context": fields })),
        }
    }
    fn log_command_result<T>(
        &mut self,
        result: &Result<T, AppError>,
        now: u64,
        final_command: bool,
        fields: serde_json::Value,
    ) {
        match result {
            Ok(_) => self.log(now, if final_command { LogLevel::Info } else { LogLevel::Debug }, "control.command.success", "控制指令执行成功", fields),
            Err(error) => self.log(now, LogLevel::Error, "control.command.failed", &error.message, serde_json::json!({ "error": error.message, "code": error.code, "context": fields })),
        }
    }
    fn run(mut self) {
        self.log(
            now_ms(),
            LogLevel::Info,
            "app.started",
            "LinkerHand Console 运行时已启动",
            serde_json::json!({ "source": "runtime", "simulator": self.simulator }),
        );
        let mut next_motion = now_ms();
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
            // Motion is flushed on its own 50ms cadence, independent of
            // telemetry sampling. Telemetry can block on the sidecar (e.g. a
            // slow sensor read), and coupling the two starved command
            // delivery, making the real hand move sluggishly.
            if now.saturating_sub(next_motion) >= 50 {
                next_motion = now;
                if let Err(error) = self.flush_motion(now) {
                    self.log(
                        now,
                        LogLevel::Error,
                        "control.transport.failed",
                        &error.message,
                        serde_json::json!({ "code": error.code }),
                    );
                }
                self.broadcast_operation();
                self.broadcast_action();
                self.broadcast_grasp();
            }
            if now.saturating_sub(next_telemetry) >= 50 {
                next_telemetry = now;
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
                let started = now_ms();
                self.log(
                    started,
                    LogLevel::Info,
                    "device.connect.started",
                    "开始连接设备",
                    serde_json::json!({ "attempt": self.runtime.device.snapshot().attempt }),
                );
                let result = self
                    .runtime
                    .connect()
                    .map(|_| app_runtime::ui::DevicePort::get_connection(&self.runtime))
                    .map_err(map_error);
                if let Ok(snapshot) = &result {
                    self.broadcast_connection(snapshot.clone());
                }
                self.log_result(
                    &result,
                    now_ms(),
                    "device.connect",
                    "设备已连接",
                    serde_json::json!({ "state": self.runtime.device.snapshot().state }),
                );
                let _ = reply.send(result);
            }
            ActorRequest::Reconnect { reply } => {
                let started = now_ms();
                self.log(
                    started,
                    LogLevel::Info,
                    "device.reconnect.started",
                    "开始重连设备",
                    serde_json::json!({ "attempt": self.runtime.device.snapshot().attempt + 1 }),
                );
                let result = self
                    .runtime
                    .device
                    .reconnect()
                    .map(|_| self.runtime.device.snapshot())
                    .map_err(map_error);
                if let Ok(snapshot) = &result {
                    self.broadcast_connection(snapshot.clone());
                }
                self.log_result(
                    &result,
                    now_ms(),
                    "device.reconnect",
                    "设备已重连",
                    serde_json::json!({ "state": self.runtime.device.snapshot().state }),
                );
                let _ = reply.send(result);
            }
            ActorRequest::Disconnect { reply } => {
                let started = now_ms();
                self.log(
                    started,
                    LogLevel::Info,
                    "device.disconnect.started",
                    "开始断开设备",
                    serde_json::json!({}),
                );
                let result = self
                    .runtime
                    .device
                    .disconnect()
                    .map(|_| app_runtime::ui::DevicePort::get_connection(&self.runtime))
                    .map_err(map_error);
                if let Ok(snapshot) = &result {
                    self.broadcast_connection(snapshot.clone());
                }
                self.log_result(
                    &result,
                    now_ms(),
                    "device.disconnect",
                    "设备已断开",
                    serde_json::json!({ "state": self.runtime.device.snapshot().state }),
                );
                let _ = reply.send(result);
            }
            ActorRequest::Submit { command, reply } => {
                let command_id = command.command_id.clone();
                let source = serde_json::to_value(&command.source)
                    .unwrap_or_else(|_| serde_json::json!("unknown"));
                let context = serde_json::json!({ "commandId": command_id, "source": source, "finalCommand": command.final_command, "jointCount": command.positions.len() });
                self.log(
                    now_ms(),
                    LogLevel::Debug,
                    "control.command.started",
                    "开始执行控制指令",
                    context.clone(),
                );
                if self.control_state.load(Ordering::Acquire) == 1 {
                    let result = Err(app_error("STOPPED", "motion is locked after stop", false));
                    self.log_command_result(&result, now_ms(), command.final_command, context);
                    let _ = reply.send(result);
                    return;
                }
                // Manual operator commands take priority over automation. A
                // running playback/loop owns the motion source, so an operator
                // joint/preset command would be rejected with SourceBusy and
                // the hand could never be steered until the loop stops. Cancel
                // the automation so the manual command can proceed.
                if command.source == console_contracts::CommandSource::Manual
                    && matches!(
                        self.runtime.motion.active_source(),
                        Some(console_contracts::CommandSource::Playback)
                            | Some(console_contracts::CommandSource::Loop)
                    )
                {
                    self.runtime.action_stop();
                }
                let mut result = self
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
                    result = self.flush_motion(now_ms());
                }
                self.log_command_result(&result, now_ms(), command.final_command, context);
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
                let result = match self.latest.clone() {
                    Some(value) => Ok(value),
                    None => match self.runtime.sample_telemetry(now_ms()) {
                        Ok(value) => {
                            self.latest = Some(value.clone());
                            Ok(value)
                        }
                        Err(error) => Err(app_error(
                            "TELEMETRY_UNAVAILABLE",
                            format!("遥测不可用：{error}"),
                            true,
                        )),
                    },
                };
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
                if let Err(error) = action_engine::validate_playback_speed(speed) {
                    let _ = reply.send(Err(map_error(error)));
                    return;
                }
                let action_context = serde_json::json!({ "actionId": id, "speed": speed, "loopEnabled": loop_enabled, "loopCount": loop_count });
                self.log(
                    now_ms(),
                    LogLevel::Info,
                    "control.action.started",
                    "开始执行动作",
                    action_context.clone(),
                );
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
                self.log_result(
                    &result,
                    now_ms(),
                    "control.action",
                    "动作执行成功",
                    action_context,
                );
                let _ = reply.send(result);
            }
            ActorRequest::ActionPlayFrames {
                id,
                name,
                mut frames,
                speed,
                loop_enabled,
                loop_count,
                direction,
                reply,
            } => {
                if let Err(error) = action_engine::validate_playback_speed(speed) {
                    let _ = reply.send(Err(map_error(error)));
                    return;
                }
                let context = serde_json::json!({ "actionId": id, "name": name, "frameCount": frames.len(), "speed": speed, "loopEnabled": loop_enabled, "loopCount": loop_count, "direction": direction });
                self.log(
                    now_ms(),
                    LogLevel::Info,
                    "control.action.frames_started",
                    "开始执行完整动作关键帧",
                    context.clone(),
                );
                if direction == "reverse" {
                    frames.reverse();
                }
                let recording = console_contracts::ActionRecording {
                    schema_version: CURRENT_SCHEMA_VERSION,
                    id,
                    name,
                    duration_ms: frames
                        .iter()
                        .map(|frame| frame.duration_ms.unwrap_or(500))
                        .sum(),
                    steps: frames.len() as u32,
                    updated_at: String::new(),
                    frames,
                };
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
                            .action_play_recording(
                                recording,
                                speed,
                                loop_enabled,
                                loop_count,
                                now_ms(),
                            )
                            .map_err(map_error)
                    }
                } else {
                    self.runtime
                        .action_play_recording(recording, speed, loop_enabled, loop_count, now_ms())
                        .map_err(map_error)
                };
                self.log_result(
                    &result,
                    now_ms(),
                    "control.action.frames",
                    "完整动作关键帧执行成功",
                    context,
                );
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
            ActorRequest::GraspStart {
                preset,
                degraded,
                reply,
            } => {
                let _ = reply.send(
                    self.runtime
                        .grasp_start(&preset, degraded, now_ms())
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
            ActorRequest::RecordLog { entry, reply } => {
                self.log(
                    now_ms(),
                    entry.level,
                    &entry.event,
                    &entry.message,
                    entry.fields,
                );
                let _ = reply.send(Ok(()));
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
            self.log(
                now_ms(),
                LogLevel::Warn,
                "safety.stop.requested",
                "收到停止全部动作请求",
                serde_json::json!({ "emergency": true, "reason": "unlock-before-stop" }),
            );
            let result = self
                .runtime
                .stop_all_checked()
                .map_err(|error| app_error("STOP_FAILED", error.to_string(), true));
            self.log_result(
                &result,
                now_ms(),
                "safety.stop",
                "全部动作已停止",
                serde_json::json!({ "emergency": true }),
            );
            self.applied_control = 1;
            return;
        }
        match desired {
            1 => {
                self.log(
                    now_ms(),
                    LogLevel::Warn,
                    "safety.stop.requested",
                    "收到停止全部动作请求",
                    serde_json::json!({ "emergency": true }),
                );
                let result = self
                    .runtime
                    .stop_all_checked()
                    .map_err(|error| app_error("STOP_FAILED", error.to_string(), true));
                self.log_result(
                    &result,
                    now_ms(),
                    "safety.stop",
                    "全部动作已停止",
                    serde_json::json!({ "emergency": true }),
                );
            }
            2 => {
                self.runtime.unlock();
                self.log(
                    now_ms(),
                    LogLevel::Info,
                    "safety.unlock.completed",
                    "控制锁已解除",
                    serde_json::json!({}),
                );
            }
            _ => return,
        }
        self.applied_control = desired;
    }
    fn flush_motion(&mut self, now: u64) -> Result<(), AppError> {
        if let Some(command) = self.runtime.action_tick(now) {
            let _ = self.runtime.motion.submit(command);
        }
        if let Ok(Some(command)) = self.runtime.grasp_tick(now) {
            let _ = self.runtime.motion.submit(command);
        }
        if let Some(command) = self.runtime.motion.tick(now) {
            self.runtime.device.send(&command).map_err(map_error)?;
        }
        Ok(())
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
        use adaptive_grasp::GraspJointState;
        use adaptive_grasp::GraspState;
        let phase = match self.runtime.grasp.state() {
            GraspState::Idle => "idle",
            GraspState::Calibrating => "calibrating",
            GraspState::Ready => "ready",
            GraspState::Approaching => "approach",
            GraspState::ClosingCoarse | GraspState::Grasping => "closingCoarse",
            GraspState::ClosingFine => "closingFine",
            GraspState::Preloading => "preloading",
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
        let joints = self
            .runtime
            .grasp
            .joint_states()
            .iter()
            .zip(self.runtime.grasp.contact_scores().iter())
            .enumerate()
            .map(|(index, (state, score))| GraspJointEvent {
                index,
                state: match state {
                    GraspJointState::Idle => "idle",
                    GraspJointState::ClosingCoarse => "closingCoarse",
                    GraspJointState::ClosingFine => "closingFine",
                    GraspJointState::ContactCandidate => "contactCandidate",
                    GraspJointState::ContactConfirmed => "contactConfirmed",
                    GraspJointState::Frozen => "frozen",
                    GraspJointState::LimitReached => "limitReached",
                    GraspJointState::Error => "error",
                }
                .into(),
                contact_score: *score as f32,
            })
            .collect();
        let value = GraspStateEvent {
            phase: phase.into(),
            failure,
            tactile_available: telemetry.is_some_and(|t| !t.raw_touch.is_empty()),
            raw_touch: telemetry.map(|t| t.raw_touch.clone()),
            degraded: self.runtime.grasp.degraded(),
            joints,
        };
        self.grasp_channels
            .retain(|channel| channel.send(value.clone()).is_ok());
    }
    fn sample_and_broadcast(&mut self, now: u64) {
        match self.runtime.sample_telemetry(now) {
            Ok(value) => {
                self.telemetry_error = None;
                self.latest = Some(value.clone());
                self.telemetry_channels
                    .retain(|channel| channel.send(value.clone()).is_ok());
            }
            Err(error) => {
                // Sampling runs at ~20 Hz whenever a subscriber is attached, so
                // a persistent fault would flood the log if logged every tick.
                // Record one structured entry per distinct failure so the
                // cause is visible in the diagnostics log without drowning it.
                let message = error.to_string();
                if self.telemetry_error.as_deref() != Some(message.as_str()) {
                    self.log(
                        now,
                        LogLevel::Error,
                        "telemetry.sample.failed",
                        "遥测采样失败",
                        serde_json::json!({ "error": message }),
                    );
                }
                self.telemetry_error = Some(message);
            }
        }
    }
    fn shutdown(&mut self) {
        self.log(
            now_ms(),
            LogLevel::Info,
            "app.stopping",
            "LinkerHand Console 运行时正在停止",
            serde_json::json!({ "source": "runtime" }),
        );
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
    let roots = sidecar_roots();
    sidecar_process_with_roots(explicit, simulator, roots)
}

fn sidecar_roots() -> Vec<PathBuf> {
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
    roots
}

fn sidecar_process_with_roots(
    explicit: Option<PathBuf>,
    simulator: bool,
    roots: Vec<PathBuf>,
) -> (ProcessConfig, Option<PathBuf>) {
    if simulator {
        let script =
            PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../sidecar/linkerhand-bridge/main.py");
        return (ProcessConfig::fake(script), None);
    }
    let selected = resolve_sidecar_path(explicit, roots.clone());
    // Keep a deterministic, explainable missing path so a later explicit
    // connect reports a sidecar error rather than silently falling back to
    // Python from PATH.
    let program = selected
        .clone()
        .or_else(|| sidecar_candidates(None, &roots).into_iter().next())
        .unwrap_or_else(|| PathBuf::from("linkerhand-sidecar.exe"));
    // The real LinkerHand SDK crashes its Python process when both stdout and
    // stderr are pipes (hard exit, no traceback, shortly after the first SDK
    // call). stdout must stay a pipe for NDJSON, so stderr diagnostics are
    // redirected to a file instead.
    let stderr_log = std::env::temp_dir().join("linkerhand-sidecar-stderr.log");
    let process = ProcessConfig::executable(program).with_stderr_path(stderr_log);
    (process, selected)
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
                simulator,
                log_sequence: 0,
                telemetry_error: None,
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
    pub async fn open_camera_privacy_settings() -> Result<(), String> {
        #[cfg(windows)]
        {
            std::process::Command::new("cmd")
                .args(["/C", "start", "", "ms-settings:privacy-webcam"])
                .spawn()
                .map(|_| ())
                .map_err(|error| format!("启动 Windows 摄像头设置失败：{error}"))
        }
        #[cfg(not(windows))]
        {
            Err("当前平台没有 Windows 摄像头隐私设置页面".into())
        }
    }
    #[tauri::command]
    pub async fn camera_permission_status(
        app: tauri::AppHandle,
    ) -> Result<CameraPermissionStatus, String> {
        super::camera_permission_status(&app, false)
    }
    #[tauri::command]
    pub async fn reset_camera_permission(
        app: tauri::AppHandle,
    ) -> Result<CameraPermissionStatus, String> {
        super::camera_permission_status(&app, true)
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
    // Keep the flat argument list aligned with the public Tauri invoke payload;
    // wrapping it would be a wire-contract change rather than a local cleanup.
    #[allow(clippy::too_many_arguments)]
    #[tauri::command]
    pub async fn action_play_frames(
        state: tauri::State<'_, RuntimeState>,
        id: String,
        name: String,
        frames: Vec<JointTargetCommand>,
        speed: f32,
        loop_enabled: bool,
        loop_count: Option<u32>,
        direction: String,
    ) -> Result<(), AppError> {
        dispatch(state.0.clone(), |reply| ActorRequest::ActionPlayFrames {
            id,
            name,
            frames,
            speed,
            loop_enabled,
            loop_count,
            direction,
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
        preset: String,
        degraded: bool,
    ) -> Result<(), AppError> {
        dispatch(state.0.clone(), |reply| ActorRequest::GraspStart {
            preset,
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
    #[tauri::command]
    pub async fn logs_record(
        state: tauri::State<'_, RuntimeState>,
        entry: LogRecord,
    ) -> Result<(), AppError> {
        dispatch(state.0.clone(), |reply| ActorRequest::RecordLog {
            entry,
            reply,
        })
        .await
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
            #[cfg(windows)]
            install_camera_permission_handler(app.handle());
            *shutdown_slot.lock().expect("shutdown slot poisoned") = Some(handle);
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            commands::config,
            commands::capabilities,
            commands::settings_load,
            commands::settings_save,
            commands::open_camera_privacy_settings,
            commands::camera_permission_status,
            commands::reset_camera_permission,
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
            commands::action_play_frames,
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
            commands::logs_list,
            commands::logs_record
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
    fn camera_permission_handler_only_trusts_console_origins() {
        assert!(trusted_camera_origin("http://tauri.localhost/settings"));
        assert!(trusted_camera_origin("http://127.0.0.1:1420/"));
        assert!(!trusted_camera_origin("http://127.0.0.1:1421/"));
        assert!(!trusted_camera_origin("https://evil.example/"));
        assert!(!trusted_camera_origin(
            "http://tauri.localhost.evil.example/"
        ));
    }

    #[cfg(windows)]
    #[test]
    fn camera_permission_state_name_preserves_webview2_default() {
        use webview2_com::Microsoft::Web::WebView2::Win32::{
            COREWEBVIEW2_PERMISSION_STATE_ALLOW, COREWEBVIEW2_PERMISSION_STATE_DEFAULT,
            COREWEBVIEW2_PERMISSION_STATE_DENY,
        };
        assert_eq!(
            camera_permission_state_name(COREWEBVIEW2_PERMISSION_STATE_DEFAULT),
            "default"
        );
        assert_eq!(
            camera_permission_state_name(COREWEBVIEW2_PERMISSION_STATE_ALLOW),
            "allow"
        );
        assert_eq!(
            camera_permission_state_name(COREWEBVIEW2_PERMISSION_STATE_DENY),
            "deny"
        );
    }

    #[test]
    fn release_defaults_never_select_fake_transport_or_python() {
        let config = normalize_config(safe_default_config(), false);
        assert!(matches!(
            config.transport,
            console_contracts::Transport::Can { ref channel }
                if channel.eq_ignore_ascii_case("PCAN_USBBUS1")
        ));
        let (process, selected) = sidecar_process_with_roots(
            Some(PathBuf::from("C:/missing/linkerhand-sidecar.exe")),
            false,
            vec![std::env::temp_dir().join(format!(
                "linkerhand-console-v2-test-roots-{}",
                std::process::id()
            ))],
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
        let (process, selected) = sidecar_process_with_roots(
            Some(std::env::temp_dir().join(format!(
                "linkerhand-console-v2-missing-{}.exe",
                std::process::id()
            ))),
            false,
            vec![std::env::temp_dir().join(format!(
                "linkerhand-console-v2-test-roots-{}",
                std::process::id()
            ))],
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
        fail_send: Option<Arc<AtomicBool>>,
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
            if self
                .fail_send
                .as_ref()
                .is_some_and(|flag| flag.swap(false, Ordering::AcqRel))
            {
                return Err(device_adapter_api::AdapterError::Transport(
                    "injected CAN send failure".into(),
                ));
            }
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

    fn spawn_capturing_runtime_with_failure(
        fail_send: Option<Arc<AtomicBool>>,
    ) -> (RuntimeHandle, Arc<Mutex<Vec<JointTargetCommand>>>) {
        let config = DeviceConfig::new("capture", "capture O6");
        let writes = Arc::new(Mutex::new(Vec::new()));
        let mut runtime = AppRuntime::new(config, adaptive_grasp::Profile::O6);
        runtime.install_adapter(Box::new(CapturingAdapter {
            inner: device_simulator::DeviceSimulator::new("capture", 6),
            writes: writes.clone(),
            fail_send,
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
                    simulator: true,
                    log_sequence: 0,
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

    fn spawn_capturing_runtime() -> (RuntimeHandle, Arc<Mutex<Vec<JointTargetCommand>>>) {
        spawn_capturing_runtime_with_failure(None)
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
    fn actor_plays_complete_frames_in_reverse_with_loop_and_can_cancel() {
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
        let frames = vec![
            JointTargetCommand {
                schema_version: CURRENT_SCHEMA_VERSION,
                command_id: "frame-a".into(),
                source: CommandSource::Preset,
                positions: vec![0.1; 6],
                duration_ms: Some(50),
                final_command: false,
            },
            JointTargetCommand {
                schema_version: CURRENT_SCHEMA_VERSION,
                command_id: "frame-b".into(),
                source: CommandSource::Preset,
                positions: vec![0.9; 6],
                duration_ms: Some(50),
                final_command: true,
            },
        ];
        runtime
            .block_on(dispatch(handle.clone(), |reply| {
                ActorRequest::ActionPlayFrames {
                    id: "programmed-1".into(),
                    name: "编程动作".into(),
                    frames,
                    speed: 1.0,
                    loop_enabled: true,
                    loop_count: Some(2),
                    direction: "reverse".into(),
                    reply,
                }
            }))
            .unwrap();
        std::thread::sleep(Duration::from_millis(90));
        let first = writes
            .lock()
            .unwrap()
            .first()
            .cloned()
            .expect("first programmed frame was sent");
        assert_eq!(first.positions, vec![0.9; 6]);
        writes.lock().unwrap().clear();
        runtime
            .block_on(dispatch(handle.clone(), |reply| ActorRequest::ActionStop {
                reply,
            }))
            .unwrap();
        std::thread::sleep(Duration::from_millis(80));
        assert!(writes.lock().unwrap().is_empty());
        handle.shutdown();
    }

    #[test]
    fn non_final_control_command_success_is_debug_but_final_is_info() {
        let (handle, _writes) = spawn_capturing_runtime();
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
                command: command("mid", 0.2, false),
                reply,
            }))
            .unwrap();
        runtime
            .block_on(dispatch(handle.clone(), |reply| ActorRequest::Submit {
                command: command("final", 0.8, true),
                reply,
            }))
            .unwrap();
        let logs = runtime
            .block_on(dispatch(handle.clone(), |reply| ActorRequest::Logs {
                limit: 512,
                reply,
            }))
            .unwrap();
        let successes: Vec<_> = logs
            .iter()
            .filter(|entry| entry.event == "control.command.success")
            .collect();
        assert!(successes
            .iter()
            .any(|entry| entry.level == LogLevel::Debug && entry.fields["finalCommand"] == false));
        assert!(successes
            .iter()
            .any(|entry| entry.level == LogLevel::Info && entry.fields["finalCommand"] == true));
        handle.shutdown();
    }

    #[test]
    fn final_control_command_reports_transport_send_failure() {
        let fail_send = Arc::new(AtomicBool::new(false));
        let (handle, writes) = spawn_capturing_runtime_with_failure(Some(fail_send.clone()));
        let runtime = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .unwrap();
        runtime
            .block_on(dispatch(handle.clone(), |reply| ActorRequest::Connect {
                reply,
            }))
            .unwrap();
        fail_send.store(true, Ordering::Release);
        let error = runtime
            .block_on(dispatch(handle.clone(), |reply| ActorRequest::Submit {
                command: command("must-reach-can", 0.5, true),
                reply,
            }))
            .expect_err("final command must expose the CAN send failure");
        assert!(error.message.contains("injected CAN send failure"));
        assert!(writes.lock().unwrap().is_empty());
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
                preset: "cube".into(),
                degraded: true,
                reply,
            }))
            .unwrap();
        let state = events_rx.recv_timeout(Duration::from_secs(2)).unwrap();
        assert!(matches!(
            state.phase.as_str(),
            "calibrating" | "ready" | "approach" | "closingCoarse"
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
