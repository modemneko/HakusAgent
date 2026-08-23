use std::collections::BTreeMap;
use std::path::PathBuf;

use serde::{Deserialize, Serialize};

use super::{RUNTIME_CONTRACT_SCHEMA_VERSION, profile::ToolProfileManifest};

/// Reproducible runtime contract captured before an unattended or measured
/// run starts. Secret values never belong in this structure.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct RunContractManifest {
    pub schema_version: u32,
    pub binary_version: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub source_sha: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub dirty_patch_hash: Option<String>,
    pub workspace: PathBuf,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub base_revision: Option<String>,
    pub provider: String,
    pub model: String,
    pub route: String,
    pub permission_posture: String,
    pub sandbox_identity: String,
    pub network_policy: String,
    pub prompt_hash: String,
    pub profile: ToolProfileManifest,
    /// Stable hash by tool name. A resume must not silently continue with a
    /// different model-visible schema.
    pub tool_schema_hashes: BTreeMap<String, String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ManifestMismatch {
    pub field: String,
    pub saved: String,
    pub current: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ResumeCompatibility {
    Compatible,
    ExplicitMigrationRequired(Vec<ManifestMismatch>),
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct RunReadiness {
    pub ready: bool,
    #[serde(default)]
    pub blockers: Vec<String>,
    #[serde(default)]
    pub warnings: Vec<String>,
}

impl RunContractManifest {
    pub fn validate(&self) -> Result<(), String> {
        if self.schema_version != RUNTIME_CONTRACT_SCHEMA_VERSION {
            return Err(format!(
                "unsupported run manifest schema {}; expected {}",
                self.schema_version, RUNTIME_CONTRACT_SCHEMA_VERSION
            ));
        }
        self.profile.validate()?;
        for (label, value) in [
            ("binary_version", self.binary_version.as_str()),
            ("provider", self.provider.as_str()),
            ("model", self.model.as_str()),
            ("route", self.route.as_str()),
            ("permission_posture", self.permission_posture.as_str()),
            ("sandbox_identity", self.sandbox_identity.as_str()),
            ("prompt_hash", self.prompt_hash.as_str()),
        ] {
            if value.trim().is_empty() {
                return Err(format!("run manifest {label} cannot be empty"));
            }
        }
        Ok(())
    }

    #[must_use]
    pub fn readiness(&self) -> RunReadiness {
        let mut blockers = Vec::new();
        let mut warnings = Vec::new();
        if let Err(error) = self.validate() {
            blockers.push(error);
        }
        if self.source_sha.is_none() {
            warnings.push("source SHA is not available".to_string());
        }
        if self.dirty_patch_hash.is_none() {
            warnings.push("dirty patch hash is not recorded".to_string());
        }
        RunReadiness {
            ready: blockers.is_empty(),
            blockers,
            warnings,
        }
    }

    #[must_use]
    pub fn compare_for_resume(&self, current: &Self) -> ResumeCompatibility {
        let mut mismatches = Vec::new();
        compare_field(
            &mut mismatches,
            "schema_version",
            self.schema_version,
            current.schema_version,
        );
        compare_field(
            &mut mismatches,
            "provider",
            &self.provider,
            &current.provider,
        );
        compare_field(&mut mismatches, "model", &self.model, &current.model);
        compare_field(&mut mismatches, "route", &self.route, &current.route);
        compare_field(
            &mut mismatches,
            "permission_posture",
            &self.permission_posture,
            &current.permission_posture,
        );
        compare_field(
            &mut mismatches,
            "sandbox_identity",
            &self.sandbox_identity,
            &current.sandbox_identity,
        );
        compare_field(
            &mut mismatches,
            "prompt_hash",
            &self.prompt_hash,
            &current.prompt_hash,
        );
        compare_field(
            &mut mismatches,
            "profile",
            format!("{:?}", self.profile),
            format!("{:?}", current.profile),
        );
        compare_field(
            &mut mismatches,
            "tool_schema_hashes",
            format!("{:?}", self.tool_schema_hashes),
            format!("{:?}", current.tool_schema_hashes),
        );
        if mismatches.is_empty() {
            ResumeCompatibility::Compatible
        } else {
            ResumeCompatibility::ExplicitMigrationRequired(mismatches)
        }
    }
}

fn compare_field(
    mismatches: &mut Vec<ManifestMismatch>,
    field: &str,
    saved: impl ToString,
    current: impl ToString,
) {
    let saved = saved.to_string();
    let current = current.to_string();
    if saved != current {
        mismatches.push(ManifestMismatch {
            field: field.to_string(),
            saved,
            current,
        });
    }
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeSet;

    use super::*;
    use crate::core::runtime_contract::{
        profile::{AgentProfileCandidate, SemanticCapability, ToolActivationPolicy},
        terminal::TerminalProcessPolicy,
    };

    fn manifest() -> RunContractManifest {
        let mut capabilities = BTreeSet::new();
        capabilities.insert(SemanticCapability::TypedTermination);
        RunContractManifest {
            schema_version: RUNTIME_CONTRACT_SCHEMA_VERSION,
            binary_version: "0.8.68".to_string(),
            source_sha: Some("abc".to_string()),
            dirty_patch_hash: Some("patch".to_string()),
            workspace: PathBuf::from("/workspace"),
            base_revision: Some("base".to_string()),
            provider: "example".to_string(),
            model: "model".to_string(),
            route: "api".to_string(),
            permission_posture: "ask".to_string(),
            sandbox_identity: "workspace_write".to_string(),
            network_policy: "ask".to_string(),
            prompt_hash: "prompt".to_string(),
            profile: ToolProfileManifest {
                schema_version: RUNTIME_CONTRACT_SCHEMA_VERSION,
                candidate: AgentProfileCandidate::AdaptiveCore,
                activation_policy: ToolActivationPolicy::DeferredSearch,
                terminal_policy: TerminalProcessPolicy::Hybrid,
                capabilities,
                active_tools: BTreeSet::from(["tool_search".to_string()]),
                deferred_tools: BTreeSet::from(["run_verifiers".to_string()]),
                max_steps: 64,
                max_wall_time_seconds: Some(900),
            },
            tool_schema_hashes: BTreeMap::from([(
                "tool_search".to_string(),
                "schema-a".to_string(),
            )]),
        }
    }

    #[test]
    fn resume_fails_closed_on_tool_schema_drift() {
        let saved = manifest();
        let mut current = saved.clone();
        current
            .tool_schema_hashes
            .insert("tool_search".to_string(), "schema-b".to_string());
        let ResumeCompatibility::ExplicitMigrationRequired(mismatches) =
            saved.compare_for_resume(&current)
        else {
            panic!("schema drift must require migration");
        };
        assert!(
            mismatches
                .iter()
                .any(|mismatch| mismatch.field == "tool_schema_hashes")
        );
    }

    #[test]
    fn readiness_warns_without_source_identity_but_does_not_block() {
        let mut value = manifest();
        value.source_sha = None;
        let readiness = value.readiness();
        assert!(readiness.ready);
        assert_eq!(readiness.warnings, vec!["source SHA is not available"]);
    }
}
