//! Thread types for the `crates/core` boundary (issue #5261 / #3313).
//!
//! Re-exports the protocol ids plus the thread-status enums that every
//! consumer (TUI, CLI, app-server, tests) needs. The TUI's
//! `runtime_threads.rs` and `core/engine.rs` both import from here after the
//! move so `is_terminal` / `is_active` / `is_paused` is a single `Status`
//! trait, not three copies.

pub use hakus_protocol::ids::{SessionId, ThreadId};
pub use hakus_protocol::{Status, ThreadStatus};

/// Back-compat alias: the TUI's `RuntimeThread` is the same shape as the
/// protocol `Thread` now that the ids are typed. Callers that still name
/// `RuntimeThread` get this alias so the rename is mechanical.
pub type RuntimeThread = hakus_protocol::Thread;
