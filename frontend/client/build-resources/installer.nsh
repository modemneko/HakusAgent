; =====================================================================
; HakusAI NSIS 卸载脚本 — 自定义卸载流程
; =====================================================================
; 在标准卸载流程之后, 弹窗询问用户是否保留 ~/.hakus 数据目录
; (config.yaml / 历史会话 / 记忆库 / 日志 等)
;
; 这个脚本由 electron-builder 通过 `nsis.include` 字段注入到
; 生成的 NSIS uninstaller 中。需要在 package.json 的 build.nsis
; 配置里加 "include": "build-resources/installer.nsh".
; =====================================================================

!macro customUnInit
  ; 在卸载开始前不做任何事 (留作未来扩展, 例如备份配置)
!macroend

!macro customUnInstall
  ; =====================================================================
  ; 标准卸载流程结束后, 询问用户是否删除用户数据
  ; =====================================================================
  ; ~/.hakus 目录包含:
  ;   - config.yaml           (provider 配置 / API key / 角色 / TTS 等)
  ;   - sessions/             (历史会话)
  ;   - memory/               (长期记忆库)
  ;   - logs/                 (运行日志)
  ;   - sidecar/              (sidecar 运行时缓存)
  ;
  ; 默认保留 (IDYES=是删除, IDNO=保留). 用 MB_YESNO 让用户主动选择.
  ; =====================================================================
  MessageBox MB_YESNO|MB_ICONQUESTION \
    "是否同时删除 HakusAI 的用户数据？$\r$\n$\r$\n\
    这将删除:$\r$\n\
    • 配置文件 (config.yaml)$\r$\n\
    • 历史会话$\r$\n\
    • 长期记忆库$\r$\n\
    • 运行日志$\r$\n$\r$\n\
    点击「是」彻底清除, 点击「否」保留数据 (下次安装仍可使用).$\r$\n$\r$\n\
    数据位置: $PROFILE\.hakus" \
    /SD IDNO IDYES delete_data IDNO keep_data

  delete_data:
    ; 用户选择删除 — 删 ~/.hakus 目录
    IfFileExists "$PROFILE\.hakus" 0 +3
      RMDir /r "$PROFILE\.hakus"
      DetailPrint "已删除用户数据: $PROFILE\.hakus"
    Goto done

  keep_data:
    DetailPrint "保留用户数据: $PROFILE\.hakus"

  done:
!macroend
