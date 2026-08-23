use std::collections::BTreeSet;

use serde::{Deserialize, Serialize};

use super::{RUNTIME_CONTRACT_SCHEMA_VERSION, terminal::TerminalProcessPolicy};

/// Candidate profiles are implementation experiments, not public Hakus
/// modes. Plan/Act/Operate and permission posture remain independent axes.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AgentProfileCandidate {
    CurrentFull,
    ConsolidatedCore,
    SpecializedCore,
    AdaptiveCore,
}

/// Semantic abilities a profile promises regardless of model-facing tool
/// names. This lets paired trials compare combined and specialized schemas
/// without changing the task contract.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SemanticCapability {
    CommandExecution,
    FileRead,
    FileSearch,
    FileEdit,
    ActiveChecklist,
    TypedTermination,
    Verification,
    Delegation,
    Network,
    Mcp,
    Knowledge,
    Media,
    Release,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ToolActivationPolicy {
    Static,
    DeferredSearch,
    ExplicitCapability,
    Adaptive,
}

/// Exact tool/profile manifest supplied to a model for one run.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ToolProfileManifest {
    pub schema_version: u32,
    pub candidate: AgentProfileCandidate,
    pub activation_policy: ToolActivationPolicy,
    pub terminal_policy: TerminalProcessPolicy,
    pub capabilities: BTreeSet<SemanticCapability>,
    pub active_tools: BTreeSet<String>,
    pub deferred_tools: BTreeSet<String>,
    pub max_steps: u32,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub max_wall_time_seconds: Option<u64>,
}

impl ToolProfileManifest {
    #[must_use]
    pub fn new(
        candidate: AgentProfileCandidate,
        activation_policy: ToolActivationPolicy,
        terminal_policy: TerminalProcessPolicy,
        max_steps: u32,
    ) -> Self {
        Self {
            schema_version: RUNTIME_CONTRACT_SCHEMA_VERSION,
            candidate,
            activation_policy,
            terminal_policy,
            capabilities: BTreeSet::new(),
            active_tools: BTreeSet::new(),
            deferred_tools: BTreeSet::new(),
            max_steps,
            max_wall_time_seconds: None,
        }
    }

    #[must_use]
    pub fn with_capability(mut self, capability: SemanticCapability) -> Self {
        self.capabilities.insert(capability);
        self
    }

    #[must_use]
    pub fn with_active_tool(mut self, tool: impl Into<String>) -> Self {
        self.active_tools.insert(tool.into());
        self
    }

    #[must_use]
    pub fn with_deferred_tool(mut self, tool: impl Into<String>) -> Self {
        self.deferred_tools.insert(tool.into());
        self
    }

    pub fn validate(&self) -> Result<(), String> {
        if self.schema_version != RUNTIME_CONTRACT_SCHEMA_VERSION {
            return Err(format!(
                "unsupported runtime profile schema {}; expected {}",
                self.schema_version, RUNTIME_CONTRACT_SCHEMA_VERSION
            ));
        }
        if self.max_steps == 0 {
            return Err("runtime profile max_steps must be greater than zero".to_string());
        }
        if let Some(overlap) = self.active_tools.intersection(&self.deferred_tools).next() {
            return Err(format!(
                "tool `{overlap}` cannot be both active and deferred"
            ));
        }
        if !self
            .capabilities
            .contains(&SemanticCapability::TypedTermination)
        {
            return Err("runtime profile must promise typed termination".to_string());
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn candidate_profile_keeps_public_modes_out_of_the_contract() {
        let json = serde_json::to_string(&AgentProfileCandidate::AdaptiveCore).unwrap();
        assert_eq!(json, "\"adaptive_core\"");
        assert!(!json.contains("plan"));
        assert!(!json.contains("operate"));
    }

    #[test]
    fn manifest_rejects_active_deferred_overlap() {
        let manifest = ToolProfileManifest::new(
            AgentProfileCandidate::AdaptiveCore,
            ToolActivationPolicy::DeferredSearch,
            TerminalProcessPolicy::Hybrid,
            64,
        )
        .with_capability(SemanticCapability::TypedTermination)
        .with_active_tool("tool_search")
        .with_deferred_tool("tool_search");

        assert!(
            manifest
                .validate()
                .unwrap_err()
                .contains("both active and deferred")
        );
    }

    #[test]
    fn manifest_requires_typed_termination() {
        let manifest = ToolProfileManifest::new(
            AgentProfileCandidate::SpecializedCore,
            ToolActivationPolicy::Static,
            TerminalProcessPolicy::Isolated,
            32,
        );
        assert!(
            manifest
                .validate()
                .unwrap_err()
                .contains("typed termination")
        );
    }
}
