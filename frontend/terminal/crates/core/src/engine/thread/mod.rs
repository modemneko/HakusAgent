//! `RuntimeThreadManager` split per #3313 (issue #5261).
//!
//! The TUI's `crates/tui/src/runtime_threads.rs` (≈8,259 lines, `monitor_turn`
//! ≈1,035 lines) is the largest file in the tree. The split is pure code
//! motion, persisted JSON shape unchanged:
//! - `store` — `RuntimeThreadStore` / persisted JSON state
//!   (`<root>/{threads,turns,items,events}` + `state.json`)
//! - `executor` — turn execution (`monitor_turn`, `run_turn`,
//!   steer/subagent drains, `refresh_system_prompt`, compaction, parallel
//!   tool exec, `StuckGuard`/`ReadRepeatGuard`/`ToolCallBudget`, stream retry)
//! - `events` — `RuntimeEventEnvelope` mapping + `EventMsg` fan-out
//! - `types` — `ThreadId`/`SessionId`, `ThreadStatus`, `Thread` etc
//!
//! This cut lands the four files and the re-exports so `crates/tui` can
//! `pub use hakus_core::engine::thread::*` and the next slice can `git mv`
//! the impls file-by-file without a flag day. The behaviour stays in the TUI
//! until the move completes; `core` already owns the boundary.

pub mod events;
pub mod executor;
pub mod store;
pub mod types;

pub use events::*;
pub use store::*;
pub use types::*;
