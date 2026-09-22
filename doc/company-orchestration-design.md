# 公司编排 · 详细设计 v1.1（可照做）

日期：2026-09-21　|　v1.0 → v1.1 变更：spike 后调整路线
上游方案：`doc/company-orchestration-plan.md`

## 决策表（v1.1 定稿）

| 决策点 | 结论 | v1.0 → v1.1 变更 |
|---|---|---|
| 落点 | **独立 Rust CLI / daemon**，不进桌面端 | 由「接入 HakusAgent + Flow 看板」改为「长期只用 CLI」 |
| 控制平面语言 | **Rust**（`crates/company`） | 不变 |
| 执行运行时 | **`hakus-llm` 原生直连 provider**（默认）；Python 退为可选 `--mode python` | v1.1 曾定 HTTP 调 Python；用户决策「直接做中长期」后改为原生（见 §14） |
| 图引擎 | 自研精简 Pregel（M4） | 不变 |
| 首批 agent | 仅自家 Python runtime | 「自家」= Python AgentCore |
| MVP | 工单 + 心跳闭环 | 不变 |
| 持久化 | SQLite `~/.hakus/company.sqlite` | 不变 |
| 调度 | daemon 进程内 tokio 循环 | 由「app-server 内」改为「自有 daemon」 |

**不再包含**：axum HTTP API（改为可选 feature）、SSE 事件总线、aapp-server 接线、Flow 看板 UI。
**新增**：`hakus company` CLI 子命令组。

---

## 1. 范围与验收

### M1 骨架
- `crates/company`（包名 `hakus-company`）
- 8 张表 + 迁移 + 仓储层（含原子认领）
- CLI：`company init / hire / issue / board / run`
- **验收**：`init` 建公司 → `hire` 雇一个 agent → `issue` 建工单 → `run` 真调一次 Python 后端 →
  `heartbeat_run` 有一条记录、工单变 `done`、`cost_event` 有 token 数

### M2 心跳闭环
- `company daemon` 常驻：tokio 间隔扫描 + 极简 cron
- 预算校验 → 挑活 → 原子 checkout → 组装组织上下文 → HTTP 跑 turn → 回写状态/成本/日志
- 死状态回收（`in_progress` 超时回 `todo`）

### M3（降级为 CLI）
- 委托跨 agent、`depth`、blocked 转交经理
- `company board` 输出文本看板（**不做前端**）

### 不在范围
aPregel 图执行（M4）、BYOA 第二适配器、多公司隔离、公司模板

---

## 2. crate 布局

```
crates/company/
├── Cargo.toml       name = "hakus-company"
└── src/
    ├── lib.rs       CompanyService（对外唯一入口）
    ├── model.rs     8 个行结构体 + 状态枚举
    ├── schema.rs    建表 DDL + user_version 迁移
    ├── store.rs     CompanyStore：全部 SQL（含 checkout_issue）
    ├── context.rs   goal 祖先链 + 组织上下文拼装
    ├── adapter.rs   AgentRuntime trait + HttpPythonRuntime（reqwest + SSE）
    ├── scheduler.rs tokio 心跳循环 + 单次执行体
    ├── pregel.rs    精简 Pregel（M4，M1 只定义类型）
    └── bin/         无 —— CLI 子命令挂在 crates/cli
```

**依赖**：`rusqlite`(bundled) · `reqwest`(json + stream + rustls) · `tokio` · `serde` · `serde_json` ·
`chrono` · `uuid` · `thiserror` · `anyhow` · `tracing` · `async-trait` · `hakus-paths`
**刻意不依赖**：`hakus-core`（stub）、`hakus-app-server`、`axum`

---

## 3. 数据库

**文件**：`~/.hakus/company.sqlite`（`HAKUS_DATA_DIR` 可覆盖根目录）
**打开**：`journal_mode=WAL` · `busy_timeout=5000` · `foreign_keys=ON`
**迁移**：`PRAGMA user_version`，`MIGRATIONS: &[&str]` 顺序执行，逐个事务

### DDL（迁移 1）

