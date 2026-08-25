//! Android's in-process Hakus Runtime API.
//!
//! Android APKs do not contain a Python interpreter. The Tauri process starts
//! the shared Rust Runtime API instead, bound to loopback so the WebView can
//! use the same HTTP/SSE client as the desktop UI.

use std::path::PathBuf;
use std::sync::Mutex;

use tauri::{AppHandle, Manager};

pub const EMBEDDED_BACKEND_PORT: u16 = 48081;

pub struct EmbeddedBackendState {
    task: Mutex<Option<tauri::async_runtime::TokioJoinHandle<()>>>,
}

impl EmbeddedBackendState {
    pub fn start(app: &AppHandle) -> Result<Self, String> {
        let app_data_dir = app
            .path()
            .app_data_dir()
            .map_err(|error| format!("resolve Android app data directory: {error}"))?;
        let workspace = app_data_dir.join("workspace");
        std::fs::create_dir_all(&workspace)
            .map_err(|error| format!("create Android workspace: {error}"))?;

        // The canonical state root is the app's private data directory. This
        // keeps sessions, config, skills, and runtime records together and
        // avoids every legacy product-directory fallback.
        std::env::set_var("HAKUS_HOME", &app_data_dir);

        let task_workspace: PathBuf = workspace;
        let task = tauri::async_runtime::spawn(async move {
            if let Err(error) = hakus_tui::run_embedded_runtime_api(
                task_workspace,
                "127.0.0.1".to_string(),
                EMBEDDED_BACKEND_PORT,
            )
            .await
            {
                eprintln!("[android-backend] Runtime API stopped: {error:#}");
            }
        });

        Ok(Self {
            task: Mutex::new(Some(task)),
        })
    }

    pub fn stop(&self) {
        if let Ok(mut task) = self.task.lock() {
            if let Some(task) = task.take() {
                task.abort();
            }
        }
    }
}

impl Drop for EmbeddedBackendState {
    fn drop(&mut self) {
        if let Ok(task) = self.task.get_mut() {
            if let Some(task) = task.take() {
                task.abort();
            }
        }
    }
}
