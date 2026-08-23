//! Model-facing LSP code-intelligence tool.
//!
//! Extends the existing [`crate::lsp::LspManager`] lifecycle — never spawns a
//! competing server pool. Operations: diagnostics, symbols, definition,
//! references.

use async_trait::async_trait;
use serde_json::{Value, json};

use super::spec::{
    ApprovalRequirement, ToolCapability, ToolContext, ToolError, ToolResult, ToolSpec,
    optional_str, required_str,
};

/// Model-callable LSP intelligence surface.
pub struct LspTool;

#[async_trait]
impl ToolSpec for LspTool {
    fn name(&self) -> &'static str {
        "lsp"
    }

    fn description(&self) -> &'static str {
        "Query language-server intelligence for a file: diagnostics, document \
         or workspace symbols, go-to-definition, and find-references. Reuses \
         the session LSP manager (no separate server lifecycle). Requires \
         `[lsp] enabled = true` and a configured server for the file language."
    }

    fn input_schema(&self) -> Value {
        json!({
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["diagnostics", "symbols", "definition", "references"],
                    "description": "Intelligence operation to run."
                },
                "path": {
                    "type": "string",
                    "description": "Workspace-relative or absolute path to the source file."
                },
                "line": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "1-based line for definition/references."
                },
                "character": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "1-based column for definition/references (default 1)."
                },
                "query": {
                    "type": "string",
                    "description": "Optional workspace symbol query when operation=symbols."
                }
            },
            "required": ["operation", "path"]
        })
    }

    fn capabilities(&self) -> Vec<ToolCapability> {
        vec![ToolCapability::ReadOnly]
    }

    fn approval_requirement(&self) -> ApprovalRequirement {
        ApprovalRequirement::Auto
    }

    async fn execute(&self, input: Value, context: &ToolContext) -> Result<ToolResult, ToolError> {
        let operation = required_str(&input, "operation")?;
        let path_raw = required_str(&input, "path")?;
        let line = input.get("line").and_then(|v| v.as_u64()).map(|n| n as u32);
        let character = input
            .get("character")
            .and_then(|v| v.as_u64())
            .map(|n| n as u32);
        let query = optional_str(&input, "query")?;

        let manager = context.lsp_manager.as_ref().ok_or_else(|| {
            ToolError::execution_failed(
                "LSP manager is not attached to this tool context (LSP unavailable for this session)",
            )
        })?;

        let path = resolve_workspace_path(&context.workspace, path_raw);
        let payload = manager
            .intelligence(operation, &path, line, character, query)
            .await
            .map_err(ToolError::execution_failed)?;

        Ok(ToolResult::success(
            serde_json::to_string_pretty(&payload).unwrap_or_else(|_| payload.to_string()),
        ))
    }
}

fn resolve_workspace_path(workspace: &std::path::Path, raw: &str) -> std::path::PathBuf {
    let candidate = std::path::PathBuf::from(raw);
    if candidate.is_absolute() {
        candidate
    } else {
        workspace.join(candidate)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::lsp::{Diagnostic, Language, LspConfig, LspManager, Severity};
    use crate::tools::spec::ToolContext;
    use async_trait::async_trait;
    use std::path::Path;
    use std::sync::Arc;
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::time::Duration;
    use tempfile::tempdir;

    struct CountingTransport {
        calls: AtomicUsize,
        request_calls: AtomicUsize,
    }

    #[async_trait]
    impl crate::lsp::LspTransport for CountingTransport {
        async fn diagnostics_for(
            &self,
            _path: &Path,
            _text: &str,
            _wait: Duration,
        ) -> anyhow::Result<Vec<Diagnostic>> {
            self.calls.fetch_add(1, Ordering::Relaxed);
            Ok(vec![Diagnostic {
                line: 1,
                column: 1,
                severity: Severity::Error,
                message: "boom".into(),
            }])
        }

        async fn request(
            &self,
            method: &str,
            _params: Value,
            _wait: Duration,
        ) -> anyhow::Result<Value> {
            self.request_calls.fetch_add(1, Ordering::Relaxed);
            Ok(json!({ "method": method, "locations": [] }))
        }

        async fn shutdown(&self) {}
    }

    #[tokio::test]
    async fn tool_reuses_single_manager_transport_for_definition() {
        let dir = tempdir().unwrap();
        let path = dir.path().join("lib.rs");
        tokio::fs::write(&path, b"fn main() {}").await.unwrap();

        let mgr = Arc::new(LspManager::new(
            LspConfig::default(),
            dir.path().to_path_buf(),
        ));
        let transport = Arc::new(CountingTransport {
            calls: AtomicUsize::new(0),
            request_calls: AtomicUsize::new(0),
        });
        mgr.install_test_transport(Language::Rust, transport.clone())
            .await;

        let mut ctx = ToolContext::new(dir.path());
        ctx = ctx.with_lsp_manager(mgr);

        let tool = LspTool;
        for _ in 0..2 {
            let result = tool
                .execute(
                    json!({
                        "operation": "definition",
                        "path": "lib.rs",
                        "line": 1,
                        "character": 4
                    }),
                    &ctx,
                )
                .await
                .expect("definition succeeds");
            assert!(result.success, "{}", result.content);
            assert!(result.content.contains("definition"));
        }
        assert_eq!(
            transport.request_calls.load(Ordering::Relaxed),
            2,
            "two definition calls"
        );
    }

    #[tokio::test]
    async fn diagnostics_operation_returns_items() {
        let dir = tempdir().unwrap();
        let path = dir.path().join("lib.rs");
        tokio::fs::write(&path, b"fn main() {}").await.unwrap();

        let mgr = Arc::new(LspManager::new(
            LspConfig::default(),
            dir.path().to_path_buf(),
        ));
        let transport = Arc::new(CountingTransport {
            calls: AtomicUsize::new(0),
            request_calls: AtomicUsize::new(0),
        });
        mgr.install_test_transport(Language::Rust, transport.clone())
            .await;

        let mut ctx = ToolContext::new(dir.path());
        ctx = ctx.with_lsp_manager(mgr);

        let result = LspTool
            .execute(
                json!({ "operation": "diagnostics", "path": "lib.rs" }),
                &ctx,
            )
            .await
            .expect("diagnostics");
        assert!(result.success);
        assert!(result.content.contains("boom"));
        assert_eq!(transport.calls.load(Ordering::Relaxed), 1);
    }

    #[tokio::test]
    async fn disabled_lsp_hard_blocks_tool() {
        let dir = tempdir().unwrap();
        let path = dir.path().join("lib.rs");
        tokio::fs::write(&path, b"fn main() {}").await.unwrap();
        let mgr = Arc::new(LspManager::new(
            LspConfig {
                enabled: false,
                ..LspConfig::default()
            },
            dir.path().to_path_buf(),
        ));
        let mut ctx = ToolContext::new(dir.path());
        ctx = ctx.with_lsp_manager(mgr);
        let err = LspTool
            .execute(
                json!({ "operation": "diagnostics", "path": "lib.rs" }),
                &ctx,
            )
            .await
            .expect_err("disabled must fail");
        assert!(
            err.to_string().contains("disabled"),
            "unexpected error: {err}"
        );
    }
}