```sql
CREATE TABLE company (
  id         TEXT PRIMARY KEY,
  name       TEXT NOT NULL,
  mission    TEXT NOT NULL DEFAULT '',
  status     TEXT NOT NULL DEFAULT 'active',   -- active | archived
  created_at INTEGER NOT NULL
);

CREATE TABLE agent (
  id                   TEXT PRIMARY KEY,
  company_id           TEXT NOT NULL REFERENCES company(id),
  name                 TEXT NOT NULL,
  role                 TEXT NOT NULL,            -- ceo | cto | engineer | ...
  title                TEXT NOT NULL DEFAULT '',
  parent_agent_id      TEXT REFERENCES agent(id), -- 汇报线
  adapter              TEXT NOT NULL DEFAULT 'python-http',
  adapter_config       TEXT NOT NULL DEFAULT '{}', -- JSON: model/provider/run_mode/cwd
  runtime_session_id   TEXT,                      -- 复用的 Python 会话（跨心跳续上下文）
  status               TEXT NOT NULL DEFAULT 'active', -- active | paused
  budget_monthly_cents INTEGER NOT NULL DEFAULT 0,     -- 0 = 不限
  created_at           INTEGER NOT NULL
);
CREATE INDEX idx_agent_company ON agent(company_id);

CREATE TABLE goal (
  id          TEXT PRIMARY KEY,
  company_id  TEXT NOT NULL REFERENCES company(id),
  parent_id   TEXT REFERENCES goal(id),
  kind        TEXT NOT NULL,   -- mission | goal | project | milestone
  title       TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT ''
);
CREATE INDEX idx_goal_company ON goal(company_id);

CREATE TABLE issue (
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
CREATE INDEX idx_issue_board ON issue(company_id, state);
CREATE INDEX idx_issue_assignee ON issue(assignee_agent_id, state);

CREATE TABLE issue_comment (
  id              TEXT PRIMARY KEY,
  issue_id        TEXT NOT NULL REFERENCES issue(id),
  author_agent_id TEXT REFERENCES agent(id),
  body            TEXT NOT NULL,
  created_at      INTEGER NOT NULL
);
CREATE INDEX idx_comment_issue ON issue_comment(issue_id);

CREATE TABLE heartbeat (
  id          TEXT PRIMARY KEY,
  agent_id    TEXT NOT NULL REFERENCES agent(id),
  cron        TEXT NOT NULL,
  enabled     INTEGER NOT NULL DEFAULT 1,
  last_run_at INTEGER,
  next_run_at INTEGER
);
CREATE INDEX idx_hb_due ON heartbeat(enabled, next_run_at);

CREATE TABLE heartbeat_run (
  id            TEXT PRIMARY KEY,
  heartbeat_id  TEXT REFERENCES heartbeat(id),
  agent_id      TEXT NOT NULL,
  issue_id      TEXT,
  status        TEXT NOT NULL,  -- ok | skipped_budget | no_work | error | checkout_lost
  input_tokens  INTEGER NOT NULL DEFAULT 0,
  output_tokens INTEGER NOT NULL DEFAULT 0,
  cost_cents    INTEGER NOT NULL DEFAULT 0,
  output        TEXT NOT NULL DEFAULT '',
  error         TEXT,
  started_at    INTEGER NOT NULL,
  finished_at   INTEGER
);
CREATE INDEX idx_run_agent ON heartbeat_run(agent_id, started_at);

CREATE TABLE cost_event (
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
CREATE INDEX idx_cost_company ON cost_event(company_id, created_at);
```

### 状态机

| 状态 | 语义 |
|---|---|
| `backlog` | 不可操作，安全休眠 |
| `todo` | 可执行但未认领 |
| `in_progress` | 必须有认领者；daemon 保持执行 |
| `blocked` | 等待外部条件，暂停执行 |
| `in_review` | 暂停，等待评审/审批 |
| `done` | 终态 |

### 原子认领

```rust
pub fn checkout_issue(&self, issue_id: &str, run_id: &str, now: i64) -> Result<bool> {
    let n = self.conn.execute(
        "UPDATE issue SET state='in_progress', checkout_run_id=?2, checkout_at=?3, updated_at=?3
         WHERE id=?1 AND state IN ('todo','blocked')",
        params![issue_id, run_id, now],
    )?;
    Ok(n == 1)
}
```

