#!/bin/bash
# =====================================================================
# HakusAI Linux deb 卸载后钩子 (postrm)
# =====================================================================
# deb 包卸载后执行 (apt remove / dpkg -r).
# Linux 没有像 Windows NSIS 那样的交互式弹窗, 所以这里只打印提示
# 让用户决定是否手动删除 ~/.hakus 数据目录.
#
# 由 electron-builder 通过 build.linux.fpm 的 --after-remove 注入.
# =====================================================================

set -e

# 数据目录位置 (跟随当前用户)
HAKUS_DATA_DIR="${HOME}/.hakus"

# 仅在 purge 阶段才提示, 普通卸载不打印太多
case "$1" in
  purge)
    if [ -d "$HAKUS_DATA_DIR" ]; then
      echo ""
      echo "=============================================="
      echo " HakusAI 已卸载, 但保留了用户数据:"
      echo "   $HAKUS_DATA_DIR"
      echo ""
      echo " 包含:"
      echo "   - config.yaml (provider 配置 / API key / 角色)"
      echo "   - sessions/   (历史会话)"
      echo "   - memory/     (长期记忆库)"
      echo "   - logs/       (运行日志)"
      echo ""
      echo " 如需彻底清除, 执行:"
      echo "   rm -rf $HAKUS_DATA_DIR"
      echo "=============================================="
      echo ""
    fi
    ;;
  remove|upgrade|failed-upgrade|abort-install|abort-upgrade|disappear)
    # 普通 remove / upgrade 不打扰用户
    :
    ;;
esac

exit 0
