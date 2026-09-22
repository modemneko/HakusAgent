# 公司级多智能体编排（Paperclip 式）— 方案定稿 v1

日期：2026-09-21
参考：https://johng.cn/ai/paperclip-multi-agent-company-orchestration

## 0. 已定决策

| 决策点 | 选择 |
| --- | --- |
| 落点 | **接入 HakusAgent**：控制平面作为 Rust crate 挂在现有 `app-server`，前端复用 Flow 模式 |
| 图引擎 | **自研精简 Pregel**（不引入 langgraph-rs），但用可插拔 executor trait 预留 |
| 首批智能体来源 | **仅自家 runtime**（CodeWhale / HakusAgent 线程） |
| MVP 第一刀 | **工单 + 心跳闭环** |
| 持久化 | SQLite（沿用 `crates/state`，rusqlite bundled），WAL 模式 |

> 变更原则：以上任一项改动都要回到这里更新，避免口头决策漂移。

## 1. 分层（关键认知）

Paperclip 是两层，LangGraph 只对得上其中一层：

- **控制平面（公司）**：org chart、ticket 状态机、goal 链、heartbeat 调度、budget、cost 归因、审批网关、tenant 隔离、公司模板 —— 与图无关，必须自研。
- **执行运行时（单 agent 内部）**：工具循环、上下文、暂停/恢复、人在环 —— 这才是图引擎的射程。

因此本方案是「自研公司控制平面 + 可插拔单 agent 执行器」，而不是「用 LangGraph 做 Paperclip」。

## 2. 现有地基（frontend/terminal，Codex fork「CodeWhale」）

| 已有 | 用途 |
| --- | --- |
| `crates/app-server` | axum HTTP + SSE：`/v1/threads`、`/v1/threads/{id}/turns`、`/v1/threads/{id}/events` |
| `crates/workflow` | Fleet IR：`named_fleet`(YAML)、router 分发、member role、permission ceiling、gates、review_repair、model_policy、elevation 风险升级 |
| `crates/workflow-js` | rquickjs VM 命令式编排（1000 agents/生命周期上限） |
| `crates/state` | SQLite 持久化 |
| `crates/mcp` / `tools` / `execpolicy` / `secrets` / `hooks` / `telemetry` | 工具与治理基建 |
| `crates/tui/automation_manager.rs` | 定时触发的前身（仅 TUI 层） |

**缺口**（本次要补的全部）：持久化 org + 汇报线、ticket 状态机 + 原子 checkout、goal 祖先链、服务端 heartbeat 调度、budget/cost 归因、组织级 approval、tenant 隔离。

## 3. 数据模型（SQLite，MVP 六张表 + 两张运行表）

```
company(id, name, mission, status, created_at)
agent(id, company_id, name, role, title, parent_agent_id, adapter='hakus',
      adapter_config JSON, status[active|paused], budget_monthly_cents, created_at)
goal(id, company_id, parent_id, kind[mission|goal|project|milestone], title, description)
issue(id, company_id, goal_id, title, body,
      state[backlog|todo|in_progress|blocked|in_review|done],
      assignee_agent_id, created_by_agent_id, billing_code, depth,
      checkout_run_id, checkout_at, created_at, updated_at)
issue_comment(id, issue_id, author_agent_id, body, created_at)
heartbeat(id, agent_id, cron, enabled, last_run_at, next_run_at)
heartbeat_run(id, heartbeat_id, agent_id, issue_id, status, started_at,
              finished_at, input_tokens, output_tokens, cost_cents, error)
cost_event(id, company_id, agent_id, issue_id, billing_code, model,
           input_tokens, output_tokens, cost_cents, created_at)
```

状态机语义（照搬 Paperclip，带执行含义）：

| 状态 | 语义 |
| --- | --- |
| `backlog` | 不可操作，安全休眠 |
| `todo` | 可执行但未认领，可有分配者 |
| `in_progress` | **必须**有认领者；控制平面保持执行心跳 |
| `blocked` | 等待外部条件，暂停执行 |
| `in_review` | 暂停，等待评审者或人工审批 |
| `done` | 终态 |

**原子认领**（防双重执行）：SQLite 单写者天然串行，用条件更新判定胜负：

```sql
UPDATE issue SET state='in_progress', checkout_run_id=?, checkout_at=?
WHERE id=? AND state IN ('todo','blocked');
-- changes() == 1 才视为认领成功
```

## 4. 心跳闭环时序（MVP 主干）

