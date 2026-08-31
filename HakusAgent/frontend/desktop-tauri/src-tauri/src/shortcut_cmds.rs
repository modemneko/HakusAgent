//! Shortcut commands — global keyboard shortcut configuration.

use tauri::AppHandle;
use tauri_plugin_store::StoreExt;
use tauri_plugin_global_shortcut::{GlobalShortcutExt, ShortcutState};

/// Default accelerator: Shift+CommandOrControl+H
const DEFAULT_ACCELERATOR: &str = "Shift+CommandOrControl+H";

/// Restore the user's shortcut during app startup. Invalid or conflicting
/// shortcuts are ignored so a bad preference cannot prevent the app from
/// launching.
pub fn register_saved_shortcut(app: &AppHandle) {
    let Ok(store) = app.store("settings.json") else { return };
    let accelerator = store
        .get("toggleShortcut")
        .or_else(|| store.get("shortcutAccelerator"))
        .and_then(|value| value.as_str().map(ToOwned::to_owned))
        .unwrap_or_else(|| DEFAULT_ACCELERATOR.to_string());
    if accelerator.is_empty() { return; }
    let _ = app.global_shortcut().on_shortcut(accelerator.as_str(), |app, _shortcut, event| {
        if event.state == ShortcutState::Pressed {
            crate::toggle_main_window(app);
        }
    });
}

#[tauri::command]
pub fn shortcuts_get_config(app: AppHandle) -> Result<serde_json::Value, String> {
    let store = app.store("settings.json").map_err(|e| e.to_string())?;
    let accelerator = store
        .get("toggleShortcut")
        .or_else(|| store.get("shortcutAccelerator"))
        .and_then(|v| v.as_str().map(|s| s.to_string()))
        .unwrap_or_else(|| DEFAULT_ACCELERATOR.to_string());
    let registered = if accelerator.is_empty() {
        None
    } else if app.global_shortcut().is_registered(accelerator.as_str()) {
        Some(accelerator.clone())
    } else {
        None
    };
    Ok(serde_json::json!({
        "accelerator": accelerator,
        "default": DEFAULT_ACCELERATOR,
        "registered": registered,
    }))
}

#[tauri::command]
pub fn shortcuts_set_accelerator(
    app: AppHandle,
    accelerator: String,
) -> Result<serde_json::Value, String> {
    let store = app.store("settings.json").map_err(|e| e.to_string())?;

    let previous = store
        .get("toggleShortcut")
        .or_else(|| store.get("shortcutAccelerator"))
        .and_then(|value| value.as_str().map(ToOwned::to_owned))
        .unwrap_or_default();

    if !previous.is_empty() && previous != accelerator {
        let _ = app.global_shortcut().unregister(previous.as_str());
    }

    if !accelerator.is_empty() {
        if let Err(error) = app.global_shortcut().on_shortcut(
            accelerator.as_str(),
            |app, _shortcut, event| {
                if event.state == ShortcutState::Pressed {
                    crate::toggle_main_window(app);
                }
            },
        ) {
            // Restore the old registration if the replacement conflicts with
            // another app, so the user is never left without a working key.
            if !previous.is_empty() {
                let _ = app.global_shortcut().on_shortcut(
                    previous.as_str(),
                    |app, _shortcut, event| {
                        if event.state == ShortcutState::Pressed {
                            crate::toggle_main_window(app);
                        }
                    },
                );
            }
            return Err(error.to_string());
        }
    }

    store.set(
        "toggleShortcut",
        serde_json::Value::String(accelerator.clone()),
    );
    // Keep the legacy key in sync for older builds that still read it.
    store.set(
        "shortcutAccelerator",
        serde_json::Value::String(accelerator.clone()),
    );
    store.save().map_err(|e| e.to_string())?;

    Ok(serde_json::json!({
        "ok": true,
        "accelerator": accelerator,
    }))
}

#[tauri::command]
pub fn shortcuts_validate(accelerator: String) -> Result<serde_json::Value, String> {
    let valid = accelerator.parse::<tauri_plugin_global_shortcut::Shortcut>().is_ok();
    Ok(serde_json::json!({"valid": valid}))
}
