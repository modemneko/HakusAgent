use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest, Sha256};

use super::RUNTIME_CONTRACT_SCHEMA_VERSION;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RuntimeEventKind {
    UserMessage,
    AssistantMessage,
    ToolStarted,
    ToolCompleted,
    ApprovalRequested,
    ApprovalResolved,
    SteeringQueued,
    SteeringDelivered,
    ResourcesLoaded,
    Condensation,
    Work,
    Child,
    Usage,
    Retry,
    Termination,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct RuntimeEventEnvelope {
    pub schema_version: u32,
    pub sequence: u64,
    pub event_id: String,
    pub kind: RuntimeEventKind,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub parent_event_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub causal_event_id: Option<String>,
    pub recorded_at_ms: u64,
    pub payload: Value,
    pub checksum: String,
}

impl RuntimeEventEnvelope {
    #[must_use]
    pub fn new(
        sequence: u64,
        event_id: impl Into<String>,
        kind: RuntimeEventKind,
        recorded_at_ms: u64,
        payload: Value,
    ) -> Self {
        let mut event = Self {
            schema_version: RUNTIME_CONTRACT_SCHEMA_VERSION,
            sequence,
            event_id: event_id.into(),
            kind,
            parent_event_id: None,
            causal_event_id: None,
            recorded_at_ms,
            payload,
            checksum: String::new(),
        };
        event.checksum = event.expected_checksum();
        event
    }

    #[must_use]
    pub fn expected_checksum(&self) -> String {
        let canonical = serde_json::json!({
            "schema_version": self.schema_version,
            "sequence": self.sequence,
            "event_id": self.event_id,
            "kind": self.kind,
            "parent_event_id": self.parent_event_id,
            "causal_event_id": self.causal_event_id,
            "recorded_at_ms": self.recorded_at_ms,
            "payload": self.payload,
        });
        let bytes = serde_json::to_vec(&canonical).expect("runtime event JSON is serializable");
        let digest = Sha256::digest(bytes);
        digest.iter().map(|byte| format!("{byte:02x}")).collect()
    }

    pub fn validate(&self) -> Result<(), String> {
        if self.schema_version != RUNTIME_CONTRACT_SCHEMA_VERSION {
            return Err(format!(
                "unsupported runtime event schema {}",
                self.schema_version
            ));
        }
        if self.event_id.trim().is_empty() {
            return Err("runtime event ID cannot be empty".to_string());
        }
        let expected = self.expected_checksum();
        if self.checksum != expected {
            return Err(format!("runtime event {} checksum mismatch", self.event_id));
        }
        Ok(())
    }
}

#[derive(Debug, Default, Clone)]
pub struct AppendOnlyRuntimeLedger {
    events: Vec<RuntimeEventEnvelope>,
}

impl AppendOnlyRuntimeLedger {
    pub fn append(&mut self, event: RuntimeEventEnvelope) -> Result<(), String> {
        event.validate()?;
        let expected_sequence = self.events.last().map_or(0, |last| last.sequence + 1);
        if event.sequence != expected_sequence {
            return Err(format!(
                "runtime event sequence {} does not follow {}",
                event.sequence, expected_sequence
            ));
        }
        if self
            .events
            .iter()
            .any(|item| item.event_id == event.event_id)
        {
            return Err(format!("duplicate runtime event ID `{}`", event.event_id));
        }
        self.events.push(event);
        Ok(())
    }

    #[must_use]
    pub fn events(&self) -> &[RuntimeEventEnvelope] {
        &self.events
    }

    #[must_use]
    pub fn range(&self, start: u64, end_inclusive: u64) -> Vec<&RuntimeEventEnvelope> {
        self.events
            .iter()
            .filter(|event| (start..=end_inclusive).contains(&event.sequence))
            .collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ledger_rejects_corruption_and_sequence_gaps() {
        let mut ledger = AppendOnlyRuntimeLedger::default();
        ledger
            .append(RuntimeEventEnvelope::new(
                0,
                "event-0",
                RuntimeEventKind::UserMessage,
                1,
                serde_json::json!({"text": "hello"}),
            ))
            .unwrap();

        let gap = RuntimeEventEnvelope::new(
            2,
            "event-2",
            RuntimeEventKind::Termination,
            2,
            serde_json::json!({}),
        );
        assert!(ledger.append(gap).unwrap_err().contains("does not follow"));

        let mut corrupt = RuntimeEventEnvelope::new(
            1,
            "event-1",
            RuntimeEventKind::ToolCompleted,
            2,
            serde_json::json!({"ok": true}),
        );
        corrupt.payload = serde_json::json!({"ok": false});
        assert!(
            corrupt
                .validate()
                .unwrap_err()
                .contains("checksum mismatch")
        );
    }

    #[test]
    fn derived_range_does_not_remove_original_events() {
        let mut ledger = AppendOnlyRuntimeLedger::default();
        for sequence in 0..3 {
            ledger
                .append(RuntimeEventEnvelope::new(
                    sequence,
                    format!("event-{sequence}"),
                    RuntimeEventKind::AssistantMessage,
                    sequence,
                    serde_json::json!({"sequence": sequence}),
                ))
                .unwrap();
        }
        assert_eq!(ledger.range(1, 2).len(), 2);
        assert_eq!(ledger.events().len(), 3);
    }
}
