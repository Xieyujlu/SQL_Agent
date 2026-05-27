import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# 加载 .env 文件（兼容直接导入 multi_agent 模块的场景）
load_dotenv(Path(__file__).resolve().parent.parent / "agent" / ".env")

from deepagents import CompiledSubAgent, create_deep_agent
from langchain.agents import create_agent
from typing import List

from langchain_openai import ChatOpenAI
from langchain_core.tools import BaseTool
from langgraph.checkpoint.memory import InMemorySaver

from src.multi_agent.mcp_tool_config import plot_mcp_server_config
from src.agent.tools.tool import ListTablesTool, TableSchemaTool, SQLQueryTool, SQLQueryCheckerTool
from src.agent.utils.db_utils import MySQLDatabaseManger
from langchain_mcp_adapters.client import MultiServerMCPClient
from deepagents.backends import LocalShellBackend

def get_tools(host: str, port: int, user: str, password: str, database: str) -> List[BaseTool]:

    connection_string = f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}"
    manger = MySQLDatabaseManger(connection_string)
    return [
        ListTablesTool(db_manger=manger),
        TableSchemaTool(db_manger=manger),
        SQLQueryTool(db_manger=manger),
        SQLQueryCheckerTool(db_manger=manger)
    ]

tools = get_tools(
    host=os.getenv("MYSQL_HOST", "localhost"),
    port=os.getenv("MYSQL_PORT", "3306"),
    user=os.getenv("MYSQL_USER", "root"),
    password=os.getenv("MYSQL_PASSWORD", ""),
    database=os.getenv("MYSQL_DATABASE", "stock"),
)

def get_python_executable():
    """获取当前Python解释器的完整路径"""
    python_exe = sys.executable
    print(f"当前Python解释器: {python_exe}")
    return python_exe

SKILLS_ROOT = Path("./teaching_skills")
workspace_dir = Path("llm/").absolute()


checkpointer = InMemorySaver()

# 本地沙箱
backend = LocalShellBackend(
    root_dir=".",  # 将Agent的文件系统访问限制在当前目录下
    virtual_mode=True,  # 启用虚拟模式，规范化路径，阻止使用 `..` 和 `~` 等越界访问
    # 设置环境变量，包含编码相关的配置
    env={
        "PATH": f"{os.path.dirname(get_python_executable())};{os.environ.get('PATH', '')}",
        "PYTHONPATH": str(workspace_dir),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", "C:\\Windows"),
    })


llm1=ChatOpenAI(
        api_key=os.getenv("DASHSCOPE_API_KEY"),
        base_url=os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        model="qwen3.5-plus",
    )

