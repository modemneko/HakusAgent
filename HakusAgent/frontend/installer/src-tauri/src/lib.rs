//! HakusAI branded installer backend.
//!
//! Copies a prebuilt app payload into a user-chosen directory, creates
//! shortcuts, registers an uninstall entry, and can migrate a previous
//! install's user data.

use serde::{Deserialize, Serialize};
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;
use tauri::{Emitter, Manager};
use walkdir::WalkDir;

const PRODUCT: &str = "HakusAI";
const APP_EXE: &str = "HakusAI.exe";

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct InstallRequest {
    pub install_dir: String,
    pub create_desktop_shortcut: bool,
    pub create_start_menu: bool,
    pub launch_on_startup: bool,
    pub launch_after_install: bool,
    pub migrate_user_data: bool,
}

#[derive(Debug, Clone, Serialize)]
pub struct ProgressEvent {
    pub stage: String,
    pub message: String,
    pub percent: f32,
}

#[derive(Debug, Clone, Serialize)]
pub struct PreviousInstall {
    pub install_dir: String,
    pub version: Option<String>,
    pub user_data_dir: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct InstallResult {
    pub ok: bool,
    pub install_dir: String,
    pub message: String,
}

fn default_install_dir() -> PathBuf {
    #[cfg(target_os = "windows")]
    {
        if let Some(base) = dirs::data_local_dir() {
            return base.join("Programs").join(PRODUCT);
        }
        PathBuf::from(r"C:\Users\Public").join(PRODUCT)
    }
    #[cfg(not(target_os = "windows"))]
    {
        dirs::home_dir()
            .unwrap_or_else(|| PathBuf::from("."))
            .join(".local")
            .join("share")
            .join("hakusai")
    }
}

fn app_data_dir() -> PathBuf {
    #[cfg(target_os = "windows")]
    {
        dirs::data_dir()
            .unwrap_or_else(|| PathBuf::from("."))
            .join("HakusAI")
    }
    #[cfg(not(target_os = "windows"))]
    {
        dirs::config_dir()
            .unwrap_or_else(|| PathBuf::from("."))
            .join("HakusAI")
    }
}

fn resolve_payload_zip(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    // 1) Bundled resource (CI drops payload/app-payload.zip here)
    if let Ok(path) = app
        .path()
        .resource_dir()
        .map(|d| d.join("payload").join("app-payload.zip"))
    {
        if path.is_file() {
            return Ok(path);
        }
    }

    // 2) Adjacent to the installer exe (dev / manual packaging)
    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            let candidates = [
                dir.join("payload").join("app-payload.zip"),
                dir.join("app-payload.zip"),
                dir.join("..").join("payload").join("app-payload.zip"),
            ];
            for candidate in candidates {
                if candidate.is_file() {
                    return Ok(candidate);
                }
            }
        }
    }

    Err(
        "未找到应用安装包 app-payload.zip。请确认安装器完整，或从 GitHub Releases 重新下载。".into(),
    )
}

#[tauri::command]
fn default_install_path() -> String {
    default_install_dir().to_string_lossy().to_string()
}

#[tauri::command]
fn detect_previous_install() -> Option<PreviousInstall> {
    let dir = default_install_dir();
    let exe = dir.join(APP_EXE);
    if !exe.is_file() {
        // Also check classic Program Files
        #[cfg(target_os = "windows")]
        {
            let alt = PathBuf::from(r"C:\Program Files\HakusAI");
            if alt.join(APP_EXE).is_file() {
                let user = app_data_dir();
                return Some(PreviousInstall {
                    install_dir: alt.to_string_lossy().to_string(),
                    version: None,
                    user_data_dir: user.is_dir().then(|| user.to_string_lossy().to_string()),
                });
            }
        }
        return None;
    }

    let user = app_data_dir();
    Some(PreviousInstall {
        install_dir: dir.to_string_lossy().to_string(),
        version: None,
        user_data_dir: user.is_dir().then(|| user.to_string_lossy().to_string()),
    })
}

#[tauri::command]
fn payload_status(app: tauri::AppHandle) -> Result<serde_json::Value, String> {
    match resolve_payload_zip(&app) {
        Ok(path) => {
            let meta = fs::metadata(&path).map_err(|e| e.to_string())?;
            Ok(serde_json::json!({
                "ok": true,
                "path": path.to_string_lossy(),
                "size_bytes": meta.len(),
            }))
        }
        Err(message) => Ok(serde_json::json!({ "ok": false, "message": message })),
    }
}

