import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# 加载 .env 文件（兼容直接导入 multi_agent 模块的场景）
load_dotenv(Path(__file__).resolve().parent.parent / "agent" / ".env")

from deepagents import CompiledSubAgent, create_deep_agent
from langchain.agents import create_agent
from typing import List, Iterator

from langchain_openai import ChatOpenAI
from langchain_core.tools import BaseTool
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatResult, ChatGenerationChunk
from langchain_core.callbacks import CallbackManagerForLLMRun
from loguru import logger
from pydantic import PrivateAttr
import aiosqlite

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from src.multi_agent.mcp_tool_config import plot_mcp_server_config
from src.agent.tools.tool import ListTablesTool, TableSchemaTool, SQLQueryTool, SQLQueryCheckerTool
from src.agent.tools.memory_tools import (
    GetUserProfileTool, SetUserProfileTool, SaveEventTool, SearchEventTool,
    current_user_id,
)
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

# 长期记忆工具（主 Agent 使用）
memory_tools = [
    GetUserProfileTool(),
    SetUserProfileTool(),
    SaveEventTool(),
    SearchEventTool(),
]

def get_python_executable():
    """获取当前Python解释器的完整路径"""
    python_exe = sys.executable
    print(f"当前Python解释器: {python_exe}")
    return python_exe

# 用文件相对路径，兼容本地开发 (cwd=项目根) 和 Docker (cwd=/app)
SKILLS_ROOT = Path(__file__).resolve().parent.parent / "teaching_skills"
workspace_dir = Path("llm/").absolute()


_db_path = os.path.join(os.path.dirname(__file__), "..", "..", "data", "checkpoints.db")

_checkpointer: AsyncSqliteSaver | None = None


async def _get_checkpointer() -> AsyncSqliteSaver:
    """获取全局单例 AsyncSqliteSaver（异步初始化）。"""
    global _checkpointer
    if _checkpointer is None:
        _conn = await aiosqlite.connect(_db_path)
        _checkpointer = AsyncSqliteSaver(_conn)
        await _checkpointer.setup()
    return _checkpointer

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


class _FallbackChatModel(BaseChatModel):
    """ChatModel 包装器：主模型失败时 try-except 切换到备用模型。

    所有模型自省（bind_tools、profile、model_name 等）委托给主模型，
    仅对 _generate / _stream 等实际调用方法做 try-except 降级。
    """

    _primary: BaseChatModel = PrivateAttr()
    _fallback: BaseChatModel = PrivateAttr()

    def __init__(self, primary: BaseChatModel, fallback: BaseChatModel):
        super().__init__()
        self._primary = primary
        self._fallback = fallback

    # ── 自省属性委托给主模型 ──────────────────────────────────
    def __getattr__(self, name: str):
        # 先让 Pydantic 处理 PrivateAttr（_primary / _fallback）和自身字段
        try:
            return super().__getattr__(name)
        except AttributeError:
            return getattr(self._primary, name)

    @property
    def _llm_type(self) -> str:
        return self._primary._llm_type

    # ── bind_tools / bind：必须显式覆盖，否则 BaseChatModel 的
    #     NotImplemented 实现会通过 MRO 匹配，跳过 __getattr__ ───

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        result = self._primary.bind_tools(tools, tool_choice=tool_choice, **kwargs)
        result.bound = self  # 换绑到 self，确保调用链路经过 try-except
        return result

    def bind(self, **kwargs):
        result = self._primary.bind(**kwargs)
        result.bound = self
        return result

    # ── 实际调用方法：try primary → except fallback ──────────

    def _generate(
        self, messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs,
    ) -> ChatResult:
        try:
            return self._primary._generate(
                messages, stop=stop, run_manager=run_manager, **kwargs
            )
        except Exception:
            logger.warning(f"主模型 qwen3.5-plus 调用失败，切换到备用模型 qwen-turbo")
            return self._fallback._generate(
                messages, stop=stop, run_manager=run_manager, **kwargs
            )

    async def _agenerate(
        self, messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs,
    ) -> ChatResult:
        try:
            return await self._primary._agenerate(
                messages, stop=stop, run_manager=run_manager, **kwargs
            )
        except Exception:
            logger.warning(f"主模型 qwen3.5-plus 调用失败，切换到备用模型 qwen-turbo")
            return await self._fallback._agenerate(
                messages, stop=stop, run_manager=run_manager, **kwargs
            )

    def _stream(
        self, messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs,
    ) -> Iterator[ChatGenerationChunk]:
        try:
            yield from self._primary._stream(
                messages, stop=stop, run_manager=run_manager, **kwargs
            )
        except Exception:
            logger.warning(f"主模型 qwen3.5-plus 调用失败，切换到备用模型 qwen-turbo")
            yield from self._fallback._stream(
                messages, stop=stop, run_manager=run_manager, **kwargs
            )

    async def _astream(
        self, messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs,
    ):
        try:
            async for chunk in self._primary._astream(
                messages, stop=stop, run_manager=run_manager, **kwargs
            ):
                yield chunk
        except Exception:
            logger.warning(f"主模型 qwen3.5-plus 调用失败，切换到备用模型 qwen-turbo")
            async for chunk in self._fallback._astream(
                messages, stop=stop, run_manager=run_manager, **kwargs
            ):
                yield chunk


