use std::collections::BTreeSet;
use std::path::PathBuf;

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ContextSourceKind {
    Constitution,
    RepositoryLaw,
    ScopedRepositoryLaw,
    Instruction,
    Skill,
    Hook,
    Mcp,
    Memory,
    ModelProfile,
    CapabilityProfile,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ContextPriority {
    Required,
    High,
    Normal,
    Optional,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ContextSourceReceipt {
    pub id: String,
    pub kind: ContextSourceKind,
    pub priority: ContextPriority,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub path: Option<PathBuf>,
    pub bytes: u64,
    pub estimated_tokens: u64,
    pub content_hash: String,
    pub included: bool,
    pub reason: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ResourcesLoadedEvent {
    pub event_id: String,
    pub sources: Vec<ContextSourceReceipt>,
    pub assembly_ms: u64,
    pub prompt_tokens: u64,
    pub schema_tokens: u64,
}

impl ResourcesLoadedEvent {
    #[must_use]
    pub fn included_tokens(&self) -> u64 {
        self.sources
            .iter()
            .filter(|source| source.included)
            .map(|source| source.estimated_tokens)
            .sum()
    }

    pub fn validate_required_sources(&self) -> Result<(), Vec<String>> {
        let missing = self
            .sources
            .iter()
            .filter(|source| source.priority == ContextPriority::Required && !source.included)
            .map(|source| source.id.clone())
            .collect::<Vec<_>>();
        if missing.is_empty() {
            Ok(())
        } else {
            Err(missing)
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ContinuitySet {
    #[serde(default)]
    pub constraints: BTreeSet<String>,
    #[serde(default)]
    pub approvals: BTreeSet<String>,
    #[serde(default)]
    pub failed_checks: BTreeSet<String>,
    #[serde(default)]
    pub edited_paths: BTreeSet<PathBuf>,
    #[serde(default)]
    pub pending_work: BTreeSet<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CondensationEvent {
    pub event_id: String,
    pub source_start_event_id: String,
    pub source_end_event_id: String,
    pub summary_hash: String,
    pub provider: String,
    pub model: String,
    pub reason: String,
    pub continuity: ContinuitySet,
    pub input_tokens: u64,
    pub output_tokens: u64,
}

impl CondensationEvent {
    pub fn validate(&self) -> Result<(), String> {
        for (label, value) in [
            ("event_id", self.event_id.as_str()),
            ("source_start_event_id", self.source_start_event_id.as_str()),
            ("source_end_event_id", self.source_end_event_id.as_str()),
            ("summary_hash", self.summary_hash.as_str()),
            ("provider", self.provider.as_str()),
            ("model", self.model.as_str()),
            ("reason", self.reason.as_str()),
        ] {
            if value.trim().is_empty() {
                return Err(format!("condensation {label} cannot be empty"));
            }
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn required_law_cannot_be_silently_dropped() {
        let event = ResourcesLoadedEvent {
            event_id: "resources-1".to_string(),
            sources: vec![ContextSourceReceipt {
                id: "AGENTS.md".to_string(),
                kind: ContextSourceKind::RepositoryLaw,
                priority: ContextPriority::Required,
                path: Some(PathBuf::from("AGENTS.md")),
                bytes: 100,
                estimated_tokens: 25,
                content_hash: "hash".to_string(),
                included: false,
                reason: "budget".to_string(),
            }],
            assembly_ms: 1,
            prompt_tokens: 0,
            schema_tokens: 0,
        };
        assert_eq!(
            event.validate_required_sources().unwrap_err(),
            vec!["AGENTS.md"]
        );
    }

    #[test]
    fn condensation_preserves_distinct_continuity_domains() {
        let continuity = ContinuitySet {
            constraints: BTreeSet::from(["do not deploy".to_string()]),
            approvals: BTreeSet::from(["edit src only".to_string()]),
            failed_checks: BTreeSet::from(["cargo test".to_string()]),
            edited_paths: BTreeSet::from([PathBuf::from("src/lib.rs")]),
            pending_work: BTreeSet::from(["rerun test".to_string()]),
        };
        let json = serde_json::to_value(&continuity).unwrap();
        assert_eq!(json["constraints"][0], "do not deploy");
        assert_eq!(json["failed_checks"][0], "cargo test");
        assert_eq!(json["pending_work"][0], "rerun test");
    }
}
