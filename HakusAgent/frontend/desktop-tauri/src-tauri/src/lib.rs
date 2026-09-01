mod embedded_backend;
#[cfg(not(target_os = "android"))]
mod updater_cmds;
#[cfg(not(target_os = "android"))]
mod shortcut_cmds;
mod store_cmds;
#[cfg(not(target_os = "android"))]
mod voice_cmds;
#[cfg(not(target_os = "android"))]
mod tray_cmds;
#[cfg(not(target_os = "android"))]
mod window_cmds;

#[cfg(not(target_os = "android"))]
use std::time::{Duration, Instant};
#[cfg(not(target_os = "android"))]
use tauri::{
    menu::{Menu, MenuItem, PredefinedMenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconEvent},
    Manager, RunEvent, WebviewUrl, WebviewWindowBuilder, WindowEvent,
};
#[cfg(not(target_os = "android"))]
use tauri_plugin_store::StoreExt;

#[cfg(target_os = "android")]
use tauri::{Manager, RunEvent};

#[cfg(target_os = "android")]
fn configure_android_webview(app: &tauri::AppHandle) -> tauri::Result<()> {
    let Some(webview) = app.get_webview_window("main") else {
        eprintln!("[setup] Main Android WebView is not ready; keeping CSS viewport fallback");
        return Ok(());
    };

    if let Err(error) = webview.with_webview(|webview| {
        use jni::objects::JValue;

        webview.jni_handle().exec(|env, _, webview| {
            let result = (|| -> jni::errors::Result<()> {
                let settings = env
                    .call_method(
                        &webview,
                        "getSettings",
                        "()Landroid/webkit/WebSettings;",
                        &[],
                    )?
                    .l()?;

                // Never let Android fall back to the legacy ~980px desktop
                // viewport. Responsive CSS must see the actual WebView width.
                env.call_method(&settings, "setUseWideViewPort", "(Z)V", &[JValue::Bool(0)])?;
                env.call_method(
                    &settings,
                    "setLoadWithOverviewMode",
                    "(Z)V",
                    &[JValue::Bool(0)],
                )?;
                Ok(())
            })();

            if let Err(error) = result {
                eprintln!("[setup] Failed to normalize Android WebView viewport: {error}");
            }
        });
    }) {
        eprintln!("[setup] Failed to access Android WebView: {error}");
    }

    Ok(())
}

/// Read (trayEnabled, minimizeToTray) from the persisted settings store.
/// Defaults to (true, false) when the store is unavailable or keys missing.
#[cfg(not(target_os = "android"))]
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

/// Stop the in-process Rust Runtime API if it is still running.
/// Called from every exit path (close button, tray quit, Alt+F4, process kill)
/// so the runtime task does not linger after the UI disappears.
#[cfg(not(target_os = "android"))]
fn kill_backend(app: &tauri::AppHandle) {
    if let Some(state) = app.try_state::<embedded_backend::EmbeddedBackendState>() {
        state.stop();
    }
    if let Some(state) = app.try_state::<voice_cmds::VoiceProcessState>() {
        voice_cmds::stop_process(state.inner());
    }
}

/// Toggle the main window's visibility — used by tray left-click and the
/// "显示/隐藏窗口" context menu item. If the window is visible, hide it;
/// if hidden, show + focus it.
#[cfg(not(target_os = "android"))]
pub(crate) fn toggle_main_window(app: &tauri::AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        if window.is_visible().unwrap_or(false) {
            let _ = window.hide();
        } else {
            let _ = window.show();
            let _ = window.set_focus();
        }
    }
}

/// Opt the main window into Windows 11 rounded corners.
///
/// With `decorations: false` the DWM draws square corners by default; the
/// explicit `DWMWCP_ROUND` preference restores the native rounded frame
/// (plus the system drop shadow enabled in tauri.conf.json).
#[cfg(target_os = "windows")]
fn apply_rounded_corners(app: &tauri::AppHandle) {
    use windows::Win32::Foundation::HWND;
    use windows::Win32::Graphics::Dwm::{
        DwmSetWindowAttribute, DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUND,
    };

    let Some(window) = app.get_webview_window("main") else {
        return;
    };
    let Ok(hwnd) = window.hwnd() else {
        return;
    };
    let preference = DWMWCP_ROUND;
    let result = unsafe {
        DwmSetWindowAttribute(
            HWND(hwnd.0),
            DWMWA_WINDOW_CORNER_PREFERENCE,
            &preference as *const _ as *const core::ffi::c_void,
            std::mem::size_of_val(&preference) as u32,
        )
    };
    if let Err(error) = result {
        eprintln!("[setup] Failed to set rounded corners: {error}");
    }
}

