//! Backend process management — spawns and manages the HakusAI Python server.
//!
//! The Python FastAPI server is called "the backend".
//! Default port is 48081 (matching apiClient default).
//!
//! The backend is auto-started from the Tauri setup hook (lib.rs),
//! so it's already running by the time the frontend loads.

use std::sync::Mutex;
use tauri::{AppHandle, Emitter, Manager, State};
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

    /// Kill the spawned Python backend child process if it is still running.
    /// Idempotent — safe to call from every exit path (close button, tray quit,
    /// Alt+F4, process kill). Used by lib.rs::kill_backend so external modules
    /// don't need direct access to the private `child` field.
    pub fn kill_child(&self) {
        if let Ok(mut child_lock) = self.child.lock() {
            if let Some(child) = child_lock.take() {
                let _ = child.kill();
            }
        }
        if let Ok(mut port_lock) = self.port.lock() {
            *port_lock = None;
        }
    }
}

/// Spawn the Python backend. Called from the Tauri setup hook AND from the
/// backend_start command. Returns immediately with the default port;
/// the actual port is detected from `HAKUSAI_PORT=` on stdout.
pub fn spawn_backend(app: &AppHandle) -> Result<u16, String> {
    let state = app.state::<BackendState>();

    // Check if already running
    {
        let child_lock = state.child.lock().map_err(|e| e.to_string())?;
        if child_lock.is_some() {
            let port_lock = state.port.lock().map_err(|e| e.to_string())?;
            return Ok(port_lock.unwrap_or(DEFAULT_BACKEND_PORT));
        }
    }

    eprintln!("[backend] Spawning python -m hakusai_server.server ...");

    // Spawn the Python backend via tauri-plugin-shell Command.
    let backend_cmd = app
        .shell()
        .command("python")
        .args(["-m", "hakusai_server.server"]);

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

    eprintln!("[backend] Process spawned, default port = {DEFAULT_BACKEND_PORT}");

    // Spawn a background task to collect logs and detect the actual port
    let app_handle = app.clone();
    tauri::async_runtime::spawn(async move {
        let mut rx = rx;
        while let Some(event) = rx.recv().await {
            let backend_state = app_handle.state::<BackendState>();
            match event {
                tauri_plugin_shell::process::CommandEvent::Stdout(line) => {
                    let text = String::from_utf8_lossy(&line).trim_end().to_string();
                    eprintln!("[backend:stdout] {text}");

                    // Detect port from "HAKUSAI_PORT=XXXXX" printed by server.py
                    if let Some(port_str) = text.strip_prefix("HAKUSAI_PORT=") {
                        if let Ok(port) = port_str.trim().parse::<u16>() {
                            eprintln!("[backend] Detected actual port: {port}");
                            if let Ok(mut port_lock) = backend_state.port.lock() {
                                *port_lock = Some(port);
                            }
                            // Emit event to frontend so it can update the base URL
                            let _ = app_handle.emit("backend:port", port);
                        }
                    }

                    if let Ok(mut logs) = backend_state.logs.lock() {
                        if logs.len() >= 500 {
                            logs.remove(0);
                        }
                        logs.push(text);
                    }
                }
                tauri_plugin_shell::process::CommandEvent::Stderr(line) => {
                    let text = String::from_utf8_lossy(&line).trim_end().to_string();
                    eprintln!("[backend:stderr] {text}");
                    if let Ok(mut logs) = backend_state.logs.lock() {
                        if logs.len() >= 500 {
                            logs.remove(0);
                        }
                        logs.push(format!("[stderr] {text}"));
                    }
                }
                tauri_plugin_shell::process::CommandEvent::Terminated(_status) => {
                    eprintln!("[backend] Process terminated");
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

    Ok(DEFAULT_BACKEND_PORT)
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
    let port = spawn_backend(&app)?;
    Ok(serde_json::json!({
        "ok": true,
        "port": port,
    }))
}

#[tauri::command]
pub fn backend_start(
    app: AppHandle,
    _state: State<BackendState>,
) -> Result<serde_json::Value, String> {
    let port = spawn_backend(&app)?;
    Ok(serde_json::json!({
        "ok": true,
        "port": port,
    }))
}

#[tauri::command]
pub fn backend_stop(
    _app: AppHandle,
    state: State<BackendState>,
) -> Result<serde_json::Value, String> {
    state.kill_child();
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
