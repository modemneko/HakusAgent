//! Backend process management — spawns and manages the HakusAI Python server.
//!
//! The Python FastAPI server is called "the backend".

use std::sync::Mutex;
use tauri::{AppHandle, Manager, State};
use tauri_plugin_shell::{ShellExt, process::CommandChild};

/// State holding the running backend process handle.
pub struct BackendState {
    child: Mutex<Option<CommandChild<tauri_plugin_shell::process::CommandEvent>>>,
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
            return Ok(serde_json::json!({
                "ok": true,
                "message": "Backend already running"
            }));
        }
    }

    // Spawn the Python backend via tauri-plugin-shell
    let backend_cmd = app
        .shell()
        .sidecar("hakusai-server")
        .map_err(|e| format!("Failed to create backend command: {e}"))?;

    let (mut rx, child) = backend_cmd
        .spawn()
        .map_err(|e| format!("Failed to spawn backend: {e}"))?;

    // Store the child handle
    {
        let mut child_lock = state.child.lock().map_err(|e| e.to_string())?;
        *child_lock = Some(child);
    }

    // Read stdout to detect port
    let port_detected: Mutex<Option<u16>> = Mutex::new(None);

    // Process events from the backend
    while let Some(event) = rx.recv().await {
        match event {
            tauri_plugin_shell::process::CommandEvent::Stdout(line) => {
                let text = String::from_utf8_lossy(&line).to_string();
                let text_trimmed = text.trim_end().to_string();

                // Store log line
                {
                    let mut logs = state.logs.lock().map_err(|e| e.to_string())?;
                    if logs.len() >= 500 {
                        logs.remove(0);
                    }
                    logs.push(text_trimmed.clone());
                }

                // Detect port from HAKUSAI_PORT=XXXXX
                if let Some(port_str) = text_trimmed.strip_prefix("HAKUSAI_PORT=") {
                    if let Ok(port) = port_str.trim().parse::<u16>() {
                        let mut port_lock = state.port.lock().map_err(|e| e.to_string())?;
                        *port_lock = Some(port);
                        let mut detected = port_detected.lock().unwrap();
                        *detected = Some(port);
                    }
                }
            }
            tauri_plugin_shell::process::CommandEvent::Stderr(line) => {
                let text = String::from_utf8_lossy(&line).to_string();
                let text_trimmed = text.trim_end().to_string();
                let mut logs = state.logs.lock().map_err(|e| e.to_string())?;
                if logs.len() >= 500 {
                    logs.remove(0);
                }
                logs.push(format!("[stderr] {text_trimmed}"));
            }
            tauri_plugin_shell::process::CommandEvent::Terminated(status) => {
                // Backend process died
                let mut child_lock = state.child.lock().map_err(|e| e.to_string())?;
                *child_lock = None;
                let mut port_lock = state.port.lock().map_err(|e| e.to_string())?;
                *port_lock = None;
                return Err(format!("Backend terminated with status: {status:?}"));
            }
            _ => {}
        }

        // If we got the port, we're done starting
        let detected = port_detected.lock().unwrap();
        if detected.is_some() {
            break;
        }
    }

    let port_val = *port_detected.lock().unwrap();
    Ok(serde_json::json!({
        "ok": true,
        "port": port_val,
    }))
}

#[tauri::command]
pub fn backend_stop(
    app: AppHandle,
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
    let port_lock = state.port.lock().map_err(|e| e.to_string())?;
    let port = *port_lock;
    drop(port_lock);

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
