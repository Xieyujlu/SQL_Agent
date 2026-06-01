# SQLAgent-ms

基于 **DeepAgents** + **LangChain** 的多智能体（Multi-Agent）数据查询系统。用户通过 Web 聊天界面用自然语言提问，系统自动调度子 Agent 完成数据库查询、数据可视化等任务。

## 特性

- **自然语言查询**：用中文描述需求，Agent 自动理解并生成 SQL
- **Human-in-the-Loop**：SQL 执行后暂停等待人工审核，支持「准确/错误/其他建议」反馈，服务重启后会话不丢失
- **流式输出**：SSE 实时推送 Agent 思考过程和查询结果
- **长期记忆**：MySQL 存储用户偏好 + ChromaDB 向量存储事件记忆，跨会话保持上下文
- **模型备选**：主模型 qwen3.5-plus 失败时自动降级到 qwen-turbo
- **Langfuse Tracing**：每次对话自动记录 LLM 调用链和 Token 用量
- **工具熔断**：数据库连续失败自动短路，防止无限重试

## 技术栈

| 层 | 技术 |
|------|------|
| 框架 | DeepAgents 0.5.9 + LangChain 1.2 + LangGraph 1.1 |
| LLM | 阿里通义千问 (qwen3.5-plus / qwen-turbo 备选) |
| 后端 | FastAPI + Uvicorn |
| 前端 | 原生 HTML/CSS/JS（无构建工具） |
| 数据库 | MySQL (SQLAlchemy + PyMySQL) + SQLite (LangGraph 检查点持久化) |
| 向量存储 | ChromaDB（嵌入式，本地持久化） |
| 可视化 | MCP 协议 → ModelScope 绘图服务 |
| Tracing | Langfuse v4.6 |

## 架构

```
src/frontend/              ← 用户浏览器（SSE 流式 + HITL 审核按钮）
     ↓ POST /api/chat  /api/chat/feedback
src/backend/main.py        ← FastAPI 入口，启动时初始化 agent，注入 user_id
     ↓
src/backend/agent_runner.py  ← AgentRunner（生命周期 + HITL 中断/恢复 + 异常兜底）
     ↓
src/multi_agent/multi_agent.py  ← _FallbackChatModel + create_my_agent() 构建
     ↓
┌── SQL 子 Agent ────┬── 主 Agent (记忆) ────┬── MCP 子 Agents ──┐
│  ListTablesTool     │  GetUserProfileTool   │  绘图 (ModelScope) │
│  TableSchemaTool    │  SetUserProfileTool   │                    │
│  SQLQueryTool (HITL)│  SaveEventTool        │                    │
│  SQLQueryCheckerTool│  SearchEventTool      │                    │
└────────────────────┴───────────────────────┴───────────────────┘
         ↓ interrupt()        ↓ MySQL + ChromaDB    AsyncSqliteSaver
    LangGraph 暂停          长期记忆持久化          checkpoint 恢复
```

## 快速开始

### 环境要求

- Python >= 3.11
- MySQL 本地 3306 端口
- 阿里云 DashScope API Key
- Langfuse API Key（可选，用于 Tracing）

### 安装

```bash
git clone <repo-url> && cd SQLAgent-ms

python3 -m venv venv
source venv/bin/activate

pip install deepagents langchain langchain-openai langchain-mcp-adapters \
            langgraph langgraph-checkpoint-sqlite fastapi uvicorn loguru \
            sqlalchemy pymysql aiosqlite chromadb langfuse
```

### 配置

编辑 `src/agent/.env`：

```env
DASHSCOPE_API_KEY=your_dashscope_api_key
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=your_password
MYSQL_DATABASE=stock
LANGFUSE_SECRET_KEY=your_langfuse_secret   # 可选
LANGFUSE_PUBLIC_KEY=your_langfuse_public   # 可选
LANGFUSE_BASE_URL=https://cloud.langfuse.com
```

### 启动

```bash
source venv/bin/activate
uvicorn src.backend.main:app --reload --port 8000
```

浏览器打开 `http://localhost:8000`，输入称呼后即可开始查询。

## HITL 审核流程

```
用户提问 → Agent 生成 SQL → SQLQueryTool 执行 → LangGraph 暂停
    ↓
前端展示 SQL + 查询结果 + 审核按钮（准确/错误/其他建议）
    ↓
用户反馈 → Agent 根据反馈继续分析或重新查询
    ↓
checkpoint 持久化到 SQLite → 服务重启后同一 session 可恢复
```

## 项目结构

```
src/
  backend/
    main.py              # FastAPI 应用（路由 + 静态文件）
    agent_runner.py      # AgentRunner（生命周期 + HITL + 异常兜底）
  multi_agent/
    multi_agent.py       # _FallbackChatModel + create_my_agent()
    mcp_tool_config.py   # MCP 外部服务配置
  agent/
    tools/
      tool.py            # 4 个数据库工具（HITL interrupt + 熔断保护）
      safe_tool.py       # 工具熔断 Mixin（CircuitBreakerMixin）
      memory_tools.py    # 4 个长期记忆工具
    utils/
      db_utils.py        # SQLAlchemy 数据库管理
      feedback_db.py     # HITL 反馈 MySQL 写入
      user_profile_db.py # 用户属性长期记忆（MySQL key-value）
      event_memory.py    # 事件记忆 ChromaDB 向量存储
      tracing.py         # Langfuse Trace 集成
  frontend/
    index.html           # 聊天界面 + 用户名遮罩
    style.css            # 消息气泡 + HITL 按钮样式
    app.js               # SSE 流式解析 + HITL 反馈 UI
  teaching_skills/       # Agent 技能脚本
data/
  chroma/                # ChromaDB 持久化文件
  checkpoints.db         # LangGraph 检查点数据库
```
