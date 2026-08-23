//! `RuntimeThreadStore` — persisted JSON state (issue #5261 / #3313).
//!
//! The store is the `state.json` + `<root>/{threads,turns,items,events}`
//! layout that `crates/state` already owns. This module is the `core`
//! owner for that layout so the TUI's `RuntimeThreadManager` can be split
//! without changing the file shape. The current `ThreadManager` in
//! `crates/core/src/lib.rs` already uses `StateStore`; this file is the
//! next home for that impl once the `git mv` lands. Until then it
//! documents the contract and exposes the typed store handle.

use hakus_protocol::ids::ThreadId;
use hakus_state::StateStore;

/// Typed handle over `StateStore` that the executor and events modules share.
/// The methods are thin wrappers so the store boundary is greppable and the
/// persisted shape can be asserted in one place (back-compat tests hold).
#[derive(Debug, Clone)]
pub struct ThreadStore {
    inner: StateStore,
    root: std::path::PathBuf,
}

impl ThreadStore {
    #[must_use]
    pub fn new(inner: StateStore, root: std::path::PathBuf) -> Self {
        Self { inner, root }
    }

    #[must_use]
    pub fn state(&self) -> &StateStore {
        &self.inner
    }

    #[must_use]
    pub fn root(&self) -> &std::path::Path {
        &self.root
    }

    pub fn thread_exists(&self, id: &ThreadId) -> anyhow::Result<bool> {
        Ok(self.inner.get_thread(id.as_str())?.is_some())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    #[test]
    fn store_wraps_state() {
        let dir = tempdir().unwrap();
        let state = StateStore::open(Some(dir.path().join("state.db"))).unwrap();
        let store = ThreadStore::new(state, dir.path().to_path_buf());
        assert!(!store.thread_exists(&ThreadId::new()).unwrap());
    }
}
