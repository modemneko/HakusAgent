//! Backend process management — spawns and manages the HakusAI Python server.
//!
//! The Python FastAPI server is called "the backend".
//! Default port is 48081 (matching apiClient default).

use std::sync::Mutex;
use tauri::{AppHandle, Manager, State};
use tauri_plugin_shell::{ShellExt, process::CommandChild};

const DEFAULT_BACKEND_PORT: u16 = 48081;

/// State holding the running backend process handle.
pub struct BackendState {
    child: Mutex<Option<CommandChild>>,
    port: Mutex<Option<u16>>,
    logs: Mutex<Vec<String>>,
}

impl BackendState {
    pub fn new() -> Self {
        Self {
            child: Mutex::new(None),
            port: Mutex::new(None),
            logs: Mutex::new(Vec::with_capacity(500)),
        }
    }
}

// ── Tauri Commands ─────────────────────────────────────────────────

#[tauri::command]
pub fn backend_status(state: State<BackendState>) -> Result<serde_json::Value, String> {
    let child_lock = state.child.lock().map_err(|e| e.to_string())?;
    let port_lock = state.port.lock().map_err(|e| e.to_string())?;
    let running = child_lock.is_some();
    Ok(serde_json::json!({
        "running": running,
        "port": *port_lock,
    }))
}

#[tauri::command]
pub fn backend_logs(state: State<BackendState>) -> Result<Vec<String>, String> {
    let logs = state.logs.lock().map_err(|e| e.to_string())?;
    Ok(logs.clone())
}

#[tauri::command]
pub async fn backend_restart(
    app: AppHandle,
    state: State<'_, BackendState>,
) -> Result<serde_json::Value, String> {
    // Stop existing
    backend_stop(app.clone(), state.clone())?;

    // Small delay to let the port free up
    tokio::time::sleep(std::time::Duration::from_millis(500)).await;

    // Start fresh
    backend_start(app, state).await
}

#[tauri::command]
pub async fn backend_start(
    app: AppHandle,
    state: State<'_, BackendState>,
) -> Result<serde_json::Value, String> {
    // Check if already running
    {
        let child_lock = state.child.lock().map_err(|e| e.to_string())?;
        if child_lock.is_some() {
            let port_lock = state.port.lock().map_err(|e| e.to_string())?;
            return Ok(serde_json::json!({
                "ok": true,
                "port": *port_lock,
                "message": "Backend already running"
            }));
        }
    }

    // Spawn the Python backend via tauri-plugin-shell Command.
    // Uses `python -m hakus.server` so no pre-built binary is needed in dev.
    let backend_cmd = app
        .shell()
        .command("python")
        .args(["-m", "hakus.server"]);

    let (rx, child) = backend_cmd
        .spawn()
        .map_err(|e| format!("Failed to spawn backend: {e}"))?;

    // Store the child handle and default port
    {
        let mut child_lock = state.child.lock().map_err(|e| e.to_string())?;
        *child_lock = Some(child);
    }
    {
        let mut port_lock = state.port.lock().map_err(|e| e.to_string())?;
        *port_lock = Some(DEFAULT_BACKEND_PORT);
    }

    // Spawn a background task to collect logs (don't block the command response).
    // We access state via app.handle() since State<> isn't Send.
    let app_handle = app.clone();
    tauri::async_runtime::spawn(async move {
        let mut rx = rx;
        while let Some(event) = rx.recv().await {
            let backend_state = app_handle.state::<BackendState>();
            match event {
                tauri_plugin_shell::process::CommandEvent::Stdout(line) => {
                    let text = String::from_utf8_lossy(&line).trim_end().to_string();
                    if let Ok(mut logs) = backend_state.logs.lock() {
                        if logs.len() >= 500 {
                            logs.remove(0);
                        }
                        logs.push(text);
                    }
                }
                tauri_plugin_shell::process::CommandEvent::Stderr(line) => {
                    let text = String::from_utf8_lossy(&line).trim_end().to_string();
                    if let Ok(mut logs) = backend_state.logs.lock() {
                        if logs.len() >= 500 {
                            logs.remove(0);
                        }
                        logs.push(format!("[stderr] {text}"));
                    }
                }
                tauri_plugin_shell::process::CommandEvent::Terminated(_status) => {
                    // Backend process died — clear handles
                    if let Ok(mut child_lock) = backend_state.child.lock() {
                        *child_lock = None;
                    }
                    if let Ok(mut port_lock) = backend_state.port.lock() {
                        *port_lock = None;
                    }
                    if let Ok(mut logs) = backend_state.logs.lock() {
                        logs.push("[backend] Process terminated".to_string());
                    }
                    break;
                }
                _ => {}
            }
        }
    });

    // Return immediately with the default port — frontend will health-check
    Ok(serde_json::json!({
        "ok": true,
        "port": DEFAULT_BACKEND_PORT,
    }))
}

#[tauri::command]
pub fn backend_stop(
    _app: AppHandle,
    state: State<BackendState>,
) -> Result<serde_json::Value, String> {
    let mut child_lock = state.child.lock().map_err(|e| e.to_string())?;
    if let Some(child) = child_lock.take() {
        let _ = child.kill();
    }
    let mut port_lock = state.port.lock().map_err(|e| e.to_string())?;
    *port_lock = None;
    Ok(serde_json::json!({"ok": true}))
}

// ── Health check ───────────────────────────────────────────────────

#[tauri::command]
pub async fn backend_health(state: State<'_, BackendState>) -> Result<serde_json::Value, String> {
    // Extract port value before any await — MutexGuard is !Send
    let port: Option<u16> = {
        let port_lock = state.port.lock().map_err(|e| e.to_string())?;
        *port_lock
    }; // port_lock dropped here, before await

    if port.is_none() {
        return Ok(serde_json::json!({
            "healthy": false,
            "reason": "Backend not running"
        }));
    }

    let port = port.unwrap();
    let url = format!("http://127.0.0.1:{port}/health");

    // Simple HTTP health check
    let client = reqwest::Client::new();
    match client.get(&url).timeout(std::time::Duration::from_secs(5)).send().await {
        Ok(resp) if resp.status().is_success() => {
            Ok(serde_json::json!({"healthy": true, "port": port}))
        }
        Ok(resp) => {
            Ok(serde_json::json!({
                "healthy": false,
                "reason": format!("HTTP {}", resp.status())
            }))
        }
        Err(e) => {
            Ok(serde_json::json!({
                "healthy": false,
                "reason": e.to_string()
            }))
        }
    }
}
