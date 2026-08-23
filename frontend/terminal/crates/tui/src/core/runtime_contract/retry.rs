use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum OperationClass {
    ModelRequest,
    ModelStream,
    ToolTransport,
    ToolExecution,
    ContextCompaction,
    Verification,
    ChildRun,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Idempotency {
    ReadOnly,
    IdempotentWrite,
    NonIdempotentWrite,
    Unknown,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct RetryAttempt {
    pub operation: OperationClass,
    pub idempotency: Idempotency,
    pub attempt: u32,
    pub max_attempts: u32,
    pub content_observed: bool,
    pub side_effect_observed: bool,
    pub canceled: bool,
    pub reason: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RetryDecision {
    Retry,
    Stop { reason: String },
}

#[must_use]
pub fn decide_retry(attempt: &RetryAttempt) -> RetryDecision {
    if attempt.canceled {
        return RetryDecision::Stop {
            reason: "operation was canceled".to_string(),
        };
    }
    if attempt.attempt >= attempt.max_attempts {
        return RetryDecision::Stop {
            reason: "retry budget exhausted".to_string(),
        };
    }
    if attempt.side_effect_observed
        && matches!(
            attempt.idempotency,
            Idempotency::NonIdempotentWrite | Idempotency::Unknown
        )
    {
        return RetryDecision::Stop {
            reason: "uncertain write side effect prevents an automatic retry".to_string(),
        };
    }
    if attempt.content_observed && attempt.operation == OperationClass::ModelStream {
        return RetryDecision::Stop {
            reason: "model stream already emitted content".to_string(),
        };
    }
    RetryDecision::Retry
}

#[cfg(test)]
mod tests {
    use super::*;

    fn attempt() -> RetryAttempt {
        RetryAttempt {
            operation: OperationClass::ModelStream,
            idempotency: Idempotency::ReadOnly,
            attempt: 0,
            max_attempts: 2,
            content_observed: false,
            side_effect_observed: false,
            canceled: false,
            reason: "network".to_string(),
        }
    }

    #[test]
    fn model_stream_retries_only_before_content() {
        assert_eq!(decide_retry(&attempt()), RetryDecision::Retry);
        let mut after_content = attempt();
        after_content.content_observed = true;
        assert!(matches!(
            decide_retry(&after_content),
            RetryDecision::Stop { .. }
        ));
    }

    #[test]
    fn uncertain_write_never_retries_after_side_effect() {
        let mut write = attempt();
        write.operation = OperationClass::ToolExecution;
        write.idempotency = Idempotency::Unknown;
        write.side_effect_observed = true;
        assert!(matches!(decide_retry(&write), RetryDecision::Stop { .. }));
    }
}
