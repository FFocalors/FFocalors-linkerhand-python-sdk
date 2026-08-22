//! Minimal Tauri 2 assembly shell. Business logic stays in app-runtime.
use console_contracts::WireEnvelope;
use serde::Serialize;
use serde_json::Value;
use tauri::ipc::Channel;

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct RuntimeEvent {
    pub event: WireEnvelope<Value>,
}

mod commands {
    use super::*;
    #[tauri::command]
    pub fn subscribe_runtime_events(channel: Channel<RuntimeEvent>) -> Result<(), String> {
        let _ = channel;
        Ok(())
    }
}

pub fn run() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![commands::subscribe_runtime_events])
        .run(tauri::generate_context!())
        .expect("error while running LinkerHand Console");
}