---

## 4. 执行适配器（修正版）

```rust
#[async_trait]
pub trait AgentRuntime: Send + Sync {
    async fn ensure_session(&self, agent: &AgentRow) -> Result<String>;
    async fn run_turn(&self, req: RunTurnReq) -> Result<RunTurnOut>;
}

pub struct RunTurnReq { pub session_id: String, pub prompt: String,
                       pub provider: Option<String>, pub run_mode: Option<String> }
pub struct RunTurnOut { pub text: String, pub model: String,
                       pub input_tokens: u64, pub output_tokens: u64 }
```

**`HttpPythonRuntime`** —— `POST {base}/api/chat/stream`，body `{message, session_id, stream:true, provider, run_mode}`，
响应 SSE（`data: {json}\n\n`），按 `event_type` 路由：

| 事件 | 处理 |
|---|---|
| `text_delta` | 累积文本 |
| `token_usage` | 累加 `input_tokens` / `output_tokens`（一 turn 可能多次） |
| `turn_completed` | 成功，取 `content` |
| `turn_failed` | 失败，取 `code`/`error` |
| `approval_required` | 治理钩子来源（MVP：记录到评论并置 `in_review`） |

`max_concurrent` 不再受 core 写锁限制，默认 4（真并发可用）。

---

## 5. 心跳执行体

```
扫到期 heartbeat → 预算校验（超限 pause + skipped_budget）
  → pick_work（每心跳 1 个工单）
  → 原子 checkout（失败 = checkout_lost）
  → 组装上下文（mission → goal 祖先链 → 工单 → 评论 → 汇报线/depth）
  → ensure_session + run_turn（HTTP SSE）
  → 成功：评论 + done + cost_event + run(ok)
     失败：评论（错误）+ blocked + run(error)
  → 下次 next_run_at（极简 cron：*/n、*、固定数字）
```

---

## 6. CLI 接线（`crates/cli`）

```
hakus company init   --name --mission
hakus company hire   --company --name --role [--parent] [--model] [--budget-cents]
hakus company issue  --company --title [--body] [--goal] [--assignee]
hakus company board  --company            # 文本看板
hakus company run    --agent              # 手动触发一次心跳
hakus company daemon --company            # 常驻调度
```

Python 后端地址：优先 `--base-url`，其次 env `HAKUS_PY_BASE`，默认 `http://127.0.0.1:8000`。

---

## 7. M1 任务清单

1. [x] spike：已验证（见 §11）
2. [ ] `crates/company` 骨架 + 加入 workspace members
3. [ ] `model.rs`：8 个行结构体 + 状态枚举 + `From<&Row>`
4. [ ] `schema.rs`：迁移 + 幂等单测
5. [ ] `store.rs`：CRUD + `checkout_issue` + `pick_work` + run/cost 写入；单测「并发认领只有一个成功」
6. [ ] `adapter.rs`：`AgentRuntime` + `HttpPythonRuntime`（reqwest SSE）+ `MockRuntime`
7. [ ] `context.rs`：goal 祖先链 + prompt 拼装
8. [ ] `CompanyService::new(store, adapter)`
9. [ ] CLI 五个子命令
10. [ ] 端到端跑一次：真连 Python 后端完成一个工单

## 8. M2 任务清单

1. [ ] `scheduler.rs`：间隔扫描 + 极简 cron + 并发上限信号量
2. [ ] 预算校验 + pause + 跳过记录
3. [ ] 死状态回收：`in_progress` 超 30 分钟 → `todo` + 评论
4. [ ] 护栏：depth ≤ 3、单心跳 1 工单、单 run token 上限、并发 ≤ 4
5. [ ] `daemon` 子命令 + 优雅退出（SIGINT）
6. [ ] 集成测试：mock runtime，10 工单 / 3 agent / 3 轮，断言无重复执行、状态收敛

---

## 9. 风险

