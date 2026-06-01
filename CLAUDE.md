# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

SQLAgent-ms 是一个基于 **deepagents** + **langchain** 的多智能体（Multi-Agent）数据查询系统。用户通过 Web 聊天界面用自然语言提问，系统自动调度子 Agent 完成数据库查询、数据可视化等任务。

核心功能：
- 自然语言查询 MySQL 数据库
- Human-in-the-Loop（HITL）SQL 审核：SQL 执行后暂停，等待用户反馈后继续
- 长期记忆：MySQL 存储用户偏好 + ChromaDB 向量存储事件记忆
- 用户名身份识别：支持多用户切换，跨设备找回记忆

## 技术栈

- **框架**: deepagents 0.5.9, langchain 1.2.18, langgraph 1.1.10, langchain-mcp-adapters
- **LLM**: 阿里通义千问 (DashScope)，主模型 qwen3.5-plus，备用模型 qwen-turbo（try-except 自动降级）
- **后端**: FastAPI + uvicorn（SSE 流式输出）
- **前端**: 原生 HTML/CSS/JS（无构建工具）
- **数据库**: MySQL (SQLAlchemy + PyMySQL) + SQLite (aiosqlite, LangGraph 检查点持久化)
- **向量存储**: ChromaDB（嵌入式，本地持久化）
- **外部服务**: MCP 协议连接（ModelScope 绘图）
- **Tracing**: Langfuse v4.6（LLM 调用跟踪 + Token 统计）

## 启动方式

```bash
# 确保在项目根目录下
source venv/bin/activate          # 先激活虚拟环境（macOS/Linux）
uvicorn src.backend.main:app --reload --port 8000
# 浏览器打开 http://localhost:8000
```

## 架构

```
src/frontend/ (HTML/CSS/JS)   ← 用户浏览器（SSE 流式接收 + HITL 审核按钮）
     ↓ POST /api/chat  /api/chat/feedback
src/backend/main.py            ← FastAPI 入口，启动时初始化 agent，注入 user_id
     ↓
src/backend/agent_runner.py    ← AgentRunner，管理 agent 生命周期 + HITL 中断/恢复
     ↓
src/multi_agent/multi_agent.py ← create_my_agent() 构建 deep_agent + 注册记忆工具
     ↓                                          ↓ AsyncSqliteSaver
┌── SQL 子 Agent (核心) ──┬── 主 Agent (记忆工具) ──┬── MCP 子 Agents ──┐
│  ListTablesTool          │  GetUserProfileTool    │  绘图 (ModelScope) │
│  TableSchemaTool         │  SetUserProfileTool    │                    │
│  SQLQueryTool (HITL)     │  SaveEventTool         │                    │
│  SQLQueryCheckerTool     │  SearchEventTool       │                    │
└──────────────────────────┴────────────────────────┴───────────────────┘
         ↓ interrupt()               ↓ MySQL              ↓ ChromaDB
    LangGraph 暂停等待          user_profiles 表      event_memory 向量
    checkpoint 持久化到 SQLite → 用户审核 → resume 恢复
```

## 项目结构

```
src/
  backend/
    main.py              # FastAPI 应用，路由 + 静态文件托管
    agent_runner.py      # AgentRunner 封装（chat / HITL 中断 / resume）
  multi_agent/
    multi_agent.py       # deep_agent 构建工厂 create_my_agent()
    mcp_tool_config.py   # MCP 外部服务连接配置
  agent/
    tools/
      tool.py            # 4 个数据库工具（含 HITL interrupt + 熔断保护）
      safe_tool.py       # 工具熔断 Mixin（连续失败自动短路）
      memory_tools.py    # 4 个长期记忆工具（用户属性 + 事件记忆）
    utils/
      db_utils.py        # MySQLDatabaseManager（SQLAlchemy 封装）
      feedback_db.py     # HITL 反馈 SQL 写入 MySQL
      user_profile_db.py # 用户属性长期记忆（MySQL key-value 存储）
      event_memory.py    # 事件记忆 ChromaDB 向量存储
      tracing.py         # Langfuse 集成（trace 跟踪 + token 统计）
      log_utils.py       # loguru 日志配置
  frontend/
    index.html           # 聊天界面 + 用户名输入遮罩
    style.css            # 样式（气泡消息，HITL 按钮，用户遮罩）
    app.js               # 前端逻辑（SSE 流式，HITL UI，userId localStorage）
  teaching_skills/       # Agent 技能脚本
data/
  chroma/                # ChromaDB 持久化文件（自动生成）
```

