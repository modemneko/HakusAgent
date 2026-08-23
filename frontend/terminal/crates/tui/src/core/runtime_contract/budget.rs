use std::time::Duration;

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct ExecutionBudget {
    pub max_steps: u32,
    pub max_tool_calls: u32,
    pub max_retries: u32,
    pub max_wall_time_ms: u64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct BudgetUsage {
    pub steps: u32,
    pub tool_calls: u32,
    pub retries: u32,
    pub elapsed_ms: u64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum BudgetExhaustion {
    Steps,
    ToolCalls,
    Retries,
    WallTime,
}

impl ExecutionBudget {
    pub fn validate(self) -> Result<(), String> {
        if self.max_steps == 0 {
            return Err("execution budget max_steps must be greater than zero".to_string());
        }
        if self.max_tool_calls == 0 {
            return Err("execution budget max_tool_calls must be greater than zero".to_string());
        }
        if self.max_wall_time_ms == 0 {
            return Err("execution budget max_wall_time_ms must be greater than zero".to_string());
        }
        Ok(())
    }

    #[must_use]
    pub const fn wall_time(self) -> Duration {
        Duration::from_millis(self.max_wall_time_ms)
    }

    #[must_use]
    pub fn exhausted_by(self, usage: BudgetUsage) -> Option<BudgetExhaustion> {
        if usage.steps >= self.max_steps {
            Some(BudgetExhaustion::Steps)
        } else if usage.tool_calls >= self.max_tool_calls {
            Some(BudgetExhaustion::ToolCalls)
        } else if usage.retries > self.max_retries {
            Some(BudgetExhaustion::Retries)
        } else if usage.elapsed_ms >= self.max_wall_time_ms {
            Some(BudgetExhaustion::WallTime)
        } else {
            None
        }
    }

    /// Child work may narrow a parent budget but can never widen it.
    #[must_use]
    pub fn child_budget(self, requested: Self) -> Self {
        Self {
            max_steps: self.max_steps.min(requested.max_steps),
            max_tool_calls: self.max_tool_calls.min(requested.max_tool_calls),
            max_retries: self.max_retries.min(requested.max_retries),
            max_wall_time_ms: self.max_wall_time_ms.min(requested.max_wall_time_ms),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn child_cannot_widen_parent_budget() {
        let parent = ExecutionBudget {
            max_steps: 32,
            max_tool_calls: 64,
            max_retries: 3,
            max_wall_time_ms: 60_000,
        };
        let child = parent.child_budget(ExecutionBudget {
            max_steps: u32::MAX,
            max_tool_calls: u32::MAX,
            max_retries: u32::MAX,
            max_wall_time_ms: u64::MAX,
        });
        assert_eq!(child, parent);
    }

    #[test]
    fn wall_time_has_a_distinct_exhaustion_reason() {
        let budget = ExecutionBudget {
            max_steps: 100,
            max_tool_calls: 100,
            max_retries: 3,
            max_wall_time_ms: 10,
        };
        assert_eq!(
            budget.exhausted_by(BudgetUsage {
                steps: 1,
                tool_calls: 1,
                retries: 0,
                elapsed_ms: 10,
            }),
            Some(BudgetExhaustion::WallTime)
        );
    }
}
