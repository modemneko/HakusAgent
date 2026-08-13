//! Tray commands — system tray configuration.
//! Uses tauri-plugin-store for persistence instead of electron-store.
//!
//! The tray icon itself is built once in lib.rs::setup_tray(). These commands
//! just toggle its visibility and persist the user's preference, so the
//! setting takes effect immediately without an app restart.

use tauri::{AppHandle, Manager};  // Manager needed for app.tray_by_id()
use tauri_plugin_store::StoreExt;

#[tauri::command]
pub fn tray_get_config(app: AppHandle) -> Result<serde_json::Value, String> {
    let store = app.store("settings.json").map_err(|e| e.to_string())?;
    let enabled = store
        .get("trayEnabled")
        .and_then(|v| v.as_bool())
        .unwrap_or(true);
    let minimize_to_tray = store
        .get("minimizeToTray")
        .and_then(|v| v.as_bool())
        .unwrap_or(false);
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

    // Apply immediately: show/hide the existing tray icon.
    if let Some(tray) = app.tray_by_id("main") {
        let _ = tray.set_visible(enabled);
    }

    // If the user just disabled the tray while minimizeToTray is on, we
    // can't hide on close anymore (no tray to hide to). Roll back
    // minimizeToTray so the next close actually exits.
    if !enabled {
        let m = store
            .get("minimizeToTray")
            .and_then(|v| v.as_bool())
            .unwrap_or(false);
        if m {
            store.set("minimizeToTray", serde_json::Value::Bool(false));
            store.save().map_err(|e| e.to_string())?;
        }
    }

    tray_get_config(app)
}

#[tauri::command]
pub fn tray_set_minimize_to_tray(app: AppHandle, enabled: bool) -> Result<serde_json::Value, String> {
    let store = app.store("settings.json").map_err(|e| e.to_string())?;

    // Refuse to enable minimizeToTray if the tray itself is disabled —
    // there'd be nowhere to hide. The frontend should guard against this,
    // but we enforce it here too.
    let tray_enabled = store
        .get("trayEnabled")
        .and_then(|v| v.as_bool())
        .unwrap_or(true);
    let final_value = if !tray_enabled { false } else { enabled };

    store.set("minimizeToTray", serde_json::Value::Bool(final_value));
    store.save().map_err(|e| e.to_string())?;

    tray_get_config(app)
}
