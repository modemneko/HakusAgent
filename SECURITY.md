# HakusAI 安全配置指南

本文档描述 HakusAI 后端的安全配置选项和最佳实践。

## 📋 目录

- [安全概览](#安全概览)
- [已修复的安全漏洞](#已修复的安全漏洞)
- [配置选项](#配置选项)
- [环境变量](#环境变量)
- [生产环境部署清单](#生产环境部署清单)
- [审计日志](#审计日志)

---

## 安全概览

### 默认安全姿态 (Default Security Posture)

HakusAI 2.0 采用 **安全默认** 设计：

| 配置项 | 默认值 | 安全级别 |
|--------|--------|----------|
| 绑定地址 | `127.0.0.1` | ✅ 仅本地访问 |
| CORS 来源 | `http://localhost:1421` | ✅ 仅允许本地前端 |
| API 鉴权 | 禁用（空字符串） | ⚠️ 开发模式 |
| 命令执行 | 禁用（空白名单） | ✅ 禁止所有 shell |
| 速率限制 | 60 req/min | ✅ 已启用 |

### 安全架构

```
┌─────────────────────────────────────────────────────────────┐
│                      客户端请求                              │
└──────────────────────┬──────────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────────┐
│              CORS 中间件 (安全加固)                           │
│  - 限制允许的来源                                             │
│  - ["*"] 时强制禁用 credentials                              │
│  - 限制允许的方法和头                                         │
└──────────────────────┬──────────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────────┐
│              鉴权中间件 (AuthMiddleware)                      │
│  - API Key 验证 (X-API-Key 头)                               │
│  - 速率限制 (按 IP)                                           │
│  - 审计日志记录                                               │
│  - 跳过公开端点 (/health, /docs, ...)                         │
└──────────────────────┬──────────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────────┐
│              业务路由处理                                     │
│  - WebSocket 连接鉴权                                        │
│  - Agent 权限控制                                            │
│  - 命令白名单验证                                            │
└─────────────────────────────────────────────────────────────┘
```

---

## 已修复的安全漏洞

### 🔴 严重 (Critical)

#### 1. 服务端绑定 0.0.0.0 (已修复)

**问题**: 默认绑定 `0.0.0.0:8080`，暴露在所有网络接口

**修复**: 
- 默认改为 `127.0.0.1:8080`（仅本地访问）
- 可通过 `security.host` 配置覆盖

```yaml
# config.yaml
security:
  host: "127.0.0.1"  # 或 "0.0.0.0" 如需远程访问（必须配合 API Key）
  port: 8080
```

#### 2. 危险 CORS 配置 (已修复)

**问题**: `allow_origins=["*"]` + `allow_credentials=True`（违反 CORS 规范）

**修复**:
- 默认 CORS 仅允许 `http://localhost:1421` 和 `http://127.0.0.1:1421`
- 当 origins 包含 `*` 时，自动强制 `allow_credentials=False`
- 限制允许的 HTTP 方法和头

#### 3. 无 API 鉴权 (已修复)

**问题**: 所有 API 端点无需任何认证即可访问

**修复**:
- 新增 `AuthMiddleware` 中间件
- 支持 `X-API-Key` 头鉴权
- 可通过环境变量或配置文件设置

```bash
# 环境变量方式
export HAKUSAI_API_KEY="your-secret-key-here"
```

```yaml
# 配置文件方式
security:
  api_key: "your-secret-key-here"
  api_key_header: "X-API-Key"
```

#### 4. Shell 命令注入风险 (已修复)

**问题**: `dev_tools.py` 使用 `shell=True` 执行任意命令，无白名单限制

**修复**:
- 新增命令白名单机制
- 内置危险模式黑名单
- 简单命令使用参数化执行（避免 `shell=True`）
- 所有命令执行记录审计日志

---

## 配置选项

### SecurityConfig 完整配置

```yaml
security:
  # ========== 绑定地址 ==========
  host: "127.0.0.1"        # 监听地址 (默认仅本地)
  port: 8080                # 监听端口
  
  # ========== CORS 配置 ==========
  cors_origins:
    - "http://localhost:1421"
    - "http://127.0.0.1:1421"
  cors_allow_credentials: true  # ["*"] 时强制 false
  
  # ========== API 鉴权 ==========
  api_key: ""                # 空 = 禁用鉴权 (开发模式)
  api_key_header: "X-API-Key"  # 自定义头名称
  
  # ========== WebSocket 鉴权 ==========
  ws_auth_query_param: "token"
  ws_auth_enabled: true
  
  # ========== 命令执行安全 ==========
  allow_commands: []         # 空 = 禁止所有命令
  # 示例允许列表:
  # allow_commands:
  #   - git
  #   - npm
  #   - python
  #   - pip
  #   - cat
  #   - ls
  #   - find
  #   - grep
  
  block_commands:            # 永久禁止的危险模式
    - "rm -rf /"
    - "mkfs"
    - "format"
    - "> /dev/sda"
  
  require_confirmation_for_shell: true
  
  # ========== 审计日志 ==========
  audit_log_enabled: true
  audit_log_path: "logs/audit.log"
  
  # ========== 速率限制 ==========
  rate_limit_enabled: true
  rate_limit_requests_per_minute: 60
```

---

## 环境变量

| 变量名 | 描述 | 默认值 |
|--------|------|--------|
| `HAKUSAI_API_KEY` | API 密钥 | (空) |
| `HAKUSAI_ALLOW_COMMANDS` | 允许的命令列表 (逗号分隔) | (空) |
| `HAKUSAI_STRICT_MODE` | 严格模式 (拒绝所有需确认操作) | `false` |
| `HAKUSAI_HOST` | 覆盖监听地址 | (使用配置文件) |
| `HAKUSAI_PORT` | 覆盖监听端口 | (使用配置文件) |

### 示例：启用完整安全配置

```bash
#!/bin/bash
# production_start.sh

export HAKUSAI_API_KEY="$(openssl rand -base64 32)"
export HAKUSAI_ALLOW_COMMANDS="git,npm,node,python,pip,cat,ls,find,grep,head,tail,wc"
export HAKUSAI_STRICT_MODE="false"

python -m hakusai_server
```

---

## 生产环境部署清单

### 必须配置 (Required)

- [ ] **设置 API Key**
  ```bash
  export HAKUSAI_API_KEY="<强随机密码>"
  ```

- [ ] **配置允许的命令**
  ```bash
  export HAKUSAI_ALLOW_COMMANDS="git,npm,python,pip"
  ```

- [ ] **防火墙规则**
  ```bash
  # 仅允许特定 IP 访问 8080 端口
  sudo ufw allow from <YOUR_IP> to any port 8080
  ```

- [ ] **使用 HTTPS 反向代理** (如果远程访问)
  ```nginx
  # nginx.conf
  server {
      listen 443 ssl;
      server_name your-domain.com;
      
      ssl_certificate /path/to/cert.pem;
      ssl_certificate_key /path/to/key.pem;
      
      location / {
          proxy_pass http://127.0.0.1:8080;
          proxy_set_header X-API-Key $http_x_api_key;
          proxy_set_header Host $host;
          proxy_set_header X-Real-IP $remote_addr;
      }
  }
  ```

### 推荐配置 (Recommended)

- [ ] 启用审计日志
- [ ] 配置日志轮转
- [ ] 定期审查审计日志
- [ ] 限制 `security.host` 为 `127.0.0.1`，通过反向代理暴露

### 可选增强 (Optional)

- [ ] 启用严格模式 (`HAKUSAI_STRICT_MODE=true`)
- [ ] 集成外部认证系统 (OIDC/OAuth2)
- [ ] 配置 Web Application Firewall (WAF)

---

## 审计日志

### 日志格式

```
[TIMESTAMP] [STATUS] ACTION ip=CLIENT_IP details=DETAILS ua=USER_AGENT
```

### 示例

```
[2024-01-15 10:30:45] [OK] AUTH_SUCCESS ip=192.168.1.100 path=/api/chat details=session=default
[2024-01-15 10:31:02] [FAIL] AUTH_FAILED ip=203.0.113.50 path=/api/config ua=BadBot/1.0
[2024-01-15 10:32:15] [OK] BASH_EXEC ip=agent command=git status allowed=true
[2024-01-15 10:33:00] [FAIL] RATE_LIMITED ip=198.51.100.23 path=/api/chat reason=Rate limit exceeded
```

### 查看审计日志

```bash
# 实时查看
tail -f logs/audit.log

# 统计失败请求
grep "\\[FAIL\\]" logs/audit.log | wc -l

# 查找可疑 IP
grep "\\[FAIL\\]" logs/audit.log | awk '{print $5}' | sort | uniq -c | sort -rn | head
```

---

## 安全测试

### 测试 API Key 鉴权

```bash
# 无 Key 访问 (应返回 401)
curl -v http://localhost:8080/api/version

# 带 Key 访问 (应返回 200)
curl -v -H "X-API-Key: your-key" http://localhost:8080/api/version
```

### 测试命令白名单

```bash
# 发送聊天消息尝试执行被禁止的命令
curl -X POST http://localhost:8080/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "run rm -rf /"}'
# 应返回 [SECURITY BLOCKED]
```

### 测试速率限制

```bash
# 快速发送多个请求 (超过 60 req/min 应返回 429)
for i in {1..70}; do curl -s http://localhost:8080/health; done
```

---

## 报告安全问题

如果您发现安全漏洞，请：

1. **不要**公开发布
2. 发送邮件至安全团队
3. 详细描述：
   - 漏洞类型
   - 复现步骤
   - 潜在影响
   - 建议修复方案

---

## 更新历史

| 版本 | 日期 | 变更 |
|------|------|------|
| 1.0.0 | 2024-01 | 初始安全框架 |
| 1.1.0 | 2024-01 | 修复 4 个严重安全漏洞 |

---

*本文档随 HakusAI 安全更新而更新。请定期检查最新版本。*
