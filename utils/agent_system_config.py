"""
Agent 系统配置 - ()

包含以下配置：
1. Skill 生命周期配置
2. 增强工具注册表配置
3. GEPA 优化配置
4. 沙箱执行配置
5. 长期任务编排器配置（新增）
"""
import os

AGENT_SYSTEM_CONFIG = {
    # ==================== Skill 生命周期配置 ====================
    "skill_lifecycle": {
        # 最大活跃技能数量（防止无限膨胀） - ：支持50个并发skill
        "max_active_skills": 50,

        # 相似度阈值（新 skill 与已有 skill 相似度超过此值时触发合并）
        "similarity_threshold": 0.8,

        # 存储目录
        "storage_dir": os.path.join(os.path.expanduser("~"), ".hakus", "skills"),

        # 自动清理
        "auto_cleanup": True,

        # TTL 配置（天）
        "ttl_days": 90,

        # 观察期配置（天）
        "observing_days": 7,

        # 归档条件
        "archive_conditions": {
            # 30 天未使用
            "idle_days": 30,
            # 热度分数低于此值
            "heat_threshold": 10,
        },
    },

    # ==================== 增强工具注册表配置 ====================
    "enhanced_registry": {
        # 健康检查间隔（秒）
        "health_check_interval": 60,  # 1分钟（更频繁监控）

        # 最大版本数
        "max_versions": 5,

        # 自动迁移
        "auto_migrate": True,

        # 工具调用缓存
        "tool_cache_enabled": True,
        "cache_ttl_seconds": 300,
    },

    # ==================== GEPA 优化配置（的自我进化） ====================
    "gepa": {
        # 触发方式
        "triggers": {
            # 手动触发（用户命令 /optimize）
            "manual": True,

            # 定时触发（cron 表达式：每天凌晨2点）
            "scheduled": {
                "enabled": True,
                "cron": "0 2 * * *",
            },

            # 阈值触发
            "threshold": {
                "enabled": True,
                # 使用次数超过此值后检查
                "usage_count": 20,
                # 成功率低于此值时触发优化
                "success_rate_below": 0.8,
            },
        },

        # 优化参数（：更深度的优化）
        "optimization": {
            # 最大迭代次数
            "max_rounds": 1000,
            # 单次优化超时（秒）
            "timeout_per_optimization": 600,
            # 改进阈值（低于此值认为无改进）
            "improvement_threshold": 0.02,  # 2%（更敏感）
            # 启用多目标优化
            "multi_objective_optimization": True,
        },

        # 存储目录
        "storage_dir": os.path.join(os.path.expanduser("~"), ".hakus", "gepa"),
    },

    # ==================== 沙箱执行配置（：更强大的沙箱） ====================
    "sandbox": {
        # Docker 配置
        "docker": {
            "image": "python:3.11-slim",
            "cpu_limit": "4.0",  # 4核CPU
            "memory_limit": "2048m",  # 2GB内存
            "disk_limit": "500m",
            "timeout": 120,  # 2分钟超时
            "network_enabled": True,  # 允许网络访问
            "work_dir": "/tmp/sandbox",
        },

        # 命令白名单（扩展版 - 工具集）
        "allowed_commands": [
            "ls", "cat", "grep", "find", "wc", "head", "tail", "echo",
            "pwd", "date", "whoami", "uname", "df", "free", "top",
            "python3", "python", "pip3", "pip",
            "mkdir", "touch", "cp", "mv", "rm", "chmod", "chown",
            "git", "npm", "node", "yarn", "cargo", "go", "make", "cmake",
            "curl", "wget", "ssh", "scp", "rsync",
            "docker", "docker-compose", "kubectl",
            "jq", "sed", "awk", "sort", "uniq", "tr", "cut",
            "tar", "gzip", "gunzip", "zip", "unzip",
            "ps", "kill", "pgrep", "htop", "vmstat", "iostat",
            "env", "export", "source", "alias",
        ],

        # 允许网络的命令
        "allowed_with_network": [
            "curl", "wget", "ping", "git", "npm", "pip", "cargo",
            "ssh", "scp", "rsync", "docker", "kubectl",
        ],

        # 危险命令（始终禁止）
        "dangerous_commands": [
            "rm -rf /", "mkfs", "fdisk", "mount --bind /",
            "chmod 777 /", "chown root:", "su root", "sudo su",
            ":(){ :|:& };:",  # fork bomb
            "dd if=/dev/zero of=/dev/sda",  # 磁盘销毁
        ],
    },

    # ==================== 长期任务编排器配置（） ====================
    "orchestrator": {
        # 并行执行配置
        "parallel_execution": {
            "enabled": True,
            "max_parallel_agents": 8,  # 最多8个子Agent并行
            "max_parallel_tasks": 4,   # 最多4个任务并行
        },

        # 批量处理配置
        "batch_processing": {
            "default_batch_size": 10,      # 默认批量大小（原为3）
            "max_batch_size": 20,          # 最大批量大小
            "max_iterations": 30,          # 最大迭代次数
            "adaptive_batching": True,     # 自适应批量调整
        },

        # 超时配置
        "timeouts": {
            "planner_timeout": 900,        # 计划Agent: 15分钟
            "developer_timeout": 1800,     # 开发Agent: 30分钟
            "tester_timeout": 600,         # 测试Agent: 10分钟
            "task_total_timeout": 7200,    # 单个任务总超时: 2小时
        },

        # 智能决策配置
        "intelligent_decision": {
            "auto_retry_on_failure": True,      # 失败自动重试
            "max_retries": 3,                    # 最大重试次数
            "learning_from_errors": True,        # 从错误中学习
            "dynamic_priority_adjustment": True, # 动态优先级调整
            "context_aware_scheduling": True,    # 上下文感知调度
        },

        # 子Agent能力配置（）
        "sub_agent_capabilities": {
            "tool_calling_enabled": True,       # 启用工具调用
            "file_operations_enabled": True,    # 文件操作
            "command_execution_enabled": True,   # 命令执行
            "web_search_enabled": True,          # 网络搜索
            "code_execution_enabled": True,      # 代码执行
            "max_tokens_per_call": 16384,        # 每次调用最大token数（原为8192）
            "context_window": 128000,            # 上下文窗口大小
        },
    },
}