## 关键技术细节

### HITL（Human-in-the-Loop）审核流程

- SQLQueryTool._run() 执行 SQL 后调用 `langgraph.types.interrupt()` 暂停图执行
- agent_runner._stream() 检测 `__interrupt__` 事件，yield `hitl_required` dict 后 `break` 退出流
- 前端展示 SQL + 查询结果 + 3 个审核按钮（准确/错误/其他建议）
- 用户提交反馈 → POST /api/chat/feedback → Command(resume=...) 恢复图执行
- **关键**：interrupt 后必须 break 退出 _stream，否则 SSE 流会永久悬挂
- **持久化**：检查点写入 SQLite（`data/checkpoints.db`），服务重启后同一 session_id 仍可恢复

### 长期记忆系统

- **MySQL 用户属性**：`user_profiles` 表（user_id + attribute + value），GetUserProfileTool / SetUserProfileTool
- **ChromaDB 事件记忆**：本地持久化向量库（`data/chroma/`），SaveEventTool / SearchEventTool，内置 all-MiniLM-L6-v2 embedding
- **短期记忆/会话持久化**：AsyncSqliteSaver（`data/checkpoints.db`），服务重启后 HITL 会话不丢失，可继续恢复
- **user_id 注入**：通过 `contextvars.ContextVar` 从 API 层传递到工具层

### 已知待改进

- **记忆注入从"拉"改"推"**：当前依赖 LLM 在 prompt 指引下主动调用 `get_user_profile` / `search_event`（拉模式），存在被跳过或遗忘的风险。更可靠的做法是在 `agent_runner.py` 的 `_stream()` 中，每次请求前自动查询 MySQL/ChromaDB，将用户偏好和历史事件拼入 system prompt（推模式），确保记忆一定被使用。改动点：`agent_runner.py` 的 `_stream()` + `main.py` 的 event_stream。

### 稳定性保障

- **LLM 重试**：`max_retries=3` + `timeout=60`，API 超时/限流自动 exponential backoff 重试。注意 `with_fallbacks()` 与 `create_deep_agent` 框架不兼容，不可使用
- **Agent 轮次上限**：`recursion_limit=25`，防止 Agent 陷入死循环无限烧 token。正常 SQL 查询 4-6 轮结束，25 轮足够兜底
- **工具熔断器**（`safe_tool.py` CircuitBreakerMixin）：每个数据库工具独立计数。连续失败 3 次后 30 秒内 **抛 RuntimeError**（LangGraph 感知为 tool error，强制终止而非靠 LLM 自觉停止）。冷却期后自动探活一次。已集成到全部 4 个工具
- **全局异常兜底**：`_stream()` 最外层 try-except 包裹，未预料的异常不卡死前端，yield `error` 事件并提示重试
- **前端错误处理**：SSE 解析新增 `error` 事件，红色显示错误信息
- **HITL 会话持久化**：AsyncSqliteSaver 将检查点写入 `data/checkpoints.db`，服务重启/崩溃后 HITL 审核中的会话可继续恢复，不再丢失
- **Feedback user_id**：`/api/chat/feedback` 端点不再硬编码 `"default"`，通过 `ContextVar` 注入前端传来的真实 `user_id`
- **模型备选**：`_FallbackChatModel`（`multi_agent.py`）包装主模型 qwen3.5-plus + 备用模型 qwen-turbo。通过 `BaseChatModel` 子类 + `__getattr__` 委托模式，所有自省属性（profile、model_name、_get_ls_params 等）委托给主模型，仅 `_generate` / `_agenerate` / `_stream` / `_astream` 做 try-except 降级。`bind_tools` / `bind` 显式覆盖以保证 RunnableBinding 换绑到 wrapper 自身

### Langfuse Tracing

