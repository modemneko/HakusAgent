# HakusAI 卸载说明

## Windows

1. 在「设置 → 应用」找到 HakusAI, 点击「卸载」
2. 卸载程序会弹出对话框询问是否删除用户数据
   - **点击「是」** — 彻底清除 `~/.hakus` 目录 (config / 历史 / 记忆 / 日志)
   - **点击「否」** — 保留数据, 下次安装仍可使用

## macOS

1. 把 HakusAI.app 拖到废纸篓
2. macOS 不会自动删除应用数据, 用户数据保留在 `~/.hakus/`
3. 如需彻底清除:
   ```bash
   rm -rf ~/.hakus
   ```

## Linux (deb)

1. `sudo apt remove hakusai-client` 或 `sudo dpkg -r hakusai-client`
2. 普通卸载会保留 `~/.hakus/` 数据目录
3. 卸载完成后终端会打印数据目录位置和清除命令
4. 如需彻底清除:
   ```bash
   sudo apt purge hakusai-client
   # 或者手动:
   rm -rf ~/.hakus
   ```

## Linux (AppImage)

1. 删除 AppImage 文件
2. 用户数据保留在 `~/.hakus/`, 手动删除:
   ```bash
   rm -rf ~/.hakus
   ```

## 用户数据位置

| 平台 | 路径 |
|------|------|
| Windows | `C:\Users\<你>\.hakus\` |
| macOS | `/Users/<你>/.hakus/` |
| Linux | `/home/<你>/.hakus/` |

包含内容:
- `config.yaml` — provider 配置 / API Key / 角色 / TTS 设置
- `sessions/` — 历史会话记录
- `memory/` — 长期记忆库
- `logs/` — 运行日志
- `sidecar/` — sidecar 运行时缓存 (可安全删除)
