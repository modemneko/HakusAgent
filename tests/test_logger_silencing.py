"""
测试 Claude Code 风格的日志静默策略.

核心要求:
  - 内部 logger 的 INFO 级别**不应**出现在 stdout
  - 详细日志应写入 ~/.hakus/logs/hakusai.log
  - 设置 HAKUS_VERBOSE=1 时 INFO 才输出到 stderr
  - 错误始终能上报 (stderr)
"""
import logging
import os
import sys
from io import StringIO

import pytest

from utils.logger import get_logger, quiet_console_loggers


@pytest.fixture(autouse=True)
def reset_quiet():
    """每个测试前重置静默状态."""
    import utils.logger as lg
    lg._QUIETED = False
    yield
    lg._QUIETED = False


class TestQuietLogging:
    def test_info_does_not_print_to_stdout(self, capfd):
        """Claude Code 风格: 内部 logger 的 INFO 不应出现在 stdout."""
        quiet_console_loggers()
        logger = get_logger("hakus.hooks")
        logger.info("用户消息: 这条不应在 stdout")
        captured = capfd.readouterr()
        assert "用户消息" not in captured.out
        assert "用户消息" not in captured.err

    def test_error_goes_to_stderr(self, capfd):
        """ERROR 级别始终可被上报到 stderr."""
        quiet_console_loggers()
        # 使用新 logger 名, 避免复用之前测试的缓存配置
        logger = get_logger("hakus.test_err_marker")
        logger.error("严重错误-2")
        captured = capfd.readouterr()
        assert "严重错误-2" in captured.err

    def test_warning_silenced_in_quiet_mode(self, capfd):
        quiet_console_loggers()
        logger = get_logger("hakus.hooks")
        logger.warning("警告信息")
        captured = capfd.readouterr()
        assert "警告" not in captured.out
        assert "警告" not in captured.err

    def test_verbose_env_var(self, capfd, monkeypatch):
        """HAKUS_VERBOSE=1 时, INFO 也能输出到 stderr."""
        monkeypatch.setenv("HAKUS_VERBOSE", "1")
        logger = get_logger("hakus.test_verbose_marker")
        logger.info("详细信息应可见")
        captured = capfd.readouterr()
        # 详细模式下 INFO 写到 stderr
        assert "详细信息应可见" in captured.err

    def test_all_internal_loggers_silenced(self, capfd):
        quiet_console_loggers()
        loggers_to_test = [
            "hakus.test_all_int_1", "hakus.test_all_int_2", "hakus.test_all_int_3",
            "hakus.test_all_int_4", "hakus.test_all_int_5", "hakus.test_all_int_6",
            "hakus.test_all_int_7", "hakus.test_all_int_8",
        ]
        for name in loggers_to_test:
            logger = get_logger(name)
            logger.info(f"from {name}: this is hidden")
        captured = capfd.readouterr()
        for name in loggers_to_test:
            assert f"from {name}" not in captured.out


class TestLogFileWriting:
    def test_log_file_created(self, tmp_path, monkeypatch):
        """当 HAKUS_LOG_FILE 显式设置时, 应写到指定文件."""
        log_file = tmp_path / "hakus.log"
        monkeypatch.setenv("HAKUS_LOG_FILE", str(log_file))
        logger = get_logger("hakus.test")
        logger.info("to file")
        # 处理 handler
        import time
        for h in logger.handlers:
            h.flush()
        assert log_file.exists()
        content = log_file.read_text(encoding="utf-8")
        assert "to file" in content
