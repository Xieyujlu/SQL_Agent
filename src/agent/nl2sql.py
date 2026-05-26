import os
import sys
from langchain.agents import create_agent
from typing import List
from langchain_openai import ChatOpenAI
from pymysql import connect
from langchain_core.tools import BaseTool
from src.agent.tools.tool import ListTablesTool, TableSchemaTool, SQLQueryTool, SQLQueryCheckerTool
from src.agent.utils.db_utils import MySQLDatabaseManger



def get_tools(host: str, port: int, user: str, password: str, database: str) -> List[BaseTool]:

    connection_string = f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}"
    manger = MySQLDatabaseManger(connection_string)
    return [
        ListTablesTool(db_manger=manger),
        TableSchemaTool(db_manger=manger),
        SQLQueryTool(db_manger=manger),
        SQLQueryCheckerTool(db_manger=manger)
    ]

tools = get_tools(host="localhost", port='3306', user="root", password="12345678", database="stock")

llm = ChatOpenAI(
    api_key=os.getenv("DASHSCOPE_API_KEY"),
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    model="qwen-turbo",  # 此处以qwen-plus为例，您可按需更换模型名称。模型列表：https://help.aliyun.com/zh/model-studio/getting-started/models
    # other params...
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
    dialect = 'MySQL', # 数据库方言
    top_k = 20   # 默认返回结果的最大数量
)

agent = create_agent(
    llm,
    tools=tools,
    system_prompt=system_prompt
)

# question = {"input": "数据库有哪些表"}  # 关键：使用 input 字段
# result = agent.invoke(question)
# print(result)
for step in agent.stream(
    input={'messages': [{'role': 'user', 'content': '数据库有哪些表，每张表有多少条数据？'}]},
    stream_mode="values"
):
    step['messages'][-1].pretty_print()