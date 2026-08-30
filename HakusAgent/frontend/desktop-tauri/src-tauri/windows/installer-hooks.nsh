; Hakus NSIS lifecycle hooks.
; The embedded Rust Runtime uses Tauri's app_data_dir(), which resolves to
; %APPDATA%\com.hakusai.client on Windows. Portable builds never execute this
; hook and keep their data in the platform app-data location selected at run
; time.
!macro NSIS_HOOK_PREINSTALL
  ; The installed desktop process receives HAKUS_INSTALL_MODE=installed from
  ; the launcher, so its user data has one documented location.
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  MessageBox MB_YESNO|MB_ICONQUESTION "删除 HakusAI 的全部用户数据？这将移除应用数据目录中的配置、会话、凭据和日志，且无法恢复。选择“否”只卸载程序。" IDNO hakus_keep_user_data
    ; Current Tauri data root.
    RMDir /r "$APPDATA\com.hakusai.client"
    ; Also remove the legacy root used by pre-Tauri builds when present.
    RMDir /r "$PROFILE\.hakus"
  hakus_keep_user_data:
!macroend
