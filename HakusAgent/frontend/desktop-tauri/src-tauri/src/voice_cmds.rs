//! Desktop voice-process controls.
//!
//! The old Electron shell exposed a small Celia process lifecycle API. Keep
//! the same renderer contract in Rust so the settings panel remains useful in
//! packaged Tauri builds without granting the webview a general shell API.

use serde::{Deserialize, Serialize};
use std::{
    path::Path,
    process::{Child, Command, Stdio},
    sync::Mutex,
    time::{SystemTime, UNIX_EPOCH},
};

#[derive(Default)]
pub struct VoiceProcessState {
    child: Mutex<Option<Child>>,
    started_at: Mutex<Option<u64>>,
    last_error: Mutex<Option<String>>,
}

#[derive(Debug, Default, Deserialize)]
pub struct VoiceStartOptions {
    #[serde(default, alias = "celiaPath")]
    pub celia_path: Option<String>,
    #[serde(default, alias = "configPath")]
    pub config_path: Option<String>,
    #[serde(default, alias = "pythonCommand")]
    pub python_command: Option<String>,
    #[serde(default, alias = "openInTerminal")]
    pub open_in_terminal: Option<bool>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct VoiceProcessStatus {
    pub running: bool,
    pub pid: Option<u32>,
    pub started_at: Option<u64>,
    pub last_error: Option<String>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct VoiceProcessResult {
    pub ok: bool,
    pub running: bool,
    pub pid: Option<u32>,
    pub error: Option<String>,
}

fn now_millis() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_millis() as u64)
        .unwrap_or_default()
}

fn refresh_child(child: &mut Option<Child>) -> Result<(), String> {
    let Some(process) = child.as_mut() else {
        return Ok(());
    };
    match process.try_wait().map_err(|error| error.to_string())? {
        Some(_) => *child = None,
        None => {}
    }
    Ok(())
}

fn status_inner(state: &VoiceProcessState) -> Result<VoiceProcessStatus, String> {
    let mut child = state.child.lock().map_err(|_| "voice state poisoned".to_string())?;
    refresh_child(&mut child)?;
    let running = child.is_some();
    let pid = child.as_ref().map(Child::id);
    if !running {
        *state
            .started_at
            .lock()
            .map_err(|_| "voice state poisoned".to_string())? = None;
    }
    let last_error = state
        .last_error
        .lock()
        .map_err(|_| "voice state poisoned".to_string())?
        .clone();
    let started_at = *state
        .started_at
        .lock()
        .map_err(|_| "voice state poisoned".to_string())?;
    Ok(VoiceProcessStatus {
        running,
        pid,
        started_at,
        last_error,
    })
}

#[tauri::command]
pub fn voice_status(state: tauri::State<'_, VoiceProcessState>) -> Result<VoiceProcessStatus, String> {
    status_inner(&state)
}

#[tauri::command]
pub fn voice_start_celia(
    state: tauri::State<'_, VoiceProcessState>,
    options: Option<VoiceStartOptions>,
) -> Result<VoiceProcessResult, String> {
    let options = options.unwrap_or_default();
    let celia_path = options
        .celia_path
        .filter(|value| !value.trim().is_empty())
        .ok_or_else(|| "请先在设置中填写 Celia 项目路径".to_string())?;
    let celia_root = Path::new(&celia_path);
    let run_py = celia_root.join("run.py");
    if !run_py.is_file() {
        let error = format!("Celia run.py not found: {}", run_py.display());
        *state
            .last_error
            .lock()
            .map_err(|_| "voice state poisoned".to_string())? = Some(error.clone());
        return Ok(VoiceProcessResult {
            ok: false,
            running: false,
            pid: None,
            error: Some(error),
        });
    }

    let mut child_slot = state.child.lock().map_err(|_| "voice state poisoned".to_string())?;
    refresh_child(&mut child_slot)?;
    if let Some(child) = child_slot.as_ref() {
        return Ok(VoiceProcessResult {
            ok: true,
            running: true,
            pid: Some(child.id()),
            error: None,
        });
    }

    let python = options
        .python_command
        .filter(|value| !value.trim().is_empty())
        .unwrap_or_else(|| {
            if cfg!(windows) {
                "python".to_string()
            } else {
                "python3".to_string()
            }
        });
    let config_path = options
        .config_path
        .filter(|value| !value.trim().is_empty())
        .unwrap_or_else(|| "config.yaml".to_string());

    let mut command = Command::new(&python);
    command
        .args(["run.py", "--voice", "--config"])
        .arg(config_path)
        .current_dir(celia_root)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());

    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        // Keep the optional terminal mode, while avoiding a hidden console for
        // the normal background process.
        const CREATE_NEW_CONSOLE: u32 = 0x0000_0010;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        command.creation_flags(if options.open_in_terminal.unwrap_or(false) {
            CREATE_NEW_CONSOLE
        } else {
            CREATE_NO_WINDOW
        });
    }

    let child = match command.spawn() {
        Ok(child) => child,
        Err(error) => {
            let message = format!("启动 Celia 失败: {error}");
            *state
                .last_error
                .lock()
                .map_err(|_| "voice state poisoned".to_string())? = Some(message.clone());
            return Ok(VoiceProcessResult {
                ok: false,
                running: false,
                pid: None,
                error: Some(message),
            });
        }
    };
    let pid = child.id();
    *child_slot = Some(child);
    drop(child_slot);
    *state
        .started_at
        .lock()
        .map_err(|_| "voice state poisoned".to_string())? = Some(now_millis());
    *state
        .last_error
        .lock()
        .map_err(|_| "voice state poisoned".to_string())? = None;
    Ok(VoiceProcessResult {
        ok: true,
        running: true,
        pid: Some(pid),
        error: None,
    })
}

#[tauri::command]
pub fn voice_stop_celia(
    state: tauri::State<'_, VoiceProcessState>,
) -> Result<VoiceProcessResult, String> {
    let mut child_slot = state.child.lock().map_err(|_| "voice state poisoned".to_string())?;
    refresh_child(&mut child_slot)?;
    let Some(mut child) = child_slot.take() else {
        *state
            .started_at
            .lock()
            .map_err(|_| "voice state poisoned".to_string())? = None;
        return Ok(VoiceProcessResult {
            ok: true,
            running: false,
            pid: None,
            error: None,
        });
    };
    let pid = child.id();
    if let Err(error) = child.kill() {
        let message = format!("停止 Celia 失败: {error}");
        *state
            .last_error
            .lock()
            .map_err(|_| "voice state poisoned".to_string())? = Some(message.clone());
        *child_slot = Some(child);
        return Ok(VoiceProcessResult {
            ok: false,
            running: true,
            pid: Some(pid),
            error: Some(message),
        });
    }
    let _ = child.wait();
    *state
        .started_at
        .lock()
        .map_err(|_| "voice state poisoned".to_string())? = None;
    Ok(VoiceProcessResult {
        ok: true,
        running: false,
        pid: None,
        error: None,
    })
}

/// Best-effort cleanup used by every desktop exit path. Tauri drops managed
/// state after the event loop ends, so explicitly terminate the child first.
pub fn stop_process(state: &VoiceProcessState) {
    if let Ok(mut child_slot) = state.child.lock() {
        if let Some(mut child) = child_slot.take() {
            let _ = child.kill();
            let _ = child.wait();
        }
    }
    if let Ok(mut started_at) = state.started_at.lock() {
        *started_at = None;
    }
}
