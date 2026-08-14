mod backend;
mod store_cmds;
mod window_cmds;
mod tray_cmds;
mod shortcut_cmds;

use backend::BackendState;
use tauri::{
    Manager, WindowEvent, RunEvent,
    menu::{Menu, MenuItem, PredefinedMenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconEvent},
};
use tauri_plugin_store::StoreExt;

/// Read (trayEnabled, minimizeToTray) from the persisted settings store.
/// Defaults to (true, false) when the store is unavailable or keys missing.
fn read_tray_settings(app: &tauri::AppHandle) -> (bool, bool) {
    let store = match app.store("settings.json") {
        Ok(s) => s,
        Err(_) => return (true, false),
    };
    let tray_enabled = store
        .get("trayEnabled")
        .and_then(|v| v.as_bool())
        .unwrap_or(true);
    let minimize_to_tray = store
        .get("minimizeToTray")
        .and_then(|v| v.as_bool())
        .unwrap_or(false);
    (tray_enabled, minimize_to_tray)
}

/// Kill the spawned Python backend child process if it is still running.
/// Called from every exit path (close button, tray quit, Alt+F4, process kill)
/// so the backend doesn't linger as an orphan after the UI disappears.
fn kill_backend(app: &tauri::AppHandle) {
    if let Some(state) = app.try_state::<BackendState>() {
        state.kill_child();
    }
}

/// Toggle the main window's visibility — used by tray left-click and the
/// "显示/隐藏窗口" context menu item. If the window is visible, hide it;
/// if hidden, show + focus it.
fn toggle_main_window(app: &tauri::AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        if window.is_visible().unwrap_or(false) {
            let _ = window.hide();
        } else {
            let _ = window.show();
            let _ = window.set_focus();
        }
    }
}

/// Build (or reconfigure) the system tray icon with a context menu and
/// click handler. Idempotent — safe to call multiple times.
fn setup_tray(app: &tauri::AppHandle) -> tauri::Result<()> {
    // Retrieve the tray icon auto-created from tauri.conf.json's `trayIcon`
    // block (id defaults to "main" when not specified). If it isn't there
    // (config block removed / auto-creation failed), just bail — we don't
    // try to build one manually because that would require icon loading
    // plumbing that's easy to get wrong.
    let tray = match app.tray_by_id("main") {
        Some(t) => t,
        None => {
            eprintln!("[setup] No tray icon with id 'main' found — skipping tray setup");
            return Ok(());
        }
    };

    // Build the right-click context menu. Use a separator between the
    // show/hide action and the quit action so the destructive option is
    // visually distinct — this matches native Windows app conventions.
    let show_item = MenuItem::with_id(app, "tray_show", "显示/隐藏窗口", true, None::<&str>)?;
    let sep = PredefinedMenuItem::separator(app)?;
    let quit_item = MenuItem::with_id(app, "tray_quit", "退出 HakusAI", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&show_item, &sep, &quit_item])?;
    tray.set_menu(Some(menu))?;
    let _ = tray.set_tooltip(Some("HakusAI"));

    // Left-click toggles window visibility (Windows / Linux convention).
    // Right-click is handled automatically by the OS — it shows the menu
    // set via set_menu() above.
    tray.on_tray_icon_event(|tray, event| {
        if let TrayIconEvent::Click {
            button: MouseButton::Left,
            button_state: MouseButtonState::Up,
            ..
        } = event
        {
            toggle_main_window(tray.app_handle());
        }
    });

    // Apply the persisted `trayEnabled` setting — if the user previously
    // disabled the tray, hide it on startup.
    let (tray_enabled, _) = read_tray_settings(app);
    let _ = tray.set_visible(tray_enabled);

    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        // ── Plugins ─────────────────────────────────────────────
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_store::Builder::new().build())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .plugin(tauri_plugin_process::init())
        .plugin(tauri_plugin_dialog::init())

        // ── State ───────────────────────────────────────────────
        .manage(BackendState::new())

        // ── Setup: auto-start Python backend + tray ─────────────
        .setup(|app| {
            // spawn_backend() is non-blocking — it just calls shell.spawn()
            // and kicks off an async log reader. No need for spawn_blocking.
            match backend::spawn_backend(app.handle()) {
                Ok(port) => eprintln!("[setup] Backend auto-started, port = {port}"),
                Err(e) => eprintln!("[setup] Backend auto-start failed: {e}"),
            }

            // Build the system tray icon + menu.
            if let Err(e) = setup_tray(app.handle()) {
                eprintln!("[setup] Tray setup failed: {e}");
            }

            Ok(())
        })

        // ── Window close interceptor ────────────────────────────
        // If `trayEnabled && minimizeToTray`, hide the window instead of
        // closing it so the app keeps running in the tray. Otherwise let the
        // close go through and kill the backend child process so it doesn't
        // orphan after the UI exits.
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { api, .. } = event {
                let app = window.app_handle();
                let (tray_enabled, minimize_to_tray) = read_tray_settings(app);
                if tray_enabled && minimize_to_tray {
                    // Prevent the window from actually closing — hide it
                    // instead so the app keeps running in the tray.
                    api.prevent_close();
                    let _ = window.hide();
                    // Make sure the tray icon is visible (it might have been
                    // hidden if the user previously disabled the tray and
                    // just re-enabled it).
                    if let Some(tray) = app.tray_by_id("main") {
                        let _ = tray.set_visible(true);
                    }
                } else {
                    // Actually closing — kill the backend so it doesn't
                    // outlive the UI. The RunEvent::Exit handler below is
                    // a backup, but killing here ensures the backend dies
                    // even if some other window keeps the app alive.
                    kill_backend(app);
                }
            }
        })

        // ── Global menu event handler ───────────────────────────
        // Registering on the app (not the tray) catches menu events from
        // any source — tray context menu, window menu, etc. This is more
        // robust than tray.on_menu_event which can be silently overwritten.
        .on_menu_event(|app, event| {
            if event.id() == "tray_show" {
                toggle_main_window(app);
            } else if event.id() == "tray_quit" {
                kill_backend(app);
                app.exit(0);
            }
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
        .build(tauri::generate_context!())
        .expect("error while building tauri application");

    // Run loop — handle Exit / ExitRequested to clean up the backend child
    // process for any exit path we didn't catch in on_window_event (e.g.
    // process kill, panic, Alt+F4 when minimizeToTray is on but tray is
    // disabled, or the user clicked "退出 HakusAI" in the tray menu).
    app.run(|app_handle, event| {
        match event {
            RunEvent::ExitRequested { .. } => {
                // Last window is closing — kill the backend before the app
                // exits so it doesn't linger as an orphan.
                kill_backend(app_handle);
            }
            RunEvent::Exit => {
                // Final cleanup — duplicate of the above but covers cases
                // where Exit is triggered without ExitRequested (e.g. via
                // app.exit(0) from the tray menu).
                kill_backend(app_handle);
            }
            _ => {}
        }
    });
}
