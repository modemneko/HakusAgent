//! Tray commands — system tray configuration.
//! Uses tauri-plugin-store for persistence instead of electron-store.

use tauri::AppHandle;
use tauri_plugin_store::StoreExt;

#[tauri::command]
pub fn tray_get_config(app: AppHandle) -> Result<serde_json::Value, String> {
    let store = app.store("settings.json").map_err(|e| e.to_string())?;
    let enabled = store.get("trayEnabled").unwrap_or(serde_json::Value::Bool(true));
    let minimize_to_tray = store.get("minimizeToTray").unwrap_or(serde_json::Value::Bool(false));
    Ok(serde_json::json!({
        "enabled": enabled,
        "minimizeToTray": minimize_to_tray,
    }))
}

#[tauri::command]
pub fn tray_set_enabled(app: AppHandle, enabled: bool) -> Result<serde_json::Value, String> {
    let store = app.store("settings.json").map_err(|e| e.to_string())?;
    store.set("trayEnabled", serde_json::Value::Bool(enabled));
    store.save().map_err(|e| e.to_string())?;
    tray_get_config(app)
}

#[tauri::command]
pub fn tray_set_minimize_to_tray(app: AppHandle, enabled: bool) -> Result<serde_json::Value, String> {
    let store = app.store("settings.json").map_err(|e| e.to_string())?;
    store.set("minimizeToTray", serde_json::Value::Bool(enabled));
    store.save().map_err(|e| e.to_string())?;
    tray_get_config(app)
}
