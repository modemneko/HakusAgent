use serde::{Deserialize, Serialize};
use serde_json::Value;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum WorkDomain {
    /// Durable delegated/background unit.
    Task,
    /// Active checklist inside the current turn or lane.
    Todo,
    /// Strategy owned through Plan mode.
    Plan,
    /// Ordered durable execution.
    Workflow,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum WorkLifecycle {
    Pending,
    Active,
    Waiting,
    Completed,
    Failed,
    Canceled,
}

/// Common envelope only. The payload remains owned by its domain so Tasks,
/// To-do, Plan, and Workflow cannot collapse into a generic tracker.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct WorkEventEnvelope {
    pub schema_version: u32,
    pub event_id: String,
    pub domain: WorkDomain,
    pub object_id: String,
    pub lifecycle: WorkLifecycle,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub parent_id: Option<String>,
    pub payload: Value,
}

impl WorkEventEnvelope {
    pub fn validate(&self) -> Result<(), String> {
        if self.schema_version == 0 {
            return Err("work event schema version cannot be zero".to_string());
        }
        if self.event_id.trim().is_empty() || self.object_id.trim().is_empty() {
            return Err("work event and object IDs cannot be empty".to_string());
        }
        if !self.payload.is_object() {
            return Err("work event payload must remain a typed object".to_string());
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn domains_share_an_envelope_without_losing_meaning() {
        let task = WorkEventEnvelope {
            schema_version: 1,
            event_id: "event-task".to_string(),
            domain: WorkDomain::Task,
            object_id: "task-1".to_string(),
            lifecycle: WorkLifecycle::Active,
            parent_id: None,
            payload: serde_json::json!({"worker_id": "worker-1"}),
        };
        let todo = WorkEventEnvelope {
            domain: WorkDomain::Todo,
            event_id: "event-todo".to_string(),
            object_id: "todo-1".to_string(),
            payload: serde_json::json!({"checked": false}),
            ..task.clone()
        };
        assert_ne!(task.domain, todo.domain);
        assert!(task.payload.get("worker_id").is_some());
        assert!(todo.payload.get("checked").is_some());
        assert!(task.validate().is_ok());
        assert!(todo.validate().is_ok());
    }
}