```
[scheduler tick]
  → 取到期 heartbeat（enabled 且 next_run_at <= now）
  → 预算校验：本月 SUM(cost_event) vs agent.budget_monthly_cents
        超限 → agent.status=paused，跳过并记 heartbeat_run(skipped)
  → 挑活：assignee=self 且 state=todo，或 unassigned 且 role 匹配（限制 1 个/心跳）
  → 原子 checkout（条件 UPDATE）
  → 组装上下文：mission → goal 祖先链 → issue 标题/正文 → 评论 → 汇报线/委托 depth
  → 调用自家 runtime：开 thread + turn（流式收事件，累加 token/成本）
  → 回写：issue_comment / 状态流转(done|blocked|in_review) / cost_event / heartbeat_run
  → SSE 推送 /v1/company/events
```

委托规则（P1）：同意且能做 → 完成；同意但做不了 → `blocked`；质疑任务价值 → **不得自行取消**，转交自己的经理。跨团队委托带 `depth`，默认上限 3。

## 5. 自研精简 Pregel

MVP 里图的定位：一次心跳内部若需多步（CEO 拆任务 → 委托 → 汇总），用图表达。

- `Node`：`async fn(State) -> StatePatch`
- `Edge`：固定边 / 条件路由（返回下一个节点 id）
- 执行：superstep 循环（每步并行跑就绪节点，用 tokio；步末统一 merge）
- `Channel`：last-write（默认）与 append（日志/消息）两种 reduce
- `Checkpoint`：每步末落 SQLite（MVP 先只写 heartbeat_run 日志，P3 再上真正的 resume）
- `Interrupt`：节点前可挂审批点，挂起后等待 approval 记录写入才继续

内置两个图即可开工：`ceo_plan_graph`（审使命 → 拆组织架构 → 建工单 → 触发审批 interrupt）、`worker_task_graph`（读上下文 → 执行 turn → 写结果/状态）。

Flow 画布（前端）产出的 JSON 图，后续通过「发布为公司流程模板」编译成这里的图 —— MVP 不做。

## 6. API（挂在 app-server）

```
POST   /v1/company                      创建公司
GET    /v1/company/{id}/agents           组织树
POST   /v1/company/{id}/agents           雇用 agent
POST   /v1/company/{id}/issues           建工单
GET    /v1/company/{id}/issues?state=    看板数据
POST   /v1/company/issues/{id}/checkout  原子认领
POST   /v1/company/issues/{id}/comment   评论/汇报
GET    /v1/company/events                SSE 实时事件
POST   /v1/company/approvals/{id}        审批通过/驳回
GET    /v1/company/{id}/costs            成本与预算视图
```

## 7. 里程碑

| 阶段 | 交付 |
| --- | --- |
| **M1 骨架** | `crates/company` + 迁移 + 上表 + REST/SSE + 一个 CLI 子命令能建公司/雇 agent/建工单 |
| **M2 心跳闭环** | scheduler + 预算校验 + 原子 checkout + 调自家 runtime + 回写 + heartbeat_run 日志 + 前端可见 |
| **M3 委托与看板** | 跨 agent 委托 + depth 上限 + blocked 转交经理 + Flow 模式内工单看板视图 |
| **M4 上图** | CEO/Worker 心跳内部改用自研 Pregel + interrupt 审批 + checkpoint 落库 |
| **M5（后）** | BYOA 适配器（Claude Code / HTTP webhook）、公司模板导入导出、多公司隔离 |

## 8. 风险与护栏（MVP 就要有）

- **成本失控**：agent 月度硬上限 + 单 run token 上限 + 全局并发上限（默认 4）
- **委托爆炸**：depth 上限 3、单公司 agent 数上限、单心跳最多派发 1 个工单
- **死状态**：`in_progress` 超时（如 30 分钟无事件）自动回收为 `todo`，避免沉默死状态
- **并发**：SQLite WAL + 单写者；重活全部走 tokio spawn_blocking 隔离
- **可观测**：每个 heartbeat_run 完整留痕（输入、输出、token、成本、错误），先有审计再谈自治

## 9. 待定（开工前需确认）

1. 心跳调度常驻形式：app-server 内 tokio scheduler / 独立 daemon 进程
2. 调自家 runtime：直连 `core` crate（快、紧耦合）vs 走本地 HTTP `/v1`（解耦、为 BYOA 预留）
3. role 词汇表：是否直接复用 `workflow::fleet_exact` 的 `ROLE_ALIASES`（ceo/cto/engineer…）