- **CallbackHandler**: 每次请求创建独立实例，注入 `config["callbacks"]`，LangGraph 自动传播到所有子 Agent 和 LLM 调用
- **Trace 隔离**: 每个请求独立的 CallbackHandler，不同 session 的 trace 相互独立
- **元数据**: trace_context 包含 user_id + session_id，可在 Langfuse UI 中按用户/会话筛选
- **Token 统计**: CallbackHandler 自动拦截 `on_llm_end` 事件，记录 prompt_tokens / completion_tokens / total_tokens
- **前端展示**: SSE 流结束后 yield `trace_info` 事件，前端渲染 Langfuse Trace 链接
- **配置文件**: `src/agent/utils/tracing.py`，环境变量 `LANGFUSE_SECRET_KEY` / `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_BASE_URL`

### 用户身份

- 前端 `localStorage` 存储 `sqlagent_username`（用户输入的称呼）
- 首次访问弹出遮罩输入框，后续访问跳过
- header 显示当前用户名，点击可切换用户（清空聊天记录 + 重置 sessionId）
- 同一用户名跨设备/清缓存后输入即可找回记忆

### 其他

- **CompiledSubAgent 是 dict 子类** — 访问属性用 `s["name"]` / `s.get("name")`，不用 `s.name`
- **MCP 服务器连接有 try-except 保护** — 外部服务不可用时自动跳过，不影响核心 SQL 功能
- **AsyncSqliteSaver** — 对话检查点持久化到 SQLite（`data/checkpoints.db`），服务重启后 HITL 会话可恢复
- **LocalShellBackend** — 文件系统沙箱，限制 agent 可执行命令的范围
- **SQL 工具只读约束** — execute_query 和 check_query 均只允许 SELECT/WITH 语句

## 环境要求

- **环境变量**: `DASHSCOPE_API_KEY`（阿里通义千问 API Key）
- **MySQL**: 本地 3306 端口，数据库 `stock`，用户 root / 密码 123456（见 .env）
- **Python**: >= 3.11（使用了 `str | None` 类型注解语法）
- **ChromaDB**: 首次启动自动下载 all-MiniLM-L6-v2 模型（约 80MB）

## 依赖安装

项目使用虚拟环境（`venv/`）管理依赖。首次搭建环境：

```bash
# 创建虚拟环境（需 Python >= 3.11）
python3 -m venv venv

# 激活虚拟环境
source venv/bin/activate       # macOS/Linux

# 安装依赖
pip install deepagents langchain langchain-openai langchain-mcp-adapters \
            langgraph langgraph-checkpoint-sqlite fastapi uvicorn loguru \
            sqlalchemy pymysql aiosqlite chromadb langfuse
```

**注意：** 运行项目或安装新依赖前，务必先 `source venv/bin/activate`，避免污染系统 Python 环境。

## 关键文件索引

| 文件 | 作用 |
|------|------|
| [src/multi_agent/multi_agent.py](src/multi_agent/multi_agent.py) | deep_agent 构建入口，子 agent + 记忆工具注册 |
| [src/backend/main.py](src/backend/main.py) | FastAPI 应用，POST /api/chat + /api/chat/feedback |
| [src/backend/agent_runner.py](src/backend/agent_runner.py) | Agent 生命周期 + HITL 中断 + 异常兜底 + recursion_limit |
| [src/agent/tools/tool.py](src/agent/tools/tool.py) | 4 个数据库工具（含 interrupt + 熔断保护） |
| [src/agent/tools/safe_tool.py](src/agent/tools/safe_tool.py) | 工具熔断 Mixin（CircuitBreakerMixin） |
| [src/agent/tools/memory_tools.py](src/agent/tools/memory_tools.py) | 4 个长期记忆工具 |
| [src/agent/utils/db_utils.py](src/agent/utils/db_utils.py) | SQLAlchemy 数据库管理 |
| [src/agent/utils/user_profile_db.py](src/agent/utils/user_profile_db.py) | MySQL 用户属性 CRUD |
| [src/agent/utils/event_memory.py](src/agent/utils/event_memory.py) | ChromaDB 事件向量存储 |
| [src/agent/utils/tracing.py](src/agent/utils/tracing.py) | Langfuse Trace 集成（CallbackHandler + Token 统计） |
| [src/agent/utils/feedback_db.py](src/agent/utils/feedback_db.py) | HITL 反馈 MySQL 写入 |
| [src/frontend/app.js](src/frontend/app.js) | 前端逻辑（SSE 解析、HITL UI、userId 管理） |
| [src/multi_agent/mcp_tool_config.py](src/multi_agent/mcp_tool_config.py) | MCP 外部服务 URL 配置 |
