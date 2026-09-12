; Hakus NSIS lifecycle hooks.
; The embedded Rust Runtime uses Tauri's app_data_dir(), which resolves to
; %APPDATA%\com.hakusai.client on Windows. Portable builds never execute this
; hook and keep their data in the platform app-data location selected at run
; time.
LangString autostartText ${LANG_SIMPCHINESE} "开机自动启动 HakusAI"
LangString autostartText ${LANG_ENGLISH} "Start HakusAI at login"
LangString HAKUS_UNINSTALL_DATA ${LANG_SIMPCHINESE} "删除 HakusAI 的全部用户数据？这将移除应用数据目录中的配置、会话、凭据和日志，且无法恢复。选择“否”只卸载程序。"
LangString HAKUS_UNINSTALL_DATA ${LANG_ENGLISH} "Delete all HakusAI user data? This removes configuration, sessions, credentials, and logs. This cannot be undone. Choose No to uninstall the program only."

!macro NSIS_HOOK_PREINSTALL
  ; The installed desktop process receives HAKUS_INSTALL_MODE=installed from
  ; the launcher, so its user data has one documented location.
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  ; Stop both the packaged executable and the old development name before
  ; removing WebView2/store files. Otherwise a tray-resident process can keep
  ; the data file open and leave uninstall residue behind.
    ; Remove the optional login autostart entry created by the installer finish page.
  DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "HakusAI"
  ExecWait '"$SYSDIR\taskkill.exe" /F /IM HakusAI.exe /T'
  ExecWait '"$SYSDIR\taskkill.exe" /F /IM desktop-tauri.exe /T'
  MessageBox MB_YESNO|MB_ICONQUESTION "$(HAKUS_UNINSTALL_DATA)" IDNO hakus_keep_user_data
    ; Current Tauri data root (tauri-plugin-store settings, runtime data).
    RMDir /r "$APPDATA\com.hakusai.client"
    ; WebView2 user data (localStorage mirror of the settings store used by
    ; the theme bootstrap and first-run detection). Leaving this behind was
    ; the "uninstall residue" that silently marked onboarding as done, so a
    ; fresh install never showed the initialization wizard.
    RMDir /r "$LOCALAPPDATA\com.hakusai.client"
    ; The shared ~/.hakus root belongs to HakusCLI and may contain sessions,
    ; config, and databases used by other clients. Never remove it as part of
    ; the desktop GUI uninstall. Clean only legacy GUI-specific roots.
    RMDir /r "$APPDATA\hakusai-client"
    RMDir /r "$LOCALAPPDATA\hakusai-client"
    RMDir /r "$APPDATA\HakusAI"
    RMDir /r "$LOCALAPPDATA\HakusAI"
  hakus_keep_user_data:
!macroend