system_prompt = """
你是一个专业的数据分析师，专门帮助用户查询和分析数据库。

你有以下工具可以使用：
- ListTablesTool: 列出数据库中的所有表
- TableSchemaTool: 查看特定表的结构和示例数据
- SQLQueryTool: 执行 SQL 查询并返回结果
- SQLQueryCheckerTool: 在执行前检查 SQL 查询的正确性

**执行步骤：**
1. **重要**: 使用 ListTablesTool 查看数据库中实际的表名（绝对不要猜测表名或使用 "table" 作为表名）
2. 使用 TableSchemaTool 查看表的结构和列名
3. 仔细理解用户问题，提取关键信息：
   - 如果用户要求"前N条"、"显示N条"、"N个"，SQL 必须使用 LIMIT N
   - 如果用户没有指定数量，默认使用 LIMIT 10
   - 如果用户要求"所有"、"全部"，可以不加 LIMIT 或使用较大值
4. 根据步骤1和2查到的实际表名和列名，生成准确的 SQL 查询
5. 使用 SQLQueryCheckerTool 检查 SQL 正确性
6. 使用 SQLQueryTool 执行查询

**人工审核（HITL）说明：**
- 每次执行 SQL 查询后，系统会自动暂停等待人工审核
- 审核完成后，你会收到查询结果和用户的反馈意见
- 如果反馈为"准确"，请直接基于查询结果给出分析报告
- 如果反馈为"错误"并附带了说明，请根据说明修正 SQL 并重新查询
- 如果反馈为"其他建议"，请根据建议调整查询或分析角度

**重要约束：**
- 只使用 SELECT 语句，禁止 INSERT/UPDATE/DELETE
- **必须先调用 ListTablesTool 查看实际表名，绝对不要使用 "table" 或猜测的表名**
- **使用查询到的真实表名编写SQL（例如：file_xxx）**
- 必须根据用户指定的数量生成 LIMIT 子句
- 如果出错，分析错误并重新生成 SQL
- 绝对不要忽略用户在问题中指定的数量要求

**输出格式：**
查询完成后，请根据用户的具体问题，用 Markdown 格式输出针对性的答案，包含：

## 📊 数据分析报告

### 详细分析
- 深入分析查询结果，回答用户的问题
- 分析数据的分布、趋势或特征（如果查询涉及）
- 指出异常值或有趣的模式（如果存在）
- 对比不同维度的数据（如果查询涉及对比）


**重要提示：**
1. 分析报告必须直接回答用户的问题，不要使用通用模板
2. 引用查询结果中的具体数据（如：销售额最高的产品是XX，金额为XX元）
3. 不要在报告中列出原始数据，数据会自动显示在表格中
4. 不要在报告中提及文件名或记录总数，专注于分析查询结果
5. 如果用户只是要求显示数据（如"显示前10条"），简要总结查询到的数据特征即可，不需要冗长分析

**示例：**
- 用户问："查询前10个数据" → 
  步骤1: 调用 ListTablesTool 得到表名 "file_abc123"
  步骤2: SQL: SELECT * FROM file_abc123 LIMIT 10 
  步骤3: 列出查询到的10条数据
  步骤4：简要描述这10条数据的主要特征

- 用户问："销售额最高的前5个产品" → 
  步骤1: 调用 ListTablesTool 得到表名
  步骤2: SQL: SELECT * FROM <实际表名> ORDER BY sales DESC LIMIT 5 
  步骤3: 列出查询到的TOP5产品及其销售额
  步骤4: 对查询到的数据进行分析
""".format(
    dialect='MySQL',  # 数据库方言
    top_k=20  # 默认返回结果的最大数量
)


mcp_client = MultiServerMCPClient({
        "plot": plot_mcp_server_config,
    })



async def create_my_agent():
    subagents = []

    # 1. SQL 查询子 agent（核心功能，依赖本地 MySQL）
    sql_assistant = create_agent(
        model=llm1,
        tools=tools,
        system_prompt=system_prompt,
        checkpointer=checkpointer,
    )
    sql_sub_agent = CompiledSubAgent(
        name='sql_assistant',
        description='你是一个专业数据查询助手子Agent，用于查询数据库并给出分析报告。',
        runnable=sql_assistant
    )
    subagents.append(sql_sub_agent)

    # 2. 绘图子 agent（通过 MCP 连接，外部服务可能不可用）
    try:
        plot_tools = await mcp_client.get_tools(server_name="plot")
        plot_assistant = create_agent(
            model=llm1,
            tools=plot_tools,
            system_prompt="你是绘图子Agent，专门用于绘制图片，如柱状图、折线图。"
        )
        plot_sub_agent = CompiledSubAgent(
            name='plot_assistant',
            description='专门用于绘制图片，如柱状图、折线图。',
            runnable=plot_assistant
        )
        subagents.append(plot_sub_agent)
        print("✓ 绘图子Agent已加载")
    except Exception as e:
        print(f"⚠ 绘图子Agent加载失败（跳过）: {e}")

    agent_prompt = """
    你是一个专业的数据查询助手，你需要根据用户的问题，查询数据库并给出分析报告。
    你可以根据skill查询电脑的一些属性。
    """
    if any(s.get("name") == "plot_assistant" for s in subagents):
        agent_prompt += "同时可以根据查询结果绘制图片。\n"

    return create_deep_agent(
        model=llm1,
        subagents=subagents,
        system_prompt=agent_prompt,
        backend=backend,
        skills=[str(SKILLS_ROOT)],
        checkpointer=checkpointer
    )

