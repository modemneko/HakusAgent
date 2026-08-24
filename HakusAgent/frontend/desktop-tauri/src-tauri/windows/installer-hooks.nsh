; Hakus NSIS lifecycle hooks.
; Installed builds use %USERPROFILE%\.hakus. Portable builds never execute
; this hook and keep their data beside the executable instead.
!macro NSIS_HOOK_PREINSTALL
  ; The installed desktop process receives HAKUS_INSTALL_MODE=installed from
  ; the launcher, so its user data has one documented location.
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  MessageBox MB_YESNO|MB_ICONQUESTION "删除 Hakus 的全部用户数据？这将移除 %USERPROFILE%\.hakus 中的配置、会话、凭据和日志，且无法恢复。选择“否”只卸载程序。" IDNO hakus_keep_user_data
    RMDir /r "$PROFILE\.hakus"
  hakus_keep_user_data:
!macroend
