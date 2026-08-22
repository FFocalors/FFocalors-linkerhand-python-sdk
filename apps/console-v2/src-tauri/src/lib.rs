//! Tauri assembly only. `RuntimeActor` is the single owner of AppRuntime and
//! the sidecar adapter; IPC commands never hold a mutex while doing I/O.
use app_runtime::AppRuntime;
use console_contracts::{AppError, ConnectionSnapshot, DeviceCapabilities, DeviceConfig, JointTargetCommand, OperationSnapshot, TelemetrySnapshot};
use sidecar_client::{process::{ProcessConfig, SidecarProcessManager}, SidecarDeviceAdapter};
use std::sync::{mpsc, Arc};
use std::sync::atomic::{AtomicBool, Ordering};
use std::thread;
use tauri::ipc::Channel;

fn app_error(code: &str, message: impl Into<String>, retryable: bool) -> AppError {
    AppError { code: code.into(), message: message.into(), retryable, details: None }
}
fn map_error(value: impl std::fmt::Display) -> AppError { app_error("RUNTIME_ERROR", value.to_string(), true) }

type Reply<T> = tokio::sync::oneshot::Sender<Result<T, AppError>>;
enum ActorRequest {
    Config { reply: Reply<DeviceConfig> },
    Capabilities { reply: Reply<DeviceCapabilities> },
    Connection { reply: Reply<ConnectionSnapshot> },
    Connect { reply: Reply<ConnectionSnapshot> },
    Disconnect { reply: Reply<ConnectionSnapshot> },
    Submit { command: JointTargetCommand, reply: Reply<()> },
    Operation { reply: Reply<OperationSnapshot> },
    ReadTelemetry { reply: Reply<TelemetrySnapshot> },
    SubscribeTelemetry { channel: Channel<TelemetrySnapshot>, reply: Reply<()> },
    UnsubscribeTelemetry { channel_id: u32, reply: Reply<()> },
    Shutdown,
}

#[derive(Clone)]
pub struct RuntimeHandle {
    tx: mpsc::SyncSender<ActorRequest>,
    control_state: Arc<std::sync::atomic::AtomicU8>,
    shutdown_requested: Arc<AtomicBool>,
    stopped: Arc<AtomicBool>,
}
pub struct RuntimeState(pub RuntimeHandle);

