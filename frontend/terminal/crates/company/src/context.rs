//! Goal-aware prompt assembly.
//!
//! Paperclip's biggest quality lever is that an agent always knows *why* it is
//! doing something: every ticket prompt carries the full mission → goal →
//! project → milestone chain, not just the ticket title.

use anyhow::Result;

use crate::model::{AgentRow, IssueRow};
use crate::store::CompanyStore;

pub struct ContextBuilder<'a> {
    store: &'a CompanyStore,
}

impl<'a> ContextBuilder<'a> {
    pub fn new(store: &'a CompanyStore) -> Self {
        Self { store }
    }

    /// Build the prompt handed to the runtime for one ticket.
    pub fn worker_prompt(&self, agent: &AgentRow, issue: &IssueRow) -> Result<String> {
        let mut out = String::new();

        let company = self.store.get_company(&agent.company_id)?;
        if let Some(c) = company {
            if !c.mission.trim().is_empty() {
                out.push_str(&format!("## 公司使命\n{}\n\n", c.mission.trim()));
            }
        }

        let chain = self.store.goal_chain(issue.goal_id.as_deref())?;
        if !chain.is_empty() {
            out.push_str("## 目标链（为什么做这件事）\n");
            for (idx, g) in chain.iter().enumerate() {
                out.push_str(&format!("{}. [{}] {}\n", idx + 1, g.kind, g.title));
                if !g.description.trim().is_empty() {
                    out.push_str(&format!("   {}\n", g.description.trim()));
                }
            }
            out.push('\n');
        }

        out.push_str("## 你的角色\n");
        out.push_str(&format!("- 姓名：{}\n", agent.name));
        out.push_str(&format!("- 角色：{}\n", agent.role));
        if !agent.title.is_empty() {
            out.push_str(&format!("- 头衔：{}\n", agent.title));
        }
        if let Some(parent) = &agent.parent_agent_id {
            out.push_str(&format!("- 汇报对象：{}\n", parent));
        }
        out.push('\n');

        out.push_str("## 当前工单\n");
        out.push_str(&format!("- 工单 ID：{}\n", issue.id));
        out.push_str(&format!("- 标题：{}\n", issue.title));
        if !issue.body.trim().is_empty() {
            out.push_str(&format!("- 描述：\n{}\n", issue.body.trim()));
        }
        if issue.depth > 0 {
            out.push_str(&format!("- 委托深度：{}\n", issue.depth));
        }
        if !issue.billing_code.is_empty() {
            out.push_str(&format!("- 成本归因：{}\n", issue.billing_code));
        }
        out.push('\n');

        let comments = self.store.list_comments(&issue.id)?;
        if !comments.is_empty() {
            out.push_str("## 工单讨论\n");
            for (author, body) in comments {
                let who = author.unwrap_or_else(|| "human".to_string());
                out.push_str(&format!("- {who}: {}\n", body.trim()));
            }
            out.push('\n');
        }

        out.push_str(
            "## 要求\n\
             1. 直接完成这项任务，输出你的工作结果。\n\
             2. 如果你无法完成，明确说明缺什么，并列出你已经完成的部分。\n\
             3. 如果你认为这个任务本身不该做，不要自行取消——说明质疑理由，交给你的经理决定。\n",
        );

        Ok(out)
    }

    /// Resolve the reporting line upward so a manager can be found.
    pub fn manager_of(&self, agent: &AgentRow) -> Option<AgentRow> {
        let parent = agent.parent_agent_id.as_deref()?;
        self.store.get_agent(parent).ok().flatten()
    }
}

/// Recursively list ancestors (nearest first). Used by delegation receipts.
pub fn ancestors(store: &CompanyStore, agent: &AgentRow) -> Vec<AgentRow> {
    let mut out = Vec::new();
    let mut cursor = agent.parent_agent_id.clone();
    while let Some(id) = cursor {
        match store.get_agent(&id).ok().flatten() {
            Some(parent) => {
                cursor = parent.parent_agent_id.clone();
                out.push(parent);
            }
            None => break,
        }
    }
    out
}