/// Timestamp recorded when the splash window is created so `finish_splash`
/// can enforce the full design timeline even when the UI boots faster.
#[cfg(not(target_os = "android"))]
pub static SPLASH_CREATED_AT: std::sync::OnceLock<Instant> = std::sync::OnceLock::new();

/// Create and show the native splash window.
///
/// The splash is a static HTML page (public/splash.html) so it renders
/// instantly — long before the React webview has booted — replicating the
/// Electron-era splash behaviour. The main window stays hidden until the
/// frontend invokes `finish_splash`, which fades the splash out and reveals
/// the UI. A safety timer below guarantees the main window always becomes
/// visible even if the frontend never gets to signal readiness.
#[cfg(not(target_os = "android"))]
fn show_native_splash(app: &tauri::AppHandle) {
    const SPLASH_FAILSAFE_MS: u64 = 90_000; // force-show the UI after 90s

    let _ = SPLASH_CREATED_AT.set(Instant::now());

    let build = WebviewWindowBuilder::new(
        app,
        "splash",
        WebviewUrl::App("splash.html".into()),
    )
    .title("HakusAI")
    .inner_size(560.0, 360.0)
    .center()
    .decorations(false)
    .shadow(false)
    .resizable(false)
    .maximizable(false)
    .minimizable(false)
    .skip_taskbar(true)
    .always_on_top(true)
    .focused(true)
    .visible(true);

    if let Err(error) = build.build() {
        eprintln!("[setup] Splash window failed to open: {error}");
        // Never leave the main window hidden when there is no splash.
        if let Some(window) = app.get_webview_window("main") {
            let _ = window.show();
        }
        return;
    }

    let failsafe_app = app.clone();
    std::thread::spawn(move || {
        // If the frontend never calls finish_splash (crashed webview,
        // blocked runtime, …) fade the splash and reveal the main window.
        std::thread::sleep(Duration::from_millis(SPLASH_FAILSAFE_MS));
        let main_gone = failsafe_app.get_webview_window("main").is_none();
        if let Some(splash) = failsafe_app.get_webview_window("splash") {
            let _ = splash.eval("document.documentElement.classList.add('is-fading');");
            std::thread::sleep(Duration::from_millis(600));
            if let Some(splash) = failsafe_app.get_webview_window("splash") {
                let _ = splash.close();
            }
        }
        if main_gone {
            // The user closed the app while the splash was up — don't keep
            // the process alive with zero windows.
            failsafe_app.exit(0);
            return;
        }
        if let Some(window) = failsafe_app.get_webview_window("main") {
            if !window.is_visible().unwrap_or(true) {
                let _ = window.show();
                let _ = window.set_focus();
            }
        }
    });
}

