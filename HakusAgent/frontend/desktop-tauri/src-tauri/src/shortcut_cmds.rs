//! Shortcut commands — global keyboard shortcut configuration.

use tauri::{AppHandle, Manager};
use tauri_plugin_store::StoreExt;

/// Default accelerator: Shift+CommandOrControl+H
const DEFAULT_ACCELERATOR: &str = "Shift+CommandOrControl+H";

#[tauri::command]
pub fn shortcuts_get_config(app: AppHandle) -> Result<serde_json::Value, String> {
    let store = app.store("settings.json").map_err(|e| e.to_string())?;
    let accelerator = store
        .get("shortcutAccelerator")
        .and_then(|v| v.as_str().map(|s| s.to_string()))
        .unwrap_or_else(|| DEFAULT_ACCELERATOR.to_string());
    Ok(serde_json::json!({
        "accelerator": accelerator,
        "default": DEFAULT_ACCELERATOR,
    }))
}

#[tauri::command]
pub fn shortcuts_set_accelerator(
    app: AppHandle,
    accelerator: String,
) -> Result<serde_json::Value, String> {
    // Basic validation — Tauri uses the same accelerator syntax as Electron
    if accelerator.is_empty() {
        return Ok(serde_json::json!({
            "ok": false,
            "error": "Accelerator cannot be empty"
        }));
    }

    let store = app.store("settings.json").map_err(|e| e.to_string())?;
    store.set("shortcutAccelerator", serde_json::Value::String(accelerator.clone()));
    store.save().map_err(|e| e.to_string())?;

    Ok(serde_json::json!({
        "ok": true,
        "accelerator": accelerator,
    }))
}

#[tauri::command]
pub fn shortcuts_validate(accelerator: String) -> Result<serde_json::Value, String> {
    // Basic syntax check
    let valid = !accelerator.is_empty()
        && accelerator.chars().any(|c| c.is_ascii_alphabetic());
    Ok(serde_json::json!({"valid": valid}))
}