_common_kwargs = dict(
    api_key=os.getenv("DASHSCOPE_API_KEY"),
    base_url=os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
)

llm_primary = ChatOpenAI(
    **_common_kwargs,
    model="qwen3.5-plus",
    max_retries=3,
    timeout=60,
)

llm_fallback = ChatOpenAI(
    **_common_kwargs,
    model="qwen-turbo",
    max_retries=2,
    timeout=30,
)

llm1 = _FallbackChatModel(primary=llm_primary, fallback=llm_fallback)

system_prompt = """
你是一个专业的数据分析师，专门帮助用户查询和分析数据库。

你有以下工具可以使用：
- ListTablesTool: 列出数据库中的所有表
- TableSchemaTool: 查看特定表的结构和示例数据
- SQLQueryTool: 执行 SQL 查询并返回结果
- SQLQueryCheckerTool: 在执行前检查 SQL 查询的正确性

**执行步骤：**
1. **重要**: 使用 ListTablesTool 查看数据库中实际的表名（绝对不要猜测表名或使用 "table" 作为表名）
2. 根据表名推断与用户问题相关的表，使用 TableSchemaTool 只查询相关表的结构和列名（必须传入 table_names 参数，禁止不传参查全部表）
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
- **TableSchemaTool 只能查询与用户问题相关的表（必须传 table_names 参数），绝对不要一次查全部表结构**
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
        checkpointer=await _get_checkpointer(),
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

    **长期记忆能力：**
    你有以下记忆工具可以使用：
    - get_user_profile: 读取用户已存储的个人信息与偏好（称呼、领域、输出格式偏好等）
    - set_user_profile: 存储用户个人信息/偏好。当用户明确告知个人信息时主动记录
    - save_event: 记录重大事件（查询失败原因、用户纠正、重要反馈）供未来参考
    - search_event: 搜索历史事件，在遇到问题时先查过往经验

    **记忆使用策略：**
    1. 每次对话开始，先用 get_user_profile 了解用户偏好
    2. 用户告知个人信息（如称呼、职业、偏好）时，用 set_user_profile 记录
    3. SQL 查询失败或用户纠正错误时，用 save_event 记录事件（包含具体错误原因）
    4. 遇到与历史类似的问题时，用 search_event 搜索过往经验
    """
    if any(s.get("name") == "plot_assistant" for s in subagents):
        agent_prompt += "同时可以根据查询结果绘制图片。\n"

    return create_deep_agent(
        model=llm1,
        subagents=subagents,
        tools=memory_tools,
        system_prompt=agent_prompt,
        backend=backend,
        skills=[str(SKILLS_ROOT)],
        checkpointer=await _get_checkpointer()
    )

