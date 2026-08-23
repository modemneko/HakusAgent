use std::collections::BTreeSet;
use std::path::PathBuf;

use serde::{Deserialize, Serialize};

/// Process-continuity policy selected by a runtime profile.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TerminalProcessPolicy {
    /// Every command starts from an explicit cwd/environment.
    Isolated,
    /// Commands share cwd/environment and may keep one live process.
    Stateful,
    /// Isolated by default; stateful sessions are explicitly requested.
    Hybrid,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct TerminalSessionIdentity {
    pub session_id: String,
    pub host_fingerprint: String,
    pub cwd: PathBuf,
    /// Environment names only. Values are deliberately excluded from durable
    /// metadata so secrets cannot leak into manifests.
    pub environment_keys: BTreeSet<String>,
    pub shell: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TerminalSessionRecovery {
    Reattached,
    RestartRequired,
    Stale,
    Unsupported,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct TerminalBackendCapabilities {
    pub interactive: bool,
    pub background: bool,
    pub tty: bool,
    pub stateful: bool,
    pub restart_reattach: bool,
}

impl TerminalBackendCapabilities {
    pub const LOCAL: Self = Self {
        interactive: true,
        background: true,
        tty: true,
        stateful: true,
        restart_reattach: false,
    };
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct TerminalRequest {
    pub policy: TerminalProcessPolicy,
    pub interactive: bool,
    pub background: bool,
    pub tty: bool,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub session_id: Option<String>,
}

/// Fail before spawning when a backend cannot honor the declared terminal
/// contract. This avoids silently degrading interactive/background work.
pub fn validate_terminal_request(
    request: &TerminalRequest,
    backend: TerminalBackendCapabilities,
) -> Result<(), String> {
    if request.interactive && !backend.interactive {
        return Err("terminal backend does not support interactive input".to_string());
    }
    if request.background && !backend.background {
        return Err("terminal backend does not support background processes".to_string());
    }
    if request.tty && !backend.tty {
        return Err("terminal backend does not support a TTY".to_string());
    }
    if matches!(request.policy, TerminalProcessPolicy::Stateful) && !backend.stateful {
        return Err("terminal backend does not support stateful sessions".to_string());
    }
    if request.session_id.is_some() && matches!(request.policy, TerminalProcessPolicy::Isolated) {
        return Err("isolated terminal requests cannot name a shared session".to_string());
    }
    Ok(())
}

impl TerminalSessionIdentity {
    /// A persisted session is safe to reattach only when both the logical ID
    /// and host fingerprint match. PIDs alone are intentionally insufficient.
    #[must_use]
    pub fn recovery_on_host(
        &self,
        session_id: &str,
        host_fingerprint: &str,
        backend: TerminalBackendCapabilities,
    ) -> TerminalSessionRecovery {
        if !backend.stateful {
            return TerminalSessionRecovery::Unsupported;
        }
        if self.session_id != session_id || self.host_fingerprint != host_fingerprint {
            return TerminalSessionRecovery::Stale;
        }
        if backend.restart_reattach {
            TerminalSessionRecovery::Reattached
        } else {
            TerminalSessionRecovery::RestartRequired
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn external_backend_fails_before_unsupported_interactive_spawn() {
        let request = TerminalRequest {
            policy: TerminalProcessPolicy::Stateful,
            interactive: true,
            background: false,
            tty: false,
            session_id: Some("term-1".to_string()),
        };
        let backend = TerminalBackendCapabilities {
            interactive: false,
            background: false,
            tty: false,
            stateful: false,
            restart_reattach: false,
        };
        assert!(
            validate_terminal_request(&request, backend)
                .unwrap_err()
                .contains("interactive")
        );
    }

    #[test]
    fn host_fingerprint_prevents_pid_style_false_reattach() {
        let identity = TerminalSessionIdentity {
            session_id: "term-1".to_string(),
            host_fingerprint: "host-a".to_string(),
            cwd: PathBuf::from("/workspace"),
            environment_keys: BTreeSet::new(),
            shell: "zsh".to_string(),
        };
        assert_eq!(
            identity.recovery_on_host("term-1", "host-b", TerminalBackendCapabilities::LOCAL),
            TerminalSessionRecovery::Stale
        );
    }
}
