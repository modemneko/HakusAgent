//! Renderer-facing wrappers around `tauri-plugin-updater`.
//!
//! The plugin's built-in commands are resource-oriented, while the existing
//! settings UI expects a small Electron-compatible status object. This module
//! keeps that compatibility surface in Rust and caches a checked/downloaded
//! update for the separate buttons in the panel.

use serde::Serialize;
use std::sync::Mutex;
use tauri::AppHandle;
use tauri_plugin_store::StoreExt;
use tauri_plugin_updater::{Update, UpdaterExt};

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct UpdaterSnapshot {
    pub status: String,
    pub info: Option<UpdaterInfo>,
    pub progress: Option<f64>,
    pub error: Option<String>,
    pub auto_download: bool,
    pub auto_install_on_app_quit: bool,
    pub current_version: String,
    pub is_packaged: bool,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct UpdaterInfo {
    pub version: String,
    pub release_date: Option<String>,
    pub release_notes: Option<String>,
}

struct PendingUpdate {
    update: Update,
    bytes: Vec<u8>,
}

#[derive(Default)]
pub struct UpdaterCommandState {
    snapshot: Mutex<Option<UpdaterSnapshot>>,
    pending: Mutex<Option<PendingUpdate>>,
}

fn snapshot(app: &AppHandle, state: &UpdaterCommandState) -> Result<UpdaterSnapshot, String> {
    let store = app.store("settings.json").map_err(|error| error.to_string())?;
    let auto_download = store
        .get("autoDownload")
        .and_then(|value| value.as_bool())
        .unwrap_or(true);
    let auto_install = store
        .get("autoInstallOnAppQuit")
        .and_then(|value| value.as_bool())
        .unwrap_or(true);
    let current_version = app.package_info().version.to_string();
    let mut slot = state.snapshot.lock().map_err(|_| "updater state poisoned".to_string())?;
    let value = slot.get_or_insert_with(|| UpdaterSnapshot {
        status: "idle".to_string(),
        info: None,
        progress: None,
        error: None,
        auto_download,
        auto_install_on_app_quit: auto_install,
        current_version: current_version.clone(),
        // A debug Tauri run is the local preview; release builds are the
        // installable desktop artifact where update checks are meaningful.
        is_packaged: !cfg!(debug_assertions),
    });
    value.current_version = current_version;
    value.auto_download = auto_download;
    value.auto_install_on_app_quit = auto_install;
    Ok(value.clone())
}

fn update_snapshot(
    app: &AppHandle,
    state: &UpdaterCommandState,
    update: impl FnOnce(&mut UpdaterSnapshot),
) -> Result<UpdaterSnapshot, String> {
    let _ = snapshot(app, state)?;
    let mut slot = state.snapshot.lock().map_err(|_| "updater state poisoned".to_string())?;
    let value = slot.as_mut().ok_or_else(|| "updater state unavailable".to_string())?;
    update(value);
    Ok(value.clone())
}

fn update_info(update: &Update) -> UpdaterInfo {
    UpdaterInfo {
        version: update.version.clone(),
        release_date: update.date.map(|date| date.to_string()),
        release_notes: update.body.clone(),
    }
}

#[tauri::command]
pub fn updater_get_status(
    app: AppHandle,
    state: tauri::State<'_, UpdaterCommandState>,
) -> Result<UpdaterSnapshot, String> {
    snapshot(&app, &state)
}

#[tauri::command]
pub async fn updater_check(
    app: AppHandle,
    state: tauri::State<'_, UpdaterCommandState>,
) -> Result<UpdaterSnapshot, String> {
    let current = snapshot(&app, &state)?;
    if !current.is_packaged {
        return update_snapshot(&app, &state, |value| {
            value.status = "error".to_string();
            value.error = Some("开发模式下自动更新不可用".to_string());
            value.progress = None;
        });
    }
    let _ = update_snapshot(&app, &state, |value| {
        value.status = "checking".to_string();
        value.error = None;
        value.progress = None;
    })?;
    match app.updater().map_err(|error| error.to_string())?.check().await {
        Ok(Some(update)) => {
            let info = update_info(&update);
            state
                .pending
                .lock()
                .map_err(|_| "updater state poisoned".to_string())?
                .replace(PendingUpdate { update, bytes: Vec::new() });
            update_snapshot(&app, &state, |value| {
                value.status = "available".to_string();
                value.info = Some(info);
                value.error = None;
            })
        }
        Ok(None) => update_snapshot(&app, &state, |value| {
            value.status = "not-available".to_string();
            value.info = None;
            value.error = None;
        }),
        Err(error) => update_snapshot(&app, &state, |value| {
            value.status = "error".to_string();
            value.error = Some(error.to_string());
            value.progress = None;
        }),
    }
}

#[tauri::command]
pub async fn updater_download(
    app: AppHandle,
    state: tauri::State<'_, UpdaterCommandState>,
) -> Result<UpdaterSnapshot, String> {
    let pending = state
        .pending
        .lock()
        .map_err(|_| "updater state poisoned".to_string())?
        .take();
    let Some(mut pending) = pending else {
        return update_snapshot(&app, &state, |value| {
            value.status = "error".to_string();
            value.error = Some("请先检查更新".to_string());
        });
    };
    let info = update_info(&pending.update);
    let downloaded = pending
        .update
        .download(
            |_, _| {},
            || {},
        )
        .await;
    match downloaded {
        Ok(bytes) => {
            pending.bytes = bytes;
            state
                .pending
                .lock()
                .map_err(|_| "updater state poisoned".to_string())?
                .replace(pending);
            update_snapshot(&app, &state, |value| {
                value.status = "downloaded".to_string();
                value.info = Some(info);
                value.progress = Some(1.0);
                value.error = None;
            })
        }
        Err(error) => update_snapshot(&app, &state, |value| {
            value.status = "error".to_string();
            value.error = Some(error.to_string());
            value.progress = None;
        }),
    }
}

#[tauri::command]
pub fn updater_install(
    app: AppHandle,
    state: tauri::State<'_, UpdaterCommandState>,
) -> Result<serde_json::Value, String> {
    let pending = state
        .pending
        .lock()
        .map_err(|_| "updater state poisoned".to_string())?
        .take();
    let Some(pending) = pending else {
        return Ok(serde_json::json!({ "ok": false }));
    };
    if pending.bytes.is_empty() {
        return Ok(serde_json::json!({ "ok": false }));
    }
    pending
        .update
        .install(pending.bytes)
        .map_err(|error| error.to_string())?;
    let _ = update_snapshot(&app, &state, |value| {
        value.status = "installed".to_string();
        value.progress = Some(1.0);
        value.error = None;
    });
    app.exit(0);
    Ok(serde_json::json!({ "ok": true }))
}

#[tauri::command]
pub fn updater_set_auto_download(
    app: AppHandle,
    state: tauri::State<'_, UpdaterCommandState>,
    enabled: bool,
) -> Result<UpdaterSnapshot, String> {
    let store = app.store("settings.json").map_err(|error| error.to_string())?;
    store.set("autoDownload", serde_json::Value::Bool(enabled));
    store.save().map_err(|error| error.to_string())?;
    update_snapshot(&app, &state, |value| value.auto_download = enabled)
}

#[tauri::command]
pub fn updater_set_auto_install_on_app_quit(
    app: AppHandle,
    state: tauri::State<'_, UpdaterCommandState>,
    enabled: bool,
) -> Result<UpdaterSnapshot, String> {
    let store = app.store("settings.json").map_err(|error| error.to_string())?;
    store.set("autoInstallOnAppQuit", serde_json::Value::Bool(enabled));
    store.save().map_err(|error| error.to_string())?;
    update_snapshot(&app, &state, |value| value.auto_install_on_app_quit = enabled)
}