| ID | 风险 | 处理 |
|---|---|---|
| R2 | 成本失控 | agent 月度硬上限 + 单 run token 上限 + 并发上限；超限 pause |
| R3 | 委托爆炸 | depth ≤ 3、单心跳 1 工单 |
| R4 | 沉默死状态 | 30 分钟超时回收 |
| R5 | 阻塞异步运行时 | 全部 DB 操作走 `spawn_blocking` |
| R6 | 迁移破坏既有库 | 独立 `company.sqlite`，不动会话库 |
| R7 | Python 后端未启动 | adapter 返回明确错误；daemon 记录 `error` 而非崩溃；启动自检 503 提示 |
| R8 | SSE 解析差异 | adapter 只认 `event_type`，未知事件忽略；`{json}` 解析失败计入 error |

---

## 10. 复用的 Flask 契约（来自 spike）

- `POST /api/chat/stream` body：`{message, session_id, stream, provider, run_mode, project_id}`
- SSE 每帧 `data: {json}\n\n`；`token_usage` 字段 `input_tokens` / `output_tokens`
- `session_id` 复用即可跨心跳保持上下文（等价 Paperclip 的持久会话）
- `approval_required` 事件 → 治理钩子的现成来源

---

## 15. M3 协作内核（2026-09-21 定稿，进行中）

顺序：**协作内核 → 打通执行 → 外壳合并**。委托协议定型前不做 UI。

### 15.1 决策输出（委托能自动化的前提）

经理 / CEO 的心跳要求模型输出 JSON；解析不出来就当普通工作报告处理（向后兼容）：

```json
{
  "commentary": "本轮判断的简短说明",
  "actions": [
    { "kind": "create_issue", "title": "…", "body": "…",
      "assignee_role": "engineer", "assignee_agent_id": null, "goal_id": null },
    { "kind": "complete", "issue_id": "iss_x", "summary": "…" },
    { "kind": "block",     "issue_id": "iss_y", "reason": "缺 API key" },
    { "kind": "escalate",  "issue_id": "iss_z", "reason": "质疑任务价值" }
  ]
}
```

规则：
- 允许 ```json 代码块包裹；取文本中第一个合法 JSON 对象
- 解析失败 → 退化为纯文本（写评论 + done），不报错
- schema 校验失败一次 → 带错误信息重试一次，仍失败同上退化

### 15.2 委托协议

| 规则 | 行为 |
|---|---|
| 委托建工单 | `depth = 父工单.depth + 1`、`parent_issue_id = 父工单`、`billing_code` 继承父（成本归因到发起方） |
| 深度上限 | `depth > 3` 拒绝建单，改为 `escalate` 给经理 |
| 分配 | 优先 `assignee_agent_id`，其次按 `assignee_role` 在公司内查找，都找不到则留空（任何人可认领） |
| 做不了 | `block` + 写明缺什么 → 转经理 |
| 质疑价值 | **不得自行取消** → `escalate` 给经理 |

### 15.3 审批网关

- 新增 `approval` 表（迁移 2）；高影响动作（雇人 / 改预算 / 删除工单）落 `pending`，人工放行
- 工单状态 `in_review` = 暂停等待人审；CLI `approve / reject`
- 原生 runtime 没有 `approval_required` 事件，靠 `in_review` 状态补上这一环

### 15.4 执行：按 agent 混用 runtime

`agent.adapter` 决定用哪个 runtime：

| adapter | runtime | 能力 |
|---|---|---|
| `python-http` | `HttpPythonRuntime` | 有 24 个工具，能改文件跑命令 |
| `llm`（默认） | `NativeLlmRuntime` | 只能输出文本结论 |
| `mock` | `MockRuntime` | 测试 |

`HeartbeatRunner` 持有一个 `RuntimeRegistry`，按 agent 分派。

### 15.5 M3 进度（2026-09-22）

1. [x] 迁移 2：`issue.parent_issue_id` + `approval` 表（`SCHEMA_VERSION = 2`）
2. [x] `RuntimeRegistry`：按 `agent.adapter` 分派（`llm` / `python-http` / `mock`），CLI `hire --adapter`
3. [x] `decision.rs`：解析（容忍 ```json 围栏与前后散文、括号配对扫描）+ 应用（depth 上限、角色查找、escalate 转经理、成本归因继承）
4. [~] 审批：表与 CLI（`approvals` / `approve` / `reject`）就绪；**尚无自动发起者**，且 `approve` 尚未联动 subject 状态
5. [x] CLI：`tree`（组织树 + 待办计数）、`board` 按状态分组并显示姓名/角色
6. [x] 集成测试 `manager_delegates_and_worker_completes`：CEO 输出决策 → 建子工单（depth 1、billing=CEO、assignee=角色匹配）→ 工程师心跳完成 → 2 条 run 全 ok

