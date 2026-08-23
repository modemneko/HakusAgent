use std::collections::VecDeque;

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ActionFingerprint {
    pub operation: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub target: Option<String>,
    pub input_digest: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub outcome_digest: Option<String>,
    pub succeeded: bool,
    pub changed_state: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct ProgressGuardConfig {
    pub identical_action_limit: usize,
    pub alternating_cycle_limit: usize,
    pub no_progress_limit: usize,
    pub history_limit: usize,
}

impl Default for ProgressGuardConfig {
    fn default() -> Self {
        Self {
            identical_action_limit: 3,
            alternating_cycle_limit: 3,
            no_progress_limit: 6,
            history_limit: 16,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum GuardDecision {
    Continue,
    Warn { reason: String },
    Stop { reason: String },
}

/// Structural no-progress detector. It consumes normalized fingerprints, not
/// provider prose, so the same policy can run in TUI, headless, and tests.
#[derive(Debug, Clone)]
pub struct ProgressGuard {
    config: ProgressGuardConfig,
    history: VecDeque<ActionFingerprint>,
    warning_issued: bool,
}

impl ProgressGuard {
    #[must_use]
    pub fn new(config: ProgressGuardConfig) -> Self {
        Self {
            config,
            history: VecDeque::with_capacity(config.history_limit),
            warning_issued: false,
        }
    }

    pub fn observe(&mut self, action: ActionFingerprint) -> GuardDecision {
        if action.changed_state {
            self.warning_issued = false;
        }
        self.history.push_back(action);
        while self.history.len() > self.config.history_limit {
            self.history.pop_front();
        }

        let reason = self
            .identical_loop_reason()
            .or_else(|| self.alternating_loop_reason())
            .or_else(|| self.no_progress_reason());
        let Some(reason) = reason else {
            return GuardDecision::Continue;
        };
        if self.warning_issued {
            GuardDecision::Stop { reason }
        } else {
            self.warning_issued = true;
            GuardDecision::Warn { reason }
        }
    }

    fn identical_loop_reason(&self) -> Option<String> {
        let limit = self.config.identical_action_limit;
        if limit < 2 || self.history.len() < limit {
            return None;
        }
        let recent = self.history.iter().rev().take(limit).collect::<Vec<_>>();
        let first = recent.first()?;
        recent
            .iter()
            .all(|action| same_action(first, action))
            .then(|| {
                format!(
                    "repeated identical `{}` action without progress",
                    first.operation
                )
            })
    }

    fn alternating_loop_reason(&self) -> Option<String> {
        let cycles = self.config.alternating_cycle_limit;
        let needed = cycles.saturating_mul(2);
        if cycles < 2 || self.history.len() < needed {
            return None;
        }
        let recent = self.history.iter().rev().take(needed).collect::<Vec<_>>();
        let a = recent.first()?;
        let b = recent.get(1)?;
        if same_action(a, b) {
            return None;
        }
        recent
            .iter()
            .enumerate()
            .all(|(index, action)| same_action(if index % 2 == 0 { a } else { b }, action))
            .then(|| {
                format!(
                    "alternating `{}`/`{}` actions are cycling without progress",
                    a.operation, b.operation
                )
            })
    }

    fn no_progress_reason(&self) -> Option<String> {
        let limit = self.config.no_progress_limit;
        if limit == 0 || self.history.len() < limit {
            return None;
        }
        self.history
            .iter()
            .rev()
            .take(limit)
            .all(|action| !action.changed_state)
            .then(|| format!("{limit} consecutive actions produced no observable state change"))
    }
}

fn same_action(left: &ActionFingerprint, right: &ActionFingerprint) -> bool {
    left.operation == right.operation
        && left.target == right.target
        && left.input_digest == right.input_digest
        && left.outcome_digest == right.outcome_digest
        && left.succeeded == right.succeeded
        && left.changed_state == right.changed_state
}

#[cfg(test)]
mod tests {
    use super::*;

    fn action(operation: &str, changed_state: bool) -> ActionFingerprint {
        ActionFingerprint {
            operation: operation.to_string(),
            target: Some("src/lib.rs".to_string()),
            input_digest: operation.to_string(),
            outcome_digest: Some("same".to_string()),
            succeeded: false,
            changed_state,
        }
    }

    #[test]
    fn repeated_action_warns_then_stops() {
        let mut guard = ProgressGuard::new(ProgressGuardConfig {
            identical_action_limit: 3,
            alternating_cycle_limit: 99,
            no_progress_limit: 99,
            history_limit: 16,
        });
        assert_eq!(
            guard.observe(action("search", false)),
            GuardDecision::Continue
        );
        assert_eq!(
            guard.observe(action("search", false)),
            GuardDecision::Continue
        );
        assert!(matches!(
            guard.observe(action("search", false)),
            GuardDecision::Warn { .. }
        ));
        assert!(matches!(
            guard.observe(action("search", false)),
            GuardDecision::Stop { .. }
        ));
    }

    #[test]
    fn real_progress_clears_warning_latch() {
        let mut guard = ProgressGuard::new(ProgressGuardConfig {
            identical_action_limit: 2,
            alternating_cycle_limit: 99,
            no_progress_limit: 99,
            history_limit: 16,
        });
        guard.observe(action("search", false));
        assert!(matches!(
            guard.observe(action("search", false)),
            GuardDecision::Warn { .. }
        ));
        assert_eq!(guard.observe(action("edit", true)), GuardDecision::Continue);
        assert_eq!(
            guard.observe(action("search", false)),
            GuardDecision::Continue
        );
    }

    #[test]
    fn alternating_cycle_is_detected() {
        let mut guard = ProgressGuard::new(ProgressGuardConfig {
            identical_action_limit: 99,
            alternating_cycle_limit: 3,
            no_progress_limit: 99,
            history_limit: 16,
        });
        for operation in ["search", "read", "search", "read", "search"] {
            assert_eq!(
                guard.observe(action(operation, false)),
                GuardDecision::Continue
            );
        }
        assert!(matches!(
            guard.observe(action("read", false)),
            GuardDecision::Warn { .. }
        ));
    }
}
