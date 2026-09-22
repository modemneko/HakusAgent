//! Schema and migrations for `company.sqlite`.
//!
//! Versioning is a plain `PRAGMA user_version` integer: migration N brings the
//! database from N-1 to N, and applying them is idempotent because each step is
//! guarded by a `user_version` check inside its own transaction.

use rusqlite::Connection;

/// Table definitions created by migration 1.
const MIGRATION_1: &str = r#"
CREATE TABLE IF NOT EXISTS company (
  id         TEXT PRIMARY KEY,
  name       TEXT NOT NULL,
  mission    TEXT NOT NULL DEFAULT '',
  status     TEXT NOT NULL DEFAULT 'active',
  created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS agent (
  id                   TEXT PRIMARY KEY,
  company_id           TEXT NOT NULL REFERENCES company(id),
  name                 TEXT NOT NULL,
  role                 TEXT NOT NULL,
  title                TEXT NOT NULL DEFAULT '',
  parent_agent_id      TEXT REFERENCES agent(id),
  adapter              TEXT NOT NULL DEFAULT 'python-http',
  adapter_config       TEXT NOT NULL DEFAULT '{}',
  runtime_session_id   TEXT,
  status               TEXT NOT NULL DEFAULT 'active',
  budget_monthly_cents INTEGER NOT NULL DEFAULT 0,
  created_at           INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_agent_company ON agent(company_id);

CREATE TABLE IF NOT EXISTS goal (
  id          TEXT PRIMARY KEY,
  company_id  TEXT NOT NULL REFERENCES company(id),
  parent_id   TEXT REFERENCES goal(id),
  kind        TEXT NOT NULL,
  title       TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_goal_company ON goal(company_id);

CREATE TABLE IF NOT EXISTS issue (
  id                  TEXT PRIMARY KEY,
  company_id          TEXT NOT NULL REFERENCES company(id),
  goal_id             TEXT REFERENCES goal(id),
  title               TEXT NOT NULL,
  body                TEXT NOT NULL DEFAULT '',
  state               TEXT NOT NULL DEFAULT 'backlog',
  assignee_agent_id   TEXT REFERENCES agent(id),
  created_by_agent_id TEXT REFERENCES agent(id),
  billing_code        TEXT NOT NULL DEFAULT '',
  depth               INTEGER NOT NULL DEFAULT 0,
  checkout_run_id     TEXT,
  checkout_at         INTEGER,
  created_at          INTEGER NOT NULL,
  updated_at          INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_issue_board ON issue(company_id, state);
CREATE INDEX IF NOT EXISTS idx_issue_assignee ON issue(assignee_agent_id, state);

CREATE TABLE IF NOT EXISTS issue_comment (
  id              TEXT PRIMARY KEY,
  issue_id        TEXT NOT NULL REFERENCES issue(id),
  author_agent_id TEXT REFERENCES agent(id),
  body            TEXT NOT NULL,
  created_at      INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_comment_issue ON issue_comment(issue_id);

CREATE TABLE IF NOT EXISTS heartbeat (
  id          TEXT PRIMARY KEY,
  agent_id    TEXT NOT NULL REFERENCES agent(id),
  cron        TEXT NOT NULL,
  enabled     INTEGER NOT NULL DEFAULT 1,
  last_run_at INTEGER,
  next_run_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_hb_due ON heartbeat(enabled, next_run_at);

CREATE TABLE IF NOT EXISTS heartbeat_run (
  id            TEXT PRIMARY KEY,
  heartbeat_id  TEXT REFERENCES heartbeat(id),
  agent_id      TEXT NOT NULL,
  issue_id      TEXT,
  status        TEXT NOT NULL,
  input_tokens  INTEGER NOT NULL DEFAULT 0,
  output_tokens INTEGER NOT NULL DEFAULT 0,
  cost_cents    INTEGER NOT NULL DEFAULT 0,
  output        TEXT NOT NULL DEFAULT '',
  error         TEXT,
  started_at    INTEGER NOT NULL,
  finished_at   INTEGER
);
CREATE INDEX IF NOT EXISTS idx_run_agent ON heartbeat_run(agent_id, started_at);

CREATE TABLE IF NOT EXISTS cost_event (
  id            TEXT PRIMARY KEY,
  company_id    TEXT NOT NULL,
  agent_id      TEXT,
  issue_id      TEXT,
  run_id        TEXT,
  billing_code  TEXT NOT NULL DEFAULT '',
  model         TEXT NOT NULL DEFAULT '',
  input_tokens  INTEGER NOT NULL DEFAULT 0,
  output_tokens INTEGER NOT NULL DEFAULT 0,
  cost_cents    INTEGER NOT NULL DEFAULT 0,
  created_at    INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cost_company ON cost_event(company_id, created_at);
"#;

/// Migration 2 — delegation and governance.
///
/// `parent_issue_id` turns the ticket table into a delegation tree; `approval`
/// is the gate that stops high-impact actions from happening unsupervised.
const MIGRATION_2: &str = r#"
ALTER TABLE issue ADD COLUMN parent_issue_id TEXT REFERENCES issue(id);

CREATE TABLE IF NOT EXISTS approval (
  id            TEXT PRIMARY KEY,
  company_id    TEXT NOT NULL,
  kind          TEXT NOT NULL,
  subject_id    TEXT NOT NULL,
  payload       TEXT NOT NULL DEFAULT '{}',
  status        TEXT NOT NULL DEFAULT 'pending',
  requested_by  TEXT,
  decided_by    TEXT,
  reason        TEXT,
  created_at    INTEGER NOT NULL,
  decided_at    INTEGER
);
CREATE INDEX IF NOT EXISTS idx_approval_pending ON approval(company_id, status);
"#;

/// Current schema version. Bump together with pushing a new migration here.
pub const SCHEMA_VERSION: u32 = 2;

const MIGRATIONS: &[&str] = &[MIGRATION_1, MIGRATION_2];

/// Apply every pending migration. Safe to call repeatedly.
pub fn migrate(conn: &mut Connection) -> rusqlite::Result<u32> {
    let current: u32 = conn.pragma_query_value(None, "user_version", |r| r.get(0))?;
    for (idx, sql) in MIGRATIONS.iter().enumerate() {
        let version = (idx as u32) + 1;
        if version <= current {
            continue;
        }
        let tx = conn.transaction()?;
        tx.execute_batch(sql)?;
        tx.pragma_update(None, "user_version", version)?;
        tx.commit()?;
    }
    let final_version: u32 = conn.pragma_query_value(None, "user_version", |r| r.get(0))?;
    Ok(final_version)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn migrate_is_idempotent() {
        let mut conn = Connection::open_in_memory().unwrap();
        let first = migrate(&mut conn).unwrap();
        assert_eq!(first, SCHEMA_VERSION);
        let second = migrate(&mut conn).unwrap();
        assert_eq!(second, SCHEMA_VERSION);
    }

    #[test]
    fn all_tables_exist() {
        let mut conn = Connection::open_in_memory().unwrap();
        migrate(&mut conn).unwrap();
        let expected = [
            "company",
            "agent",
            "goal",
            "issue",
            "issue_comment",
            "heartbeat",
            "heartbeat_run",
            "cost_event",
        ];
        for table in expected {
            let n: i64 = conn
                .query_row(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?1",
                    rusqlite::params![table],
                    |r| r.get(0),
                )
                .unwrap_or(0);
            assert_eq!(n, 1, "missing table {table}");
        }
    }
}
