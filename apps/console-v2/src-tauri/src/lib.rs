//! Minimal Tauri 2 assembly shell. Business logic stays in app-runtime.
use app_runtime::AppRuntime;
use console_contracts::{AppError, ConnectionSnapshot, DeviceCapabilities, DeviceConfig, JointTargetCommand, TelemetrySnapshot, WireEnvelope};
use device_simulator::DeviceSimulator;
use serde::Serialize;
use serde_json::Value;
use std::sync::Mutex;
use tauri::ipc::Channel;

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct RuntimeEvent {
    pub event: WireEnvelope<Value>,
}

pub struct RuntimeState(pub Mutex<AppRuntime>);

fn error(code: &str, message: impl Into<String>, retryable: bool) -> AppError {
    AppError { code: code.into(), message: message.into(), retryable, details: None }
}
fn map_error(value: impl std::fmt::Display) -> AppError { error("RUNTIME_ERROR", value.to_string(), true) }

mod commands {
    use super::*;
    #[tauri::command]
    pub fn config(state: tauri::State<'_, RuntimeState>) -> Result<DeviceConfig, AppError> { let runtime = state.0.lock().map_err(|_| error("RUNTIME_LOCK", "runtime lock poisoned", true))?; Ok(app_runtime::ui::DevicePort::get_config(&*runtime)) }
    #[tauri::command]
    pub fn capabilities(state: tauri::State<'_, RuntimeState>) -> Result<DeviceCapabilities, AppError> { let runtime = state.0.lock().map_err(|_| error("RUNTIME_LOCK", "runtime lock poisoned", true))?; app_runtime::ui::DevicePort::get_capabilities(&*runtime).ok_or_else(|| error("NOT_CONNECTED", "connect before querying capabilities", true)) }
    #[tauri::command]
    pub fn connection(state: tauri::State<'_, RuntimeState>) -> Result<ConnectionSnapshot, AppError> { let runtime = state.0.lock().map_err(|_| error("RUNTIME_LOCK", "runtime lock poisoned", true))?; Ok(app_runtime::ui::DevicePort::get_connection(&*runtime)) }
    #[tauri::command]
    pub fn connect(state: tauri::State<'_, RuntimeState>) -> Result<ConnectionSnapshot, AppError> { let mut runtime = state.0.lock().map_err(|_| error("RUNTIME_LOCK", "runtime lock poisoned", true))?; runtime.connect().map_err(map_error)?; Ok(app_runtime::ui::DevicePort::get_connection(&*runtime)) }
    #[tauri::command]
    pub fn disconnect(state: tauri::State<'_, RuntimeState>) -> Result<ConnectionSnapshot, AppError> { let mut runtime = state.0.lock().map_err(|_| error("RUNTIME_LOCK", "runtime lock poisoned", true))?; runtime.device.disconnect().map_err(map_error)?; Ok(app_runtime::ui::DevicePort::get_connection(&*runtime)) }
    #[tauri::command]
    pub fn set_joint_target(state: tauri::State<'_, RuntimeState>, command: JointTargetCommand) -> Result<(), AppError> { let mut runtime = state.0.lock().map_err(|_| error("RUNTIME_LOCK", "runtime lock poisoned", true))?; app_runtime::ui::DevicePort::set_joint_target(&mut *runtime, command, now_ms()).map_err(map_error) }
    #[tauri::command]
    pub fn stop_all(state: tauri::State<'_, RuntimeState>) -> Result<(), AppError> { let mut runtime = state.0.lock().map_err(|_| error("RUNTIME_LOCK", "runtime lock poisoned", true))?; app_runtime::ui::DevicePort::stop_all(&mut *runtime); Ok(()) }
    #[tauri::command]
    pub fn unlock(state: tauri::State<'_, RuntimeState>) -> Result<(), AppError> { let mut runtime = state.0.lock().map_err(|_| error("RUNTIME_LOCK", "runtime lock poisoned", true))?; app_runtime::ui::DevicePort::unlock(&mut *runtime); Ok(()) }
    #[tauri::command]
    pub fn telemetry(state: tauri::State<'_, RuntimeState>, channel: Channel<TelemetrySnapshot>) -> Result<(), AppError> { let mut runtime = state.0.lock().map_err(|_| error("RUNTIME_LOCK", "runtime lock poisoned", true))?; let value = runtime.sample_telemetry(now_ms()).map_err(map_error)?; channel.send(value).map_err(|e| error("CHANNEL_CLOSED", e.to_string(), false)) }
    #[tauri::command]
    pub fn subscribe_runtime_events(channel: Channel<RuntimeEvent>) -> Result<(), String> {
        let _ = channel;
        Ok(())
    }
}

fn now_ms() -> u64 { static START: std::sync::OnceLock<std::time::Instant> = std::sync::OnceLock::new(); START.get_or_init(std::time::Instant::now).elapsed().as_millis() as u64 }

pub fn run() {
    let config = DeviceConfig::new("sim-1", "演示机械手 O6");
    let mut runtime = AppRuntime::new(config.clone(), adaptive_grasp::Profile::O6);
    runtime.install_adapter(Box::new(DeviceSimulator::new("sim-1", 6)));
    tauri::Builder::default()
        .manage(RuntimeState(Mutex::new(runtime)))
        .invoke_handler(tauri::generate_handler![commands::config, commands::capabilities, commands::connection, commands::connect, commands::disconnect, commands::set_joint_target, commands::stop_all, commands::unlock, commands::telemetry, commands::subscribe_runtime_events])
        .run(tauri::generate_context!())
        .expect("error while running LinkerHand Console");
}
