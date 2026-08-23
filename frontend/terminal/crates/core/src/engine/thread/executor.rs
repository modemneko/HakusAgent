//! Turn executor — the `monitor_turn` / `run_turn` leg
//! (issue #5261 / #3313).
//!
//! This will own `run_turn`, the steer/subagent drains,
//! `refresh_system_prompt()`, `should_compact`/`compact_messages_safe`,
//! `MessageRequest` build, parallel tool exec, `StuckGuard`/
//! `ReadRepeatGuard`/`ToolCallBudget`, and stream retry budget. The move
//! is file-by-file from `crates/tui/src/core/engine/turn_loop.rs`
//! (5,706 lines) so the diff stays reviewable. Until the move lands this
//! file carries the executor type and the `execpolicy` gate that guarantees
//! approvals route through the turn context identically in both modes.

use hakus_execpolicy::ExecPolicyEngine;
use hakus_protocol::ids::{SessionId, ThreadId};

/// Per-turn execution context. The `execpolicy` engine is the sole authority
/// for approvals; both TUI and headless construct it from the same
/// `permissions.toml` / `ConfigStore` so the gate never diverges.
#[derive(Debug)]
pub struct TurnExecutor {
    pub thread_id: ThreadId,
    pub session_id: SessionId,
    pub exec_policy: ExecPolicyEngine,
    pub max_steps: u32,
}

impl TurnExecutor {
    #[must_use]
    pub fn new(
        thread_id: ThreadId,
        session_id: SessionId,
        exec_policy: ExecPolicyEngine,
        max_steps: u32,
    ) -> Self {
        Self {
            thread_id,
            session_id,
            exec_policy,
            max_steps,
        }
    }

    #[must_use]
    pub fn can_execute(&self, step: u32) -> bool {
        step < self.max_steps
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn executor_respects_max_steps() {
        let ex = TurnExecutor::new(
            ThreadId::new(),
            SessionId::new(),
            ExecPolicyEngine::new(vec![], vec![]),
            2,
        );
        assert!(ex.can_execute(0));
        assert!(ex.can_execute(1));
        assert!(!ex.can_execute(2));
    }
}
