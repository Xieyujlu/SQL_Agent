# SQLAgent-ms

基于 **DeepAgents** + **LangChain** 的多智能体（Multi-Agent）数据查询系统。用户通过 Web 聊天界面用自然语言提问，系统自动调度子 Agent 完成数据库查询、数据可视化等任务。

## 特性

- **自然语言查询**：用中文描述需求，Agent 自动理解并生成 SQL
- **Human-in-the-Loop**：SQL 执行后暂停等待人工审核，支持「准确/错误/其他建议」反馈
- **流式输出**：实时展示 Agent 思考过程和查询结果
- **多智能体协作**：SQL 查询 + 数据可视化子 Agent 协同工作
- **安全沙箱**：本地 Shell 后端限制文件系统访问范围

## 技术栈

| 层 | 技术 |
|------|------|
| 框架 | DeepAgents + LangChain + LangGraph |
| LLM | 阿里通义千问 (qwen3.5-plus) |
| 后端 | FastAPI + Uvicorn |
| 前端 | 原生 HTML/CSS/JS |
| 数据库 | MySQL (SQLAlchemy + PyMySQL) |
| 可视化 | MCP 协议 → ModelScope 绘图服务 |

## 架构

```
src/frontend/          ← 用户浏览器（聊天界面）
     ↓ SSE
src/backend/main.py    ← FastAPI 入口
     ↓
src/backend/agent_runner.py  ← Agent 生命周期 + HITL 中断/恢复
     ↓
src/multi_agent/       ← deep_agent 构建 + MCP 配置
     ↓
┌── SQL 子 Agent ──┬── 绘图子 Agent ──┐
│  ListTablesTool   │  MCP 连接         │
│  TableSchemaTool  │  ModelScope       │
│  SQLQueryTool     │                   │
│  SQLQueryChecker   │                   │
└──────────────────┴──────────────────┘
```

## 快速开始

### 环境要求

- Python >= 3.11
- MySQL（本地 3306 端口）
- 阿里云 DashScope API Key

### 安装

```bash
# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate

# 安装依赖
pip install deepagents langchain langchain-openai langchain-mcp-adapters \
            langgraph fastapi uvicorn loguru sqlalchemy pymysql
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
```

### 启动

```bash
source venv/bin/activate
uvicorn src.backend.main:app --reload --port 8000
```

浏览器打开 `http://localhost:8000`，在聊天框中输入问题即可开始查询。

## 项目结构

```
src/
  backend/
    main.py              # FastAPI 应用 + 路由
    agent_runner.py      # AgentRunner（chat / HITL 中断 / 恢复）
  multi_agent/
    multi_agent.py       # deep_agent 构建入口
    mcp_tool_config.py   # MCP 外部服务配置
  agent/
    tools/tool.py        # 数据库工具（4 个）
    utils/db_utils.py    # SQLAlchemy 数据库管理
    utils/feedback_db.py # HITL 反馈存储
    utils/log_utils.py   # 日志配置
  frontend/
    index.html           # 聊天界面
    style.css            # 样式
    app.js               # 前端逻辑（Markdown 渲染 + SSE）
  teaching_skills/       # Agent 技能脚本
```

## HITL 审核流程

```
用户提问 → Agent 执行 → SQLQueryTool 执行 SQL → 暂停
    ↓
前端展示 SQL + 查询结果 + 审核按钮（准确/错误/其他建议）
    ↓
用户反馈 → Agent 根据反馈调整分析或重新查询
```
