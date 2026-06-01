
from typing import List, Optional

from langgraph.errors import GraphInterrupt
from langgraph.types import interrupt
from langchain_core.tools import BaseTool
from pydantic import Field, create_model

from src.agent.tools.safe_tool import CircuitBreakerMixin
from src.agent.utils.db_utils import MySQLDatabaseManger
from loguru import logger


class ListTablesTool(CircuitBreakerMixin, BaseTool):

    """列出所有表信息"""
    name: str = "sql_db_list_tables"
    description: str = "列出MySQL数据库中的所有表名及其描述信息"

    # 数据库管理器实例
    db_manger: MySQLDatabaseManger

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def _run(self) -> str:
        self._check_circuit()
        try:
            tables_info = self.db_manger.get_table_with_comments()
            result = f"数据库中共有{len(tables_info)}张表:\n\n"
            for i, table_info in enumerate(tables_info):
                table_name = table_info['table_name']
                table_comment = table_info["table_comment"]

                # 处理空描述的情况
                if not table_comment or table_comment.isspace():
                    description_display = "暂无描述"
                else:
                    description_display = table_comment

                result += f"{i}. {table_name}\n"
                result += f"    描述: {description_display}\n\n"
            self._record_success()
            return result

        except Exception as e:
            logger.exception(e)
            self._record_failure()
            return f"列出表时出错: {str(e)}"
        

    async def _arun(self) -> str:
        """异步执行"""

        return self._run()
    

class TableSchemaTool(CircuitBreakerMixin, BaseTool):

    """列出表结构"""
    name: str = "sql_db_schema"
    description: str = "获取MySQL数据库中指定表的详细模式信息（包含字段注释、列定义、主键、外键等）。输入应为逗号分隔的表名列表，以获取所有表信息。"

    db_manger: MySQLDatabaseManger

    def __init__(self,**kwargs):
        super().__init__(**kwargs)
        self.args_schema = create_model("TableSchemaToolArgs", table_names=(Optional[str],Field(description="表名列表，以逗号分隔,例如：users,order")))

    def _run(self, table_names: Optional[str] = None) -> str:
        """返回表结构"""
        self._check_circuit()
        try:
            table_list = None
            if table_names:
                table_list = [name.strip() for name in table_names.split(",") if name.strip()]
                schema_info = self.db_manger.get_table_schema(table_list)
            self._record_success()
            return schema_info if schema_info else "未找到匹配的表"

        except Exception as e:
            logger.exception(e)
            self._record_failure()
            return f"获取表结构时出错: {str(e)}"
    
    async def _arun(self, table_names: Optional[str] = None) -> str:
        """异步执行"""
        return self._run(table_names)

class SQLQueryTool(CircuitBreakerMixin, BaseTool):
    """执行SQL查询"""
    name: str = "sql_db_query"
    description: str = "在MySQL数据库中执行SQL查询语句并返回结果。输入应为有效的SQL SELECT查询语句。"

    db_manger: MySQLDatabaseManger

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.args_schema = create_model(
            "SQLQueryToolArgs",
            query=(str, Field(description="有效的SQL SELECT查询语句")),
        )

    def _request_hitl(self, query: str, result: str) -> str:
        """请求人工审核（SQL SELECT 幂等，恢复后重新执行是安全的）。"""
        feedback = interrupt({
            "query": query,
            "result": result,
            "options": ["准确", "错误", "其他建议"],
        })
        decision = feedback.get("decision", "准确")
        message = feedback.get("message", "")

        if decision == "错误":
            return (
                f"SQL查询结果:\n{result}\n\n"
                f"用户反馈（错误）: {message}\n"
                f"请根据反馈修正SQL并重新查询。"
            )
        elif decision == "其他建议":
            return (
                f"SQL查询结果:\n{result}\n\n"
                f"用户建议: {message}\n"
                f"请根据建议调整查询或分析。"
            )
        else:
            return f"SQL查询结果（已通过人工审核）:\n{result}"

    def _run(self, query: str) -> str:
        """执行SQL查询语句"""
        self._check_circuit()
        try:
            result = self.db_manger.execute_query(query)
            self._record_success()
            return self._request_hitl(query, result)
        except GraphInterrupt:
            raise
        except Exception as e:
            self._record_failure()
            return f"执行SQL查询语句时出错: {str(e)}"

    async def _arun(self, query: str) -> str:
        """异步执行SQL查询"""
        return self._run(query)


class SQLQueryCheckerTool(CircuitBreakerMixin, BaseTool):
    """检查SQL查询语法"""
    name: str = "sql_db_query_checker"
    description: str = "检查SQL查询语句的语法是否正确，提供验证反馈。输入应为要检查的SQL查询。"

    db_manger: MySQLDatabaseManger

    def __init__(self,**kwargs):
        super().__init__(**kwargs)
        self.args_schema = create_model("SQLQueryCheckerToolArgs", query=(str,Field(description="需要进行检查的SQL语句")))

    def _run(self, query: str) -> str:
        """检查SQL查询语句"""
        self._check_circuit()
        try:
            result = self.db_manger.check_query(query)
            self._record_success()
            return result
        except Exception as e:
            self._record_failure()
            return f"检查SQL查询语句时出错: {str(e)}"
        
    async def _arun(self, query: str) -> str:
        """异步执行"""
        return self._run(query)


    
if __name__ == "__main__":

    DB_CONFIG = {
        "host": "localhost",
        "port": 3306,
        "user": "root",
        "password": os.getenv("MYSQL_PASSWORD", ""),
        "database": "stock"
    }
    
    manager = MySQLDatabaseManger(connection_string=f"mysql+pymysql://{DB_CONFIG['user']}:{DB_CONFIG['password']}@{DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['database']}")
    # tool = ListTablesTool(db_manger=manager) # 测试第一个工具
    # print(tool.invoke({}))
    tool = TableSchemaTool(db_manger=manager) # 测试第二个工具
    print(tool.invoke({'table_names':'row_table_df'}))
    # tool = SQLQueryTool(db_manger=manager) # 测试第三个工具
    # print(tool.invoke({'query':'select * from row_table_df limit 10'}))
    # tool = SQLQueryCheckerTool(db_manger=manager) # 测试第四个工具
    # print(tool.invoke({'query':'select * from row_table_df limit 10 a'}))