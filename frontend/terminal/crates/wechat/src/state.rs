//! Persistent state for WeChat account credentials and per-user context tokens.
//!
//! ## Account state (`wechat.json`)
//!
//! ```json
//! { "account_id": "...", "bot_token": "...", "base_url": "...", "route_tag": "..." }
//! ```
//!
//! ## Per-user state (`wechat-state.jsonl`)
//!
//! One JSON-object per line:
//! ```json
//! {"user_id":"...","context_token":"...","updated_at":1700000000}
//! ```

use crate::models::Result;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::{Path, PathBuf};

/// Account-level credentials persisted to `wechat.json`.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct AccountState {
    pub account_id: String,
    pub bot_token: String,
    pub base_url: String,
    /// Optional routing tag returned by the server at login time.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub route_tag: Option<String>,
}

impl AccountState {
    pub fn is_empty(&self) -> bool {
        self.account_id.is_empty() || self.bot_token.is_empty()
    }
}

/// One per-user context_token entry.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct UserContextEntry {
    pub user_id: String,
    pub context_token: String,
    pub updated_at: i64,
}

/// Top-level state manager.
#[derive(Debug)]
pub struct WechatState {
    state_dir: PathBuf,
}

impl WechatState {
    /// Create a new state manager rooted at `state_dir`.
    /// The directory is created if it does not exist.
    pub fn new(state_dir: PathBuf) -> Self {
        Self { state_dir }
    }

    /// Default state dir: `$HAKUS_HOME` or `~/.hakus`.
    pub fn default_dir() -> PathBuf {
        if let Ok(home) = std::env::var("HAKUS_HOME") {
            PathBuf::from(home)
        } else if let Some(dirs) = dirs::home_dir() {
            dirs.join(".hakus")
        } else {
            PathBuf::from(".")
        }
    }

    // -- Account state -------------------------------------------------------

    fn account_path(&self) -> PathBuf {
        self.state_dir.join("wechat.json")
    }

    /// Load persisted account state. Returns `Ok(None)` if the file
    /// does not exist or is empty/unparseable.
    pub fn load_account(&self) -> Result<Option<AccountState>> {
        let path = self.account_path();
        if !path.exists() {
            return Ok(None);
        }
        let data = std::fs::read_to_string(&path)?;
        let state: AccountState = serde_json::from_str(&data)?;
        if state.is_empty() {
            return Ok(None);
        }
        Ok(Some(state))
    }

    /// Persist account state to disk.
    pub fn save_account(&self, state: &AccountState) -> Result<()> {
        self.ensure_dir()?;
        let data = serde_json::to_string_pretty(state)?;
        std::fs::write(self.account_path(), data)?;
        tracing::info!(
            account_id = %state.account_id,
            "WeChat: account state saved"
        );
        Ok(())
    }

    /// Remove persisted account state (logout).
    pub fn clear_account(&self) -> Result<()> {
        let path = self.account_path();
        if path.exists() {
            std::fs::remove_file(&path)?;
        }
        Ok(())
    }

    // -- Per-user context tokens --------------------------------------------

    fn user_state_path(&self) -> PathBuf {
        self.state_dir.join("wechat-state.jsonl")
    }

    /// Load all per-user context tokens into a `HashMap`.
    pub fn load_user_contexts(&self) -> Result<HashMap<String, String>> {
        let path = self.user_state_path();
        if !path.exists() {
            return Ok(HashMap::new());
        }
        let data = std::fs::read_to_string(&path)?;
        let mut map = HashMap::new();
        for line in data.lines() {
            let line = line.trim();
            if line.is_empty() {
                continue;
            }
            if let Ok(entry) = serde_json::from_str::<UserContextEntry>(line) {
                map.insert(entry.user_id, entry.context_token);
            }
        }
        Ok(map)
    }

    /// Update (or insert) the context token for a specific user.
    /// The JSONL file is rewritten on each call (acceptable for the
    /// small expected cardinality — a bot typically talks to < 100 users).
    pub fn save_user_context(&self, user_id: &str, context_token: &str) -> Result<()> {
        self.ensure_dir()?;
        let mut contexts = self.load_user_contexts()?;
        contexts.insert(user_id.into(), context_token.into());

        let now = chrono::Utc::now().timestamp();
        let mut lines = Vec::new();
        for (uid, token) in &contexts {
            let entry = UserContextEntry {
                user_id: uid.clone(),
                context_token: token.clone(),
                updated_at: now,
            };
            lines.push(serde_json::to_string(&entry)?);
        }

        let data = lines.join("\n") + "\n";
        std::fs::write(self.user_state_path(), data)?;
        Ok(())
    }

    /// Remove a user's context token.
    pub fn remove_user_context(&self, user_id: &str) -> Result<()> {
        let mut contexts = self.load_user_contexts()?;
        contexts.remove(user_id);

        let now = chrono::Utc::now().timestamp();
        let mut lines = Vec::new();
        for (uid, token) in &contexts {
            let entry = UserContextEntry {
                user_id: uid.clone(),
                context_token: token.clone(),
                updated_at: now,
            };
            lines.push(serde_json::to_string(&entry)?);
        }

        let data = lines.join("\n");
        if data.is_empty() {
            let path = self.user_state_path();
            if path.exists() {
                std::fs::remove_file(&path)?;
            }
        } else {
            std::fs::write(self.user_state_path(), data + "\n")?;
        }
        Ok(())
    }

    // -- Helpers -------------------------------------------------------------

    fn ensure_dir(&self) -> Result<()> {
        std::fs::create_dir_all(&self.state_dir)?;
        Ok(())
    }
}