#[cfg(target_os = "windows")]
fn create_shortcut(target: &Path, shortcut: &Path, working_dir: &Path, icon: &Path) -> Result<(), String> {
    if let Some(parent) = shortcut.parent() {
        fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    let target_s = target.to_string_lossy().replace('\'', "''");
    let icon_s = icon.to_string_lossy().replace('\'', "''");
    let work_s = working_dir.to_string_lossy().replace('\'', "''");
    let lnk_s = shortcut.to_string_lossy().replace('\'', "''");
    let script = format!(
        "$W=New-Object -ComObject WScript.Shell; \
         $S=$W.CreateShortcut('{lnk}'); \
         $S.TargetPath='{target}'; \
         $S.WorkingDirectory='{work}'; \
         $S.IconLocation='{icon}'; \
         $S.Save()",
        lnk = lnk_s,
        target = target_s,
        work = work_s,
        icon = icon_s,
    );
    let status = Command::new("powershell")
        .args(["-NoProfile", "-NonInteractive", "-Command", &script])
        .status()
        .map_err(|e| e.to_string())?;
    if !status.success() {
        return Err(format!("创建快捷方式失败: {}", shortcut.display()));
    }
    Ok(())
}

#[cfg(not(target_os = "windows"))]
fn create_shortcut(_target: &Path, _shortcut: &Path, _working_dir: &Path, _icon: &Path) -> Result<(), String> {
    Ok(())
}

fn write_uninstall_helper(install_dir: &Path) -> Result<(), String> {
    #[cfg(target_os = "windows")]
    {
        let helper = install_dir.join("uninstall-hakusai.ps1");
        let body = r#"
param()
$ErrorActionPreference = 'SilentlyContinue'
$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$desktop = [Environment]::GetFolderPath('Desktop')
$startMenu = Join-Path ([Environment]::GetFolderPath('StartMenu')) 'Programs\HakusAI'
$startup = [Environment]::GetFolderPath('Startup')

Remove-Item (Join-Path $desktop 'HakusAI.lnk') -Force
Remove-Item $startMenu -Recurse -Force
Remove-Item (Join-Path $startup 'HakusAI.lnk') -Force
Remove-Item (Join-Path $env:LOCALAPPDATA 'Microsoft\Windows\Start Menu\Programs\Startup\HakusAI.lnk') -Force

# Ask whether to keep user data
$keep = $true
try {
  $answer = [System.Windows.Forms.MessageBox]::Show(
    '是否同时删除用户数据（会话、设置、记忆）？',
    '卸载 HakusAI',
    [System.Windows.Forms.MessageBoxButtons]::YesNo,
    [System.Windows.Forms.MessageBoxIcon]::Question
  )
  $keep = ($answer -ne [System.Windows.Forms.DialogResult]::Yes)
} catch { }

if (-not $keep) {
  Remove-Item (Join-Path $env:APPDATA 'HakusAI') -Recurse -Force
  Remove-Item (Join-Path $env:LOCALAPPDATA 'HakusAI') -Recurse -Force
}

# Remove install tree after a short delay so this script can exit
Start-Sleep -Milliseconds 400
Start-Process cmd.exe -ArgumentList "/c ping -n 2 127.0.0.1 >nul & rmdir /s /q `"$dir`"" -WindowStyle Hidden
"#
        .to_string();
        fs::write(&helper, body).map_err(|e| e.to_string())?;
    }
    Ok(())
}

fn register_uninstall_entry(install_dir: &Path) -> Result<(), String> {
    #[cfg(target_os = "windows")]
    {
        let uninstall_cmd = format!(
            "powershell.exe -NoProfile -ExecutionPolicy Bypass -File \"{}\"",
            install_dir.join("uninstall-hakusai.ps1").display()
        );
        let display = PRODUCT;
        let publisher = "modemneko";
        let estimated = 300_000u32; // KB
        let script = format!(
            r#"$key='HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\HakusAI';
New-Item -Path $key -Force | Out-Null;
Set-ItemProperty -Path $key -Name DisplayName -Value '{display}';
Set-ItemProperty -Path $key -Name DisplayVersion -Value '0.3.0';
Set-ItemProperty -Path $key -Name Publisher -Value '{publisher}';
Set-ItemProperty -Path $key -Name InstallLocation -Value '{loc}';
Set-ItemProperty -Path $key -Name DisplayIcon -Value '{icon}';
Set-ItemProperty -Path $key -Name UninstallString -Value '{uninst}';
Set-ItemProperty -Path $key -Name EstimatedSize -Value {est} -Type DWord;
Set-ItemProperty -Path $key -Name NoModify -Value 1 -Type DWord;
Set-ItemProperty -Path $key -Name NoRepair -Value 1 -Type DWord;
"#,
            display = display,
            publisher = publisher,
            loc = install_dir.to_string_lossy().replace('\'', "''"),
            icon = install_dir.join(APP_EXE).to_string_lossy().replace('\'', "''"),
            uninst = uninstall_cmd.replace('\'', "''"),
            est = estimated,
        );
        let status = Command::new("powershell")
            .args(["-NoProfile", "-NonInteractive", "-Command", &script])
            .status()
            .map_err(|e| e.to_string())?;
        if !status.success() {
            return Err("写入卸载注册表项失败".into());
        }
    }
    Ok(())
}

fn strip_common_prefix(path: &Path) -> PathBuf {
    let mut comps = path.components();
    let Some(first) = comps.next() else {
        return PathBuf::new();
    };
    let first_name = first.as_os_str().to_string_lossy().to_string();
    let rest: PathBuf = comps.collect();
    if matches!(first_name.as_str(), "HakusAI" | "hakusai" | "app") && !rest.as_os_str().is_empty() {
        return rest;
    }
    path.to_path_buf()
}

fn extract_zip(zip_path: &Path, dest: &Path) -> Result<usize, String> {
    let file = fs::File::open(zip_path).map_err(|e| format!("打开安装包失败: {e}"))?;
    let mut archive = zip::ZipArchive::new(file).map_err(|e| format!("解析安装包失败: {e}"))?;
    fs::create_dir_all(dest).map_err(|e| e.to_string())?;

    let mut count = 0usize;
    for i in 0..archive.len() {
        let mut entry = archive.by_index(i).map_err(|e| e.to_string())?;
        let Some(enclosed) = entry.enclosed_name() else {
            continue;
        };
        let rel = strip_common_prefix(&enclosed);
        if rel.as_os_str().is_empty() {
            continue;
        }
        let out = dest.join(&rel);
        if entry.is_dir() {
            fs::create_dir_all(&out).map_err(|e| e.to_string())?;
            continue;
        }
        if let Some(parent) = out.parent() {
            fs::create_dir_all(parent).map_err(|e| e.to_string())?;
        }
        let mut outfile = fs::File::create(&out).map_err(|e| e.to_string())?;
        std::io::copy(&mut entry, &mut outfile).map_err(|e| e.to_string())?;
        count += 1;
    }
    Ok(count)
}

fn migrate_user_data(backup_from: &Path) -> Result<(), String> {
    if !backup_from.exists() {
        return Ok(());
    }
    let dest = app_data_dir();
    if dest.exists() {
        // Don't clobber an existing profile — leave it alone.
        return Ok(());
    }
    if let Some(parent) = dest.parent() {
        fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    copy_dir_recursive(backup_from, &dest).map_err(|e| e.to_string())?;
    Ok(())
}

fn copy_dir_recursive(src: &Path, dest: &Path) -> std::io::Result<()> {
    fs::create_dir_all(dest)?;
    for entry in WalkDir::new(src).into_iter().filter_map(|e| e.ok()) {
        let rel = entry.path().strip_prefix(src).unwrap();
        let target = dest.join(rel);
        if entry.file_type().is_dir() {
            fs::create_dir_all(&target)?;
        } else {
            if let Some(p) = target.parent() {
                fs::create_dir_all(p)?;
            }
            fs::copy(entry.path(), &target)?;
        }
    }
    Ok(())
}

#[tauri::command]
async fn run_install(
    app: tauri::AppHandle,
    window: tauri::Window,
    request: InstallRequest,
) -> Result<InstallResult, String> {
    let emit = |stage: &str, message: &str, percent: f32| {
        let _ = window.emit(
            "install-progress",
            ProgressEvent {
                stage: stage.into(),
                message: message.into(),
                percent,
            },
        );
    };

    emit("prepare", "检查安装包…", 0.02);
    let zip = resolve_payload_zip(&app)?;

    let install_dir = PathBuf::from(&request.install_dir);
    emit("prepare", "创建安装目录…", 0.08);
    fs::create_dir_all(&install_dir).map_err(|e| format!("无法创建安装目录: {e}"))?;

    // Snapshot user data before overwrite, if migrating.
    let user_data = app_data_dir();
    let migrate_backup = request.migrate_user_data && user_data.exists();
    let backup_dir = install_dir.join(".hakus-user-backup");

    emit("extract", "正在释放应用文件…", 0.15);
    // Clear previous app binaries but keep backup if we just wrote it.
    if install_dir.exists() {
        for entry in fs::read_dir(&install_dir).map_err(|e| e.to_string())? {
            let entry = entry.map_err(|e| e.to_string())?;
            let name = entry.file_name();
            if name == ".hakus-user-backup" {
                continue;
            }
            let path = entry.path();
            if path.is_dir() {
                let _ = fs::remove_dir_all(&path);
            } else {
                let _ = fs::remove_file(&path);
            }
        }
    }

    if migrate_backup {
        emit("migrate", "备份用户数据…", 0.22);
        let _ = fs::remove_dir_all(&backup_dir);
        copy_dir_recursive(&user_data, &backup_dir).map_err(|e| format!("备份用户数据失败: {e}"))?;
    }

    emit("extract", "正在安装应用文件…", 0.30);
    let extracted = extract_zip(&zip, &install_dir)?;
    if extracted == 0 {
        return Err("安装包为空，安装中止".into());
    }
    emit("extract", "文件释放完成", 0.72);

    let app_exe = install_dir.join(APP_EXE);
    if !app_exe.is_file() {
        // Tolerate nested layout: HakusAI/HakusAI.exe
        let nested = install_dir.join(PRODUCT).join(APP_EXE);
        if nested.is_file() {
            // Flatten one level
            for entry in fs::read_dir(install_dir.join(PRODUCT)).map_err(|e| e.to_string())? {
                let entry = entry.map_err(|e| e.to_string())?;
                let to = install_dir.join(entry.file_name());
                let _ = fs::rename(entry.path(), to);
            }
            let _ = fs::remove_dir_all(install_dir.join(PRODUCT));
        }
    }

    emit("shortcuts", "创建快捷方式…", 0.80);
    let exe = install_dir.join(APP_EXE);
    if !exe.is_file() {
        return Err(format!(
            "未在安装目录找到 {}，安装可能不完整：{}",
            APP_EXE,
            install_dir.display()
        ));
    }
    let icon = install_dir.join("icons").join("icon.ico");
    let icon_path = if icon.is_file() { icon } else { exe.clone() };

    #[cfg(target_os = "windows")]
    {
        let desktop = dirs::desktop_dir()
            .or_else(|| dirs::home_dir().map(|h| h.join("Desktop")))
            .ok_or_else(|| "无法定位桌面目录".to_string())?;
        if request.create_desktop_shortcut {
            create_shortcut(&exe, &desktop.join("HakusAI.lnk"), &install_dir, &icon_path)?;
        }

        if request.create_start_menu {
            let start = dirs::data_dir()
                .ok_or_else(|| "无法定位开始菜单".to_string())?
                .join("Microsoft")
                .join("Windows")
                .join("Start Menu")
                .join("Programs")
                .join("HakusAI");
            fs::create_dir_all(&start).map_err(|e| e.to_string())?;
            create_shortcut(&exe, &start.join("HakusAI.lnk"), &install_dir, &icon_path)?;
            create_shortcut(
                &install_dir.join("uninstall-hakusai.ps1"),
                &start.join("卸载 HakusAI.lnk"),
                &install_dir,
                &icon_path,
            )?;
        }

        if request.launch_on_startup {
            let startup = dirs::data_dir()
                .ok_or_else(|| "无法定位启动目录".to_string())?
                .join("Microsoft")
                .join("Windows")
                .join("Start Menu")
                .join("Programs")
                .join("Startup");
            create_shortcut(&exe, &startup.join("HakusAI.lnk"), &install_dir, &icon_path)?;
        }
    }

    emit("register", "写入卸载信息…", 0.88);
    write_uninstall_helper(&install_dir)?;
    if let Err(e) = register_uninstall_entry(&install_dir) {
        eprintln!("[installer] uninstall registry failed: {e}");
    }

    if migrate_backup {
        emit("migrate", "恢复用户数据…", 0.94);
        if let Err(e) = migrate_user_data(&backup_dir) {
            eprintln!("[installer] migrate failed: {e}");
        }
        let _ = fs::remove_dir_all(&backup_dir);
    }

    emit("done", "安装完成", 1.0);

    if request.launch_after_install {
        let _ = Command::new(&exe)
            .current_dir(&install_dir)
            .spawn()
            .map_err(|e| e.to_string());
    }

    Ok(InstallResult {
        ok: true,
        install_dir: install_dir.to_string_lossy().to_string(),
        message: format!("已安装到 {}", install_dir.display()),
    })
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_process::init())
        .on_window_event(|window, event| {
            // Transparent frameless windows can leave a ghost border if we only
            // hide — force process exit when the installer window closes.
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let app = window.app_handle().clone();
                std::thread::spawn(move || {
                    std::thread::sleep(std::time::Duration::from_millis(80));
                    app.exit(0);
                });
            }
        })
        .invoke_handler(tauri::generate_handler![
            default_install_path,
            detect_previous_install,
            payload_status,
            run_install,
        ])
        .run(tauri::generate_context!())
        .expect("error while running hakusai installer");
}
