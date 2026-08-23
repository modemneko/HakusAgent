//! HakusAgent 对齐：Python `hakus.modes` 的 Rust 对应。
//!
//! Python 侧：
//! ```text
//! SWIFT_MODE = "swift"   # 快速档
//! DEEP_MODE  = "deep"    # 深度档
//! RUN_MODES  = ("swift", "deep")
//! UI_RUN_MODES = ("swift", "deep")   # TUI 展示为 Work / Code
//! ```
//! `normalize_run_mode` 接受 `work`/`code` 作为 UI 别名（Work→Swift、
//! Code→Deep），与 Python 行为一致。上游 codex 风格的 plan/agent/operate
//! 模式是另一套正交系统（自主度姿态），不在本模块管辖内。

use serde::{Deserialize, Serialize};

pub const SWIFT_MODE: RunMode = RunMode::Swift;
pub const DEEP_MODE: RunMode = RunMode::Deep;

/// HakusAgent 的两档运行模式：`Swift`（快速）/ `Deep`（深度）。
#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq, Default)]
#[serde(rename_all = "snake_case")]
pub enum RunMode {
    #[default]
    Swift,
    Deep,
}

impl RunMode {
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Swift => "swift",
            Self::Deep => "deep",
        }
    }

    /// UI 展示名：Swift → Work，Deep → Code。
    #[must_use]
    pub const fn ui_label(self) -> &'static str {
        match self {
            Self::Swift => "work",
            Self::Deep => "code",
        }
    }

    #[must_use]
    pub fn parse(value: &str) -> Option<Self> {
        normalize_run_mode(Some(value))
    }
}

/// 全部合法运行模式。
pub const RUN_MODES: &[RunMode] = &[RunMode::Swift, RunMode::Deep];

/// 归一化用户输入到 [`RunMode`]：接受 `swift/deep` 本名与 `work/code` UI
/// 别名（大小写不敏感）。与 Python `normalize_run_mode` 行为一致——无法
/// 归一化时返回 `None`。
#[must_use]
pub fn normalize_run_mode(value: Option<&str>) -> Option<RunMode> {
    let value = value?.trim().to_ascii_lowercase();
    match value.as_str() {
        "swift" | "work" => Some(RunMode::Swift),
        "deep" | "code" => Some(RunMode::Deep),
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn canonical_names_parse() {
        assert_eq!(normalize_run_mode(Some("swift")), Some(RunMode::Swift));
        assert_eq!(normalize_run_mode(Some("DEEP")), Some(RunMode::Deep));
        assert_eq!(normalize_run_mode(None), None);
        assert_eq!(normalize_run_mode(Some("")), None);
    }

    #[test]
    fn ui_aliases_work_and_code() {
        assert_eq!(normalize_run_mode(Some("work")), Some(RunMode::Swift));
        assert_eq!(normalize_run_mode(Some("Code")), Some(RunMode::Deep));
        assert_eq!(RunMode::Swift.ui_label(), "work");
        assert_eq!(RunMode::Deep.ui_label(), "code");
    }

    #[test]
    fn unknown_values_rejected() {
        assert_eq!(normalize_run_mode(Some("yolo")), None);
        assert_eq!(normalize_run_mode(Some("plan")), None);
        assert_eq!(normalize_run_mode(Some("agent")), None);
    }
}
