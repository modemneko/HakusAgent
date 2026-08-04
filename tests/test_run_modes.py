from __future__ import annotations

import pytest

from benchmark_swe import select_benchmark_modes
from hakus.modes import RUN_MODES, is_run_mode, normalize_run_mode


def test_run_mode_contract_contains_expected_modes() -> None:
    assert RUN_MODES == ("swift", "deep", "fleet")


def test_normalize_run_mode() -> None:
    assert normalize_run_mode(" Swift ") == "swift"
    assert normalize_run_mode("DEEP") == "deep"
    assert normalize_run_mode("fleet") == "fleet"
    assert normalize_run_mode("unknown") == "swift"
    assert normalize_run_mode(None) == "swift"


def test_is_run_mode() -> None:
    assert is_run_mode("swift") is True
    assert is_run_mode(" Fleet ") is True
    assert is_run_mode("fast") is False
    assert is_run_mode(None) is False


def test_select_benchmark_modes() -> None:
    assert select_benchmark_modes("swift") == ["swift"]
    assert select_benchmark_modes("fleet") == ["fleet"]
    assert select_benchmark_modes("both") == ["swift", "deep"]
    assert select_benchmark_modes("all") == ["swift", "deep", "fleet"]


def test_select_benchmark_modes_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="Unknown benchmark mode"):
        select_benchmark_modes("turbo")
