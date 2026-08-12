//! Window commands — custom titlebar controls (minimize, maximize, close).
//! No more IPC bridge needed — Tauri window API handles this natively.

use tauri::{AppHandle, Manager};

#[tauri::command]
pub fn window_minimize(app: AppHandle) -> Result<bool, String> {
    if let Some(window) = app.get_webview_window("main") {
        window.minimize().map_err(|e| e.to_string())?;
        Ok(true)
    } else {
        Err("No main window".into())
    }
}

#[tauri::command]
pub fn window_toggle_maximize(app: AppHandle) -> Result<bool, String> {
    if let Some(window) = app.get_webview_window("main") {
        let is_max = window.is_maximized().map_err(|e| e.to_string())?;
        if is_max {
            window.unmaximize().map_err(|e| e.to_string())?;
        } else {
            window.maximize().map_err(|e| e.to_string())?;
        }
        Ok(!is_max)
    } else {
        Err("No main window".into())
    }
}

#[tauri::command]
pub fn window_close(app: AppHandle) -> Result<bool, String> {
    if let Some(window) = app.get_webview_window("main") {
        window.close().map_err(|e| e.to_string())?;
        Ok(true)
    } else {
        Err("No main window".into())
    }
}

#[tauri::command]
pub fn window_is_maximized(app: AppHandle) -> Result<bool, String> {
    if let Some(window) = app.get_webview_window("main") {
        window.is_maximized().map_err(|e| e.to_string())
    } else {
        Err("No main window".into())
    }
}