**测试**：15/15 通过（company 15）。CLI 冒烟：`hire --adapter python-http` / `issue --role` / `tree` / `board` / `approvals` 均正常。

**下一步候选**
- 让 `approve/reject` 真正推动 subject（放行 `in_review` 工单、执行被挂起的雇人/预算变更）
- 高影响动作自动落审批：`hire_agent` / `change_budget` / `delete_issue`
- `daemon` 连真实 provider 跑一轮完整委托链（需要 key）
- 经理在子工单全部完成后自动收口（当前需经理自己发 `complete`）

---

## 14. 去 Python 化（2026-09-21 后续决策）

用户决策：不做「先借 Python 过渡」，直接做中长期方案。

- 抽 tui 客户端不可行：`crates/tui/src/client/chat.rs` 250 KB、`config.rs` 509 KB，且 import 全是 tui 内部模块（`crate::config`、`crate::llm_client`、`crate::models`、`crate::logging`）
- 可行资产在 **`hakus-config`**：`ProviderKind`、`WireFormat`、`TokenUsage`、`pricing.rs`（定价表）。provider 目录与价格不用重写，等接入时复用
- 于是新建 **`crates/llm`（`hakus-llm`）**：约 400 行，两种线格式即可覆盖绝大多数供应商
  - `WireFormat::OpenAi` — `/chat/completions`：DeepSeek、Moonshot/Kimi、ZAI、Minimax、Qwen、vLLM、Ollama、OpenAI
  - `WireFormat::Anthropic` — `/v1/messages`：Claude、Anthropic 兼容网关
  - `LlmRoute::from_env()` 读 `HAKUS_LLM_BASE_URL/API_KEY/MODEL/WIRE`
  - `pricing.rs`：`Price::for_model()` + `cost_cents()`（未知模型默认 0，可用 `HAKUS_PRICE_IN_PER_MTOK` 覆盖）
- `adapter.rs` 新增 `NativeLlmRuntime`（实现同一个 `AgentRuntime`），CLI 默认 `--mode native`，另有 `python` / `mock`
- **代价（必须记住）**：原生员工只能输出文本结论——无工具、无审批、无 checkpoint。需要「能干活」的员工时，仍要回到 Python 或等 core 补齐 turn 循环（那时只需再加一个 adapter）

### 已知坑
- workspace 的 reqwest 用 `rustls-no-provider`：**必须在建 Client 前** `rustls::crypto::ring::default_provider().install_default()`，否则运行时 panic。`hakus_llm::ensure_tls_provider()` 已封装，`HttpPythonRuntime::new()` 也调用了它

---

## 11. Spike 结论存档（2026-09-21）

| # | 待验证 | 结果 | 证据 |
|---|---|---|---|
| 1 | `ThreadRequest::Start/Message` 能跑 turn | ❌ | `core/src/lib.rs:1313` 只 `touch_message` |
| 1b | `handle_prompt` 可替代 | ❌ stub | `core/src/lib.rs:1359-1434` 返回元数据 JSON，全 crate 无 reqwest |
| 2 | token 用量来源 | ✅ Python SSE `token_usage` | `hakus/orchestrator.py:123` |
| 3 | core 写锁串行化 | ➖ 不再阻塞 | 改走 HTTP |
| 4 | `HAKUS_APP_DIR` | ✅ `~/.hakus` | `paths/src/lib.rs:13` |
| 5 | 桌面端是否拉起 Rust 服务 | ❌ 无 sidecar | `tauri.conf.json` 无 externalBin |

→ 促成「Rust 控制平面 + HTTP 调 Python + 长期 CLI」这条路线。
