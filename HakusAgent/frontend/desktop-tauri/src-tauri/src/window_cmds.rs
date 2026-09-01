//! Window commands — custom titlebar controls (minimize, maximize, close).
//! No more IPC bridge needed — Tauri window API handles this natively.

#[cfg(not(target_os = "android"))]
use std::time::Duration;
use tauri::{AppHandle, Manager};
use tauri_plugin_store::StoreExt;

/// Read (trayEnabled, minimizeToTray) from the persisted settings store.
fn read_tray_settings(app: &AppHandle) -> (bool, bool) {
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

/// Close (or hide) the main window.
///
/// When `trayEnabled && minimizeToTray` are both on, hides the window
/// instead of closing it so the app keeps running in the tray. The user
/// can re-open it via the tray icon (left-click or "显示/隐藏窗口" menu).
///
/// Otherwise, calls `window.close()` which fires `CloseRequested` — the
/// `on_window_event` handler in lib.rs will let it through and stop the
/// in-process Rust Runtime before the window actually closes.
#[tauri::command]
pub fn window_close(app: AppHandle) -> Result<bool, String> {
    let (tray_enabled, minimize_to_tray) = read_tray_settings(&app);
    if let Some(window) = app.get_webview_window("main") {
        if tray_enabled && minimize_to_tray {
            window.hide().map_err(|e| e.to_string())?;
        } else {
            // This fires CloseRequested; the on_window_event handler will
            // let it through (since minimizeToTray is false) and stop the
            // embedded Rust Runtime.
            window.close().map_err(|e| e.to_string())?;
        }
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

/// Dismiss the native splash screen and reveal the main window.
///
/// Called by the frontend once the embedded runtime is connected. The main
/// window is shown immediately (its own UI fades in via CSS), while the
/// splash keeps playing until its full ~2.4s design timeline has elapsed,
/// then fades out through a CSS class applied with `eval` and is closed
/// after the transition finishes. Safe to call multiple times — every step
/// is a no-op when the window is already gone/visible.
#[cfg(not(target_os = "android"))]
#[tauri::command]
pub fn finish_splash(app: AppHandle) -> Result<bool, String> {
    const SPLASH_MIN_DISPLAY_MS: u64 = 2400;
    const SPLASH_FADE_MS: u64 = 600; // 480ms CSS transition + buffer

    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
    }

    if let Some(splash) = app.get_webview_window("splash") {
        let handle = app.clone();
        std::thread::spawn(move || {
            // Honour the splash design timeline even when the UI boots fast:
            // wait out the remainder before starting the fade.
            if let Some(started) = crate::SPLASH_CREATED_AT.get() {
                let elapsed = started.elapsed().as_millis() as u64;
                if elapsed < SPLASH_MIN_DISPLAY_MS {
                    std::thread::sleep(Duration::from_millis(SPLASH_MIN_DISPLAY_MS - elapsed));
                }
            }
            let _ = splash.eval("document.documentElement.classList.add('is-fading');");
            std::thread::sleep(Duration::from_millis(SPLASH_FADE_MS));
            if let Some(splash) = handle.get_webview_window("splash") {
                let _ = splash.close();
            }
        });
    }
    Ok(true)
}