#[cfg(not(target_os = "android"))]
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
    let mut builder = tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_store::Builder::new().build());

    #[cfg(not(target_os = "android"))]
    {
        builder = builder
            // Single-instance: registering before any window-creating setup so
            // a second launch (e.g. double-clicking the exe while HakusAI
            // lives in the tray) exits immediately after focusing the
            // existing window — without this, two processes each own a tray
            // icon.
            .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
                if let Some(window) = app.get_webview_window("main") {
                    let _ = window.unminimize();
                    let _ = window.show();
                    let _ = window.set_focus();
                }
            }))
            .plugin(tauri_plugin_updater::Builder::new().build())
            .plugin(tauri_plugin_global_shortcut::Builder::new().build())
            .plugin(tauri_plugin_process::init())
            .plugin(tauri_plugin_dialog::init())
            // Desktop-only setup: start the shared Rust Runtime API and tray.
            .setup(|app| {
                app.manage(updater_cmds::UpdaterCommandState::default());
                app.manage(voice_cmds::VoiceProcessState::default());
                match embedded_backend::EmbeddedBackendState::start(app.handle()) {
                    Ok(state) => {
                        app.manage(state);
                        eprintln!(
                            "[setup] Rust Runtime auto-started, port = {}",
                            embedded_backend::EMBEDDED_BACKEND_PORT
                        );
                    }
                    Err(e) => eprintln!("[setup] Backend auto-start failed: {e}"),
                }

                // Native splash: visible immediately, hides the boot gap
                // while the main webview loads in the background.
                show_native_splash(app.handle());

                // Windows 11: restore rounded corners on the undecorated
                // window (they default to square without OS decorations).
                #[cfg(target_os = "windows")]
                apply_rounded_corners(app.handle());

                // Build the system tray icon + menu.
                if let Err(e) = setup_tray(app.handle()) {
                    eprintln!("[setup] Tray setup failed: {e}");
                }
                shortcut_cmds::register_saved_shortcut(app.handle());

                Ok(())
            })
            // ── Window close interceptor ────────────────────────────
            // If `trayEnabled && minimizeToTray`, hide the window instead of
            // closing it so the app keeps running in the tray. Otherwise let the
            // close go through and stop the embedded Rust Runtime so it does
            // not outlive the UI.
            .on_window_event(|window, event| {
                if let WindowEvent::CloseRequested { api, .. } = event {
                    // Only the MAIN window goes through the minimize-to-tray
                    // interceptor. The splash window must always be allowed
                    // to close, otherwise it would hide and linger forever
                    // when the user has tray mode enabled.
                    if window.label() != "main" {
                        return;
                    }
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
                        // Actually closing — stop the runtime so it doesn't
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
            });
    }

    #[cfg(target_os = "android")]
    {
        // Android uses the dialog plugin only for the explicit project access
        // confirmation. Folder selection itself is handled by the SAF plugin
        // below because the official dialog plugin has no folder picker on Android.
        builder = builder.plugin(tauri_plugin_dialog::init());
        builder = builder.plugin(hakus_folder_picker::init());
        // Android has no bundled Python interpreter. Start the shared Rust
        // Runtime API in-process and keep all state under app_data_dir().
        builder = builder.setup(|app| {
            configure_android_webview(app.handle())?;
            let state = embedded_backend::EmbeddedBackendState::start(app.handle())
                .map_err(std::io::Error::other)?;
            app.manage(state);
            Ok(())
        });
    }

    #[cfg(not(target_os = "android"))]
    let builder = builder.invoke_handler(tauri::generate_handler![
        // Rust Runtime API
        embedded_backend::backend_status,
        embedded_backend::backend_logs,
        embedded_backend::backend_start,
        embedded_backend::backend_stop,
        embedded_backend::backend_restart,
        embedded_backend::backend_health,
        // Store (was electron-store)
        store_cmds::store_get,
        store_cmds::store_set,
        store_cmds::store_get_all,
        store_cmds::store_clear,
        // Window (was BrowserWindow IPC)
        window_cmds::window_minimize,
        window_cmds::window_toggle_maximize,
        window_cmds::window_close,
        window_cmds::window_is_maximized,
        window_cmds::finish_splash,
        // Tray
        tray_cmds::tray_get_config,
        tray_cmds::tray_set_enabled,
        tray_cmds::tray_set_minimize_to_tray,
        // Shortcuts
        shortcut_cmds::shortcuts_get_config,
        shortcut_cmds::shortcuts_set_accelerator,
        shortcut_cmds::shortcuts_validate,
        // Updates (Electron-compatible renderer contract)
        updater_cmds::updater_get_status,
        updater_cmds::updater_check,
        updater_cmds::updater_download,
        updater_cmds::updater_install,
        updater_cmds::updater_set_auto_download,
        updater_cmds::updater_set_auto_install_on_app_quit,
        // External Celia voice process
        voice_cmds::voice_status,
        voice_cmds::voice_start_celia,
        voice_cmds::voice_stop_celia,
    ]);

    #[cfg(target_os = "android")]
    let builder = builder.invoke_handler(tauri::generate_handler![
        // Android runs the same in-process Rust Runtime as desktop. Keep the
        // lifecycle/status commands available so the settings UI is truthful.
        embedded_backend::backend_status,
        embedded_backend::backend_logs,
        embedded_backend::backend_start,
        embedded_backend::backend_stop,
        embedded_backend::backend_restart,
        embedded_backend::backend_health,
        store_cmds::store_get,
        store_cmds::store_set,
        store_cmds::store_get_all,
        store_cmds::store_clear,
    ]);

    let app = builder
        .build(tauri::generate_context!())
        .expect("error while building tauri application");

    #[cfg(not(target_os = "android"))]
    // Run loop — handle Exit / ExitRequested to clean up the embedded Rust
    // Runtime for any exit path we didn't catch in on_window_event (e.g.
    // process kill, panic, Alt+F4 when minimizeToTray is on but tray is
    // disabled, or the user clicked "退出 HakusAI" in the tray menu).
    app.run(|app_handle, event| {
        match event {
            RunEvent::ExitRequested { .. } => {
                // Last window is closing — stop the Rust Runtime before the
                // app exits so it doesn't linger after the UI is gone.
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

    #[cfg(target_os = "android")]
    app.run(|app_handle, event| {
        if matches!(event, RunEvent::Exit) {
            if let Some(state) = app_handle.try_state::<embedded_backend::EmbeddedBackendState>() {
                state.stop();
            }
        }
    });
}
