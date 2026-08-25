use std::path::PathBuf;

use serde::{Deserialize, Serialize};
use tauri::{plugin::PluginHandle, AppHandle, Manager, Runtime, State};

const ANDROID_PLUGIN_ID: &str = "com.hakusai.folderpicker";

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FolderSelection {
    pub uri: String,
    pub name: String,
    pub path: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct FolderPickerResponse {
    uri: String,
    name: String,
}

#[derive(Debug, Clone, Deserialize)]
struct FolderSyncRequest {
    uri: String,
    path: String,
}

pub struct FolderPicker<R: Runtime>(PluginHandle<R>);

#[tauri::command]
async fn pick_folder<R: Runtime>(
    app: AppHandle<R>,
    picker: State<'_, FolderPicker<R>>,
) -> Result<FolderSelection, String> {
    let app_data = app
        .path()
        .app_data_dir()
        .map_err(|error| format!("resolve app data directory: {error}"))?;
    let projects_dir = app_data.join("workspace").join("projects");
    std::fs::create_dir_all(&projects_dir)
        .map_err(|error| format!("create project workspace: {error}"))?;
    let id = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_err(|error| format!("resolve project id: {error}"))?
        .as_millis();
    let destination = projects_dir.join(format!("android-{id}"));
    std::fs::create_dir_all(&destination)
        .map_err(|error| format!("create project directory: {error}"))?;

    let response = picker
        .0
        .run_mobile_plugin::<FolderPickerResponse>(
            "pickFolder",
            serde_json::json!({ "destination": destination.to_string_lossy() }),
        )
        .map_err(|error| format!("open Android folder picker: {error}"))?;

    Ok(FolderSelection {
        uri: response.uri,
        name: response.name,
        path: destination.to_string_lossy().into_owned(),
    })
}

fn validate_project_path<R: Runtime>(app: &AppHandle<R>, path: &str) -> Result<PathBuf, String> {
    let root = app
        .path()
        .app_data_dir()
        .map_err(|error| format!("resolve app data directory: {error}"))?;
    let path = PathBuf::from(path);
    let canonical = path
        .canonicalize()
        .map_err(|error| format!("resolve project directory: {error}"))?;
    let root = root
        .canonicalize()
        .map_err(|error| format!("resolve app data directory: {error}"))?;
    if !canonical.starts_with(&root) {
        return Err("project sync path is outside HakusAI app data".to_string());
    }
    if !canonical.is_dir() {
        return Err("project sync path is not a directory".to_string());
    }
    Ok(canonical)
}

#[tauri::command]
async fn refresh_folder<R: Runtime>(
    app: AppHandle<R>,
    picker: State<'_, FolderPicker<R>>,
    request: FolderSyncRequest,
) -> Result<(), String> {
    let path = validate_project_path(&app, &request.path)?;
    picker
        .0
        .run_mobile_plugin::<serde_json::Value>(
            "refreshFolder",
            serde_json::json!({ "uri": request.uri, "path": path.to_string_lossy() }),
        )
        .map_err(|error| format!("refresh Android project: {error}"))?;
    Ok(())
}

#[tauri::command]
async fn sync_folder<R: Runtime>(
    app: AppHandle<R>,
    picker: State<'_, FolderPicker<R>>,
    request: FolderSyncRequest,
) -> Result<(), String> {
    let path = validate_project_path(&app, &request.path)?;
    picker
        .0
        .run_mobile_plugin::<serde_json::Value>(
            "syncFolder",
            serde_json::json!({ "uri": request.uri, "path": path.to_string_lossy() }),
        )
        .map_err(|error| format!("sync Android project: {error}"))?;
    Ok(())
}

pub fn init<R: Runtime>() -> tauri::plugin::TauriPlugin<R> {
    tauri::plugin::Builder::new("hakus-folder-picker")
        .invoke_handler(tauri::generate_handler![pick_folder, refresh_folder, sync_folder])
        .setup(|app, api| {
            let handle = api.register_android_plugin(ANDROID_PLUGIN_ID, "FolderPickerPlugin")?;
            app.manage(FolderPicker(handle));
            Ok(())
        })
        .build()
}