impl RuntimeHandle {
    fn enqueue(&self, request: ActorRequest) -> Result<(), AppError> {
        self.tx.try_send(request).map_err(|error| match error {
            mpsc::TrySendError::Full(_) => app_error("RUNTIME_BUSY", "runtime command queue is full", true),
            mpsc::TrySendError::Disconnected(_) => app_error("RUNTIME_CLOSED", "runtime actor is closed", false),
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
}

struct RuntimeActor {
    runtime: AppRuntime,
    rx: mpsc::Receiver<ActorRequest>,
    telemetry_channels: Vec<Channel<TelemetrySnapshot>>,
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
            if self.shutdown_requested.load(Ordering::Acquire) { self.shutdown(); break; }
            match self.rx.recv_timeout(std::time::Duration::from_millis(5)) {
                Ok(ActorRequest::Shutdown) => { self.shutdown(); break; }
                Ok(request) => self.handle(request),
                Err(mpsc::RecvTimeoutError::Timeout) => {}
                Err(mpsc::RecvTimeoutError::Disconnected) => { self.shutdown(); break; }
            }
            self.apply_control();
            if self.shutdown_requested.load(Ordering::Acquire) { self.shutdown(); break; }
            let now = now_ms();
            if now.saturating_sub(next_telemetry) >= 50 {
                next_telemetry = now;
                self.flush_motion(now);
                if !self.telemetry_channels.is_empty() { self.sample_and_broadcast(now); }
            }
        }
    }
    fn handle(&mut self, request: ActorRequest) {
        match request {
            ActorRequest::Config { reply } => { let _ = reply.send(Ok(app_runtime::ui::DevicePort::get_config(&self.runtime))); }
            ActorRequest::Capabilities { reply } => { let result = app_runtime::ui::DevicePort::get_capabilities(&self.runtime).ok_or_else(|| app_error("NOT_CONNECTED", "connect before querying capabilities", true)); let _ = reply.send(result); }
            ActorRequest::Connection { reply } => { let _ = reply.send(Ok(app_runtime::ui::DevicePort::get_connection(&self.runtime))); }
            ActorRequest::Connect { reply } => { let result = self.runtime.connect().map(|_| app_runtime::ui::DevicePort::get_connection(&self.runtime)).map_err(map_error); let _ = reply.send(result); }
            ActorRequest::Disconnect { reply } => { let result = self.runtime.device.disconnect().map(|_| app_runtime::ui::DevicePort::get_connection(&self.runtime)).map_err(map_error); let _ = reply.send(result); }
            ActorRequest::Submit { command, reply } => {
                if self.control_state.load(Ordering::Acquire) == 1 { let _ = reply.send(Err(app_error("STOPPED", "motion is locked after stop", false))); return; }
                let result = self.runtime.motion.submit(command.clone()).map_err(map_error);
                if result.is_ok() && command.final_command { self.flush_motion(now_ms()); }
                let _ = reply.send(result);
            }
            ActorRequest::Operation { reply } => { let _ = reply.send(Ok(app_runtime::ui::MotionPort::get_operation(&self.runtime))); }
            ActorRequest::ReadTelemetry { reply } => {
                let result = self.latest.clone().or_else(|| self.runtime.sample_telemetry(now_ms()).ok()).ok_or_else(|| app_error("TELEMETRY_UNAVAILABLE", "telemetry is not available until the device is connected", true));
                if let Ok(value) = &result { self.latest = Some(value.clone()); }
                let _ = reply.send(result);
            }
            ActorRequest::SubscribeTelemetry { channel, reply } => {
                if self.telemetry_channels.len() >= 8 { let _ = reply.send(Err(app_error("RUNTIME_BUSY", "telemetry subscriber limit reached", true))); }
                else { self.telemetry_channels.push(channel); let _ = reply.send(Ok(())); }
            }
            ActorRequest::UnsubscribeTelemetry { channel_id, reply } => {
                self.telemetry_channels.retain(|channel| channel.id() != channel_id);
                let _ = reply.send(Ok(()));
            }
            ActorRequest::Shutdown => {}
        }
    }
    fn apply_control(&mut self) {
        let desired = self.control_state.load(Ordering::Acquire);
        if desired == self.applied_control { return; }
        if desired == 2 && self.applied_control == 0 {
            // Preserve stop-before-unlock ordering even if both atomics were
            // changed while the actor was busy or the request queue was full.
            self.runtime.stop_all();
            self.applied_control = 1;
            return;
        }
        match desired { 1 => self.runtime.stop_all(), 2 => self.runtime.unlock(), _ => return }
        self.applied_control = desired;
    }
    fn flush_motion(&mut self, now: u64) {
        if let Some(command) = self.runtime.motion.tick(now) { let _ = self.runtime.device.send(&command); }
    }
    fn sample_and_broadcast(&mut self, now: u64) {
        let Ok(value) = self.runtime.sample_telemetry(now) else { return; };
        self.latest = Some(value.clone());
        self.telemetry_channels.retain(|channel| channel.send(value.clone()).is_ok());
    }
    fn shutdown(&mut self) {
        self.runtime.motion.stop_all();
        self.runtime.shutdown();
        self.stopped.store(true, Ordering::Release);
    }
}

fn spawn_runtime() -> RuntimeHandle {
    let config = DeviceConfig::new("sim-1", "演示机械手 O6");
    let mut runtime = AppRuntime::new(config.clone(), adaptive_grasp::Profile::O6);
    let script = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../sidecar/linkerhand-bridge/main.py");
    runtime.install_adapter(Box::new(SidecarDeviceAdapter::new(config, SidecarProcessManager::new(ProcessConfig::fake(script)))));
    let (tx, rx) = mpsc::sync_channel(128);
    let control_state = Arc::new(std::sync::atomic::AtomicU8::new(0));
    let shutdown_requested = Arc::new(AtomicBool::new(false));
    let stopped = Arc::new(AtomicBool::new(false));
    let actor_control = Arc::clone(&control_state);
    let actor_shutdown = Arc::clone(&shutdown_requested);
    let actor_stopped = Arc::clone(&stopped);
    thread::Builder::new().name("linkerhand-runtime-actor".into()).spawn(move || RuntimeActor { runtime, rx, telemetry_channels: Vec::new(), latest: None, control_state: actor_control, shutdown_requested: actor_shutdown, applied_control: 0, stopped: actor_stopped }.run()).expect("spawn runtime actor");
    RuntimeHandle { tx, control_state, shutdown_requested, stopped }
}

async fn dispatch<T>(handle: RuntimeHandle, request: impl FnOnce(Reply<T>) -> ActorRequest) -> Result<T, AppError> {
    let (reply, receiver) = tokio::sync::oneshot::channel();
    handle.enqueue(request(reply))?;
    receiver.await.map_err(|_| app_error("RUNTIME_CLOSED", "runtime actor stopped", false))?
}

mod commands {
    use super::*;
    #[tauri::command]
    pub async fn config(state: tauri::State<'_, RuntimeState>) -> Result<DeviceConfig, AppError> { dispatch(state.0.clone(), |reply| ActorRequest::Config { reply }).await }
    #[tauri::command]
    pub async fn capabilities(state: tauri::State<'_, RuntimeState>) -> Result<DeviceCapabilities, AppError> { dispatch(state.0.clone(), |reply| ActorRequest::Capabilities { reply }).await }
    #[tauri::command]
    pub async fn connection(state: tauri::State<'_, RuntimeState>) -> Result<ConnectionSnapshot, AppError> { dispatch(state.0.clone(), |reply| ActorRequest::Connection { reply }).await }
    #[tauri::command]
    pub async fn connect(state: tauri::State<'_, RuntimeState>) -> Result<ConnectionSnapshot, AppError> { dispatch(state.0.clone(), |reply| ActorRequest::Connect { reply }).await }
    #[tauri::command]
    pub async fn disconnect(state: tauri::State<'_, RuntimeState>) -> Result<ConnectionSnapshot, AppError> { dispatch(state.0.clone(), |reply| ActorRequest::Disconnect { reply }).await }
    #[tauri::command]
    pub async fn set_joint_target(state: tauri::State<'_, RuntimeState>, command: JointTargetCommand) -> Result<(), AppError> { dispatch(state.0.clone(), |reply| ActorRequest::Submit { command, reply }).await }
    #[tauri::command]
    pub async fn stop_all(state: tauri::State<'_, RuntimeState>) -> Result<(), AppError> { state.0.control_state.store(1, Ordering::Release); Ok(()) }
    #[tauri::command]
    pub async fn unlock(state: tauri::State<'_, RuntimeState>) -> Result<(), AppError> { state.0.control_state.store(2, Ordering::Release); Ok(()) }
    #[tauri::command]
    pub async fn operation(state: tauri::State<'_, RuntimeState>) -> Result<OperationSnapshot, AppError> { dispatch(state.0.clone(), |reply| ActorRequest::Operation { reply }).await }
    #[tauri::command]
    pub async fn telemetry_read(state: tauri::State<'_, RuntimeState>) -> Result<TelemetrySnapshot, AppError> { dispatch(state.0.clone(), |reply| ActorRequest::ReadTelemetry { reply }).await }
    #[tauri::command]
    pub async fn telemetry_subscribe(state: tauri::State<'_, RuntimeState>, channel: Channel<TelemetrySnapshot>) -> Result<(), AppError> { dispatch(state.0.clone(), |reply| ActorRequest::SubscribeTelemetry { channel, reply }).await }
    #[tauri::command]
    pub async fn telemetry_unsubscribe(state: tauri::State<'_, RuntimeState>, channel_id: u32) -> Result<(), AppError> { dispatch(state.0.clone(), |reply| ActorRequest::UnsubscribeTelemetry { channel_id, reply }).await }
}

fn now_ms() -> u64 { static START: std::sync::OnceLock<std::time::Instant> = std::sync::OnceLock::new(); START.get_or_init(std::time::Instant::now).elapsed().as_millis() as u64 }

pub fn run() {
    let handle = spawn_runtime();
    let shutdown_handle = handle.clone();
    tauri::Builder::default()
        .manage(RuntimeState(handle))
        .invoke_handler(tauri::generate_handler![commands::config, commands::capabilities, commands::connection, commands::connect, commands::disconnect, commands::set_joint_target, commands::stop_all, commands::unlock, commands::operation, commands::telemetry_read, commands::telemetry_subscribe, commands::telemetry_unsubscribe])
        .build(tauri::generate_context!())
        .expect("error while building LinkerHand Console")
        .run(move |_app_handle, event| {
            if let tauri::RunEvent::Exit = event { shutdown_handle.shutdown(); }
        });
}

#[cfg(test)]
mod tests {
    use super::*;
    use console_contracts::{CommandSource, CURRENT_SCHEMA_VERSION};
    use std::time::Duration;

    fn command(id: &str, value: f64, final_command: bool) -> JointTargetCommand {
        JointTargetCommand { schema_version: CURRENT_SCHEMA_VERSION, command_id: id.into(), source: CommandSource::Manual, positions: vec![value; 6], duration_ms: None, final_command }
    }

    #[test]
    fn actor_broadcasts_continuous_frames_and_stop_unlocks() {
        let handle = spawn_runtime();
        let runtime = tokio::runtime::Builder::new_current_thread().enable_all().build().unwrap();
        runtime.block_on(dispatch(handle.clone(), |reply| ActorRequest::Connect { reply })).unwrap();
        let (frames_tx, frames_rx) = mpsc::channel();
        let channel = Channel::new(move |body| {
            if let tauri::ipc::InvokeResponseBody::Json(json) = body {
                if let Ok(value) = serde_json::from_str::<TelemetrySnapshot>(&json) { let _ = frames_tx.send(value); }
            }
            Ok(())
        });
        runtime.block_on(dispatch(handle.clone(), |reply| ActorRequest::SubscribeTelemetry { channel, reply })).unwrap();
        let first = frames_rx.recv_timeout(Duration::from_secs(2)).unwrap();
        let second = frames_rx.recv_timeout(Duration::from_secs(2)).unwrap();
        assert!(second.sequence > first.sequence);
        runtime.block_on(dispatch(handle.clone(), |reply| ActorRequest::Submit { command: command("first", 0.1, false), reply })).unwrap();
        runtime.block_on(dispatch(handle.clone(), |reply| ActorRequest::Submit { command: command("latest", 0.8, false), reply })).unwrap();
        std::thread::sleep(Duration::from_millis(100));
        let latest = runtime.block_on(dispatch(handle.clone(), |reply| ActorRequest::ReadTelemetry { reply })).unwrap();
        assert_eq!(latest.positions, vec![0.8; 6]);
        runtime.block_on(dispatch(handle.clone(), |reply| ActorRequest::Submit { command: command("final", 0.9, true), reply })).unwrap();
        handle.control_state.store(1, Ordering::Release);
        std::thread::sleep(Duration::from_millis(30));
        let stopped = runtime.block_on(dispatch(handle.clone(), |reply| ActorRequest::Submit { command: command("blocked", 0.2, false), reply }));
        assert!(stopped.is_err());
        handle.control_state.store(2, Ordering::Release);
        std::thread::sleep(Duration::from_millis(30));
        runtime.block_on(dispatch(handle.clone(), |reply| ActorRequest::Submit { command: command("after-unlock", 0.3, true), reply })).unwrap();
        let started = std::time::Instant::now();
        handle.shutdown();
        assert!(started.elapsed() < Duration::from_secs(2));
    }

    #[test]
    fn atomic_shutdown_signal_survives_a_full_command_queue() {
        let handle = spawn_runtime();
        let mut filled = 0;
        for _ in 0..256 {
            let (reply, _receiver) = tokio::sync::oneshot::channel();
            if handle.tx.try_send(ActorRequest::Config { reply }).is_ok() { filled += 1; } else { break; }
        }
        assert!(filled > 0);
        handle.control_state.store(1, Ordering::Release);
        std::thread::sleep(Duration::from_millis(30));
        let runtime = tokio::runtime::Builder::new_current_thread().enable_all().build().unwrap();
        let command = command("saturated-stop", 0.2, false);
        let stopped = runtime.block_on(dispatch(handle.clone(), |reply| ActorRequest::Submit { command, reply }));
        assert!(stopped.is_err());
        let started = std::time::Instant::now();
        handle.shutdown();
        assert!(started.elapsed() < Duration::from_secs(2));
        assert!(handle.stopped.load(Ordering::Acquire));
    }
}
