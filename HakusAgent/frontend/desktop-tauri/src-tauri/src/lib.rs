mod backend;
mod store_cmds;
mod window_cmds;
mod tray_cmds;
mod shortcut_cmds;

use backend::BackendState;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        // ── Plugins ─────────────────────────────────────────────
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_store::Builder::new().build())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .plugin(tauri_plugin_process::init())

        // ── State ───────────────────────────────────────────────
        .manage(BackendState::new())

        // ── Setup: auto-start Python backend ────────────────────
        .setup(|app| {
            let handle = app.handle().clone();
            // Spawn backend in background — don't block window creation
            tauri::async_runtime::spawn_blocking(move || {
                match backend::spawn_backend(&handle) {
                    Ok(port) => eprintln!("[setup] Backend auto-started, port = {port}"),
                    Err(e) => eprintln!("[setup] Backend auto-start failed: {e}"),
                }
            });
            Ok(())
        })

        // ── Commands (replacing 22 IPC channels) ────────────────
        .invoke_handler(tauri::generate_handler![
            // Backend
            backend::backend_status,
            backend::backend_logs,
            backend::backend_start,
            backend::backend_stop,
            backend::backend_restart,
            backend::backend_health,
            // Store (was electron-store)
            store_cmds::store_get,
            store_cmds::store_set,
            store_cmds::store_get_all,
            // Window (was BrowserWindow IPC)
            window_cmds::window_minimize,
            window_cmds::window_toggle_maximize,
            window_cmds::window_close,
            window_cmds::window_is_maximized,
            // Tray
            tray_cmds::tray_get_config,
            tray_cmds::tray_set_enabled,
            tray_cmds::tray_set_minimize_to_tray,
            // Shortcuts
            shortcut_cmds::shortcuts_get_config,
            shortcut_cmds::shortcuts_set_accelerator,
            shortcut_cmds::shortcuts_validate,
        ])

        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
