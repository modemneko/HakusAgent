//! Store commands — persistent key-value settings via tauri-plugin-store.
//! Replaces electron-store.

use tauri::{AppHandle, Manager};
use tauri_plugin_store::StoreExt;

#[tauri::command]
pub fn store_get(app: AppHandle, key: String) -> Result<serde_json::Value, String> {
    let store = app.store("settings.json").map_err(|e| e.to_string())?;
    let value = store.get(&key).cloned().unwrap_or(serde_json::Value::Null);
    Ok(value)
}

#[tauri::command]
pub fn store_set(app: AppHandle, key: String, value: serde_json::Value) -> Result<(), String> {
    let store = app.store("settings.json").map_err(|e| e.to_string())?;
    store.set(&key, value);
    store.save().map_err(|e| e.to_string())?;
    Ok(())
}

#[tauri::command]
pub fn store_get_all(app: AppHandle) -> Result<serde_json::Value, String> {
    let store = app.store("settings.json").map_err(|e| e.to_string())?;
    // Return all entries as a JSON object
    let mut map = serde_json::Map::new();
    for (k, v) in store.entries() {
        let key_str = k.as_str().unwrap_or("").to_string();
        map.insert(key_str, v);
    }
    Ok(serde_json::Value::Object(map))
}
