import keyword
import json
from textwrap import indent
from typing import List, Optional
from unittest import result
from sqlalchemy.engine import Engine
from sqlalchemy.sql.expression import text
from sqlalchemy.inspection import inspect
from sqlalchemy import column, create_engine
from loguru import logger

class MySQLDatabaseManger:
    """MySQL数据库管理器，负责数据库连接和基本操作"""
    def __init__(self, connection_string: str):
        """
        初始化MySQL数据库连接

        Args:
            connection_string: 连接数据库的字符串，格式为:
                mysql+pymysql://username:password@host:port/database
        """
        self.engine = create_engine(connection_string)

    def get_table_names(self) -> List[str]:
        """获取数据库中的所有表名"""
        try:
            # 创建一个inspector（数据库映射）对象
            inspector = inspect(self.engine)
            return inspector.get_table_names()
        except Exception as e:
            logger.exception("获取表名时发生错误")
            raise ValueError(f"获取表名失败: {str(e)}")
        


    def get_table_with_comments(self) -> List[dict]:
        """
        获取数据库中的所有表的名称和描述信息

        Returns:
        List[dict]:一个字典列表，每个字典包含'table_name'和'table_comment'键。
        """
        try:
            # 构建查询语句，从INFORMATION_SCHEMA.TABLES 中获取表名和注释
            query = text(
                """
                SELECT table_name, table_comment 
                FROM INFORMATION_SCHEMA.TABLES 
                WHERE table_schema = DATABASE()
                AND TABLE_TYPE = 'BASE TABLE'
                ORDER BY table_name
                """
            )

            with self.engine.connect() as connection:
                result = connection.execute(query)
                # 将结果转换为字典列表
                tables_info = [{'table_name': row[0], 'table_comment': row[1]} for row in result]
                return tables_info
        except Exception as e:
            logger.exception("获取表信息时发生错误")
            raise ValueError(f"获取表名及描述信息失败: {str(e)}")

    def get_table_schema(self, table_names: Optional[List[str]] = None) -> str:
        """
        获取指定表的模式信息（包含字段注释）

        Args：
            table_names: 表名列表，默认为None，表示获取所有表的模式信息
            
        """
        try:
            inspector = inspect(self.engine)
            schema_info = []
            tables_to_process = table_names if table_names else inspector.get_table_names()

            for table_name in tables_to_process:
                # 获取表结构信息
                column_info = inspector.get_columns(table_name)
                # 使用get_pk_constraint 替代已弃用的 get_primary_keys 方法
                pk_constraint = inspector.get_pk_constraint(table_name)
                primary_keys = pk_constraint['constrained_columns'] if pk_constraint else []
                foregin_keys = inspector.get_foreign_keys(table_name)
                indexes = inspector.get_indexes(table_name)

                # 构建表模式描述
                table_schma = f"表名： {table_name}\n"
                table_schma += "列信息：\n"

                for column in column_info:
                    # 检查该列是否在主键列表中
                    pk_indicator = " (主键)" if column['name'] in primary_keys else ""
                    # 获取字段注释，如果不存在则显示“无注释”
                    comment = column.get('comment', '无注释')
                    table_schma += f"  列名：{column['name']}{pk_indicator}, 类型：{column['type']}, 注释：{comment}\n"
                 

                    # 处理外键信息

                if foregin_keys:
                    table_schma += "外键约束：\n"
                    for fk in foregin_keys:
                        table_schma += f"  列名：{fk['name']}, 引用表：{fk['referred_table']}, 引用列：{fk['referred_columns']}\n"

                    

                    # 处理索引信息

                if indexes:
                    table_schma += "索引：\n"
                    for idx in indexes:
                        table_schma += f"  索引名：{idx['name']}, 列名：{', '.join(idx['column_names'])}\n"

                schema_info.append(table_schma)
            return "\n".join(schema_info) if schema_info else "未找到匹配的表"

        except Exception as e:
            logger.exception("获取表模式信息时发生错误")
            raise ValueError(f"获取表模式信息失败: {str(e)}")
            

    def execute_query(self, query: str) -> str:
        """
        执行SQL查询并返回结果

        Args：
            query：SQL查询语句
        """
        # 安全检查：防止数据修改操作
        forbidden_keywords = ['insert', 'update', 'delete', 'drop', 'alter', 'create', 'grant', 'truncate']
        query_lower = query.lower().strip()

        # 检查是否已SELECT开头（允许子查询等复杂情况）
        if not query_lower.startswith(('select', 'with')) and any(
            keyword in query_lower for keyword in forbidden_keywords
        ):
            raise ValueError("只允许执行SELECT查询和WITH查询")
        
        try:
            with self.engine.connect() as connection:
                result = connection.execute(text(query))

                # 获取列名
                columns = result.keys()
                # 获取数据(限制返回行数防止内存溢出)
                rows = result.fetchmany(100)

                if not rows:

                    return "查询结果为空"
                
                # 格式化结果
                result_data = []
                for row in rows:
                    row_dict = {}
                    for i, col in enumerate(columns):
                        # 处理无法序列化的数据类型
                        try:
                            # 尝试JSON序列化来检测是否可序列化
                            if row[i] is not None:
                                json.dumps(row[i])
                            row_dict[col] = row[i]
                        except (TypeError, ValueError):
                            row_dict[col] = str(row[i])
                    result_data.append(row_dict)

                return json.dumps(result_data, ensure_ascii=False, indent=2)
        
        except Exception as e:
            logger.exception("执行查询时发生错误")
            return f"执行查询失败: {str(e)}"

    def check_query(self, query: str) -> str:
        """
        验证SQL查询语法是否正确

        Args：
                uery：要验证的SQL查询
        """
        # 基本语法检查
        if not query or not query.strip():
            return "查询不能为空"
            
        # 检查是否已SELECT开头（允许子查询等复杂情况）
        query_lower = query.lower().strip()
        if not query_lower.startswith(('select', 'with')) :
            return "只允许执行SELECT查询和WITH查询"
            
        # 尝试解析查询（不实际执行）
        # try:
        #     with self.engine.connect() as connection:
        #         # 使用SQLAlchemy的text()来解析但不执行
        #         parsed_query = text(query)
        #         # 尝试编译查询来检查语法
        #         compiled = parsed_query.compile(compile_kwargs={"literal_binds": True})
        #         return "SQL查询语法看起来正确"

        try:
            with self.engine.connect() as connection:
                # 根据数据库方言构建EXPLAIN查询
                # 这里以MySQL为例，其他数据库可能有不同的语法
                if self.engine.dialect.name == 'mysql':
                    explain_query = text(f"EXPLAIN {query}")
                else:
                    # 对于其他数据库（如SQLite），它们的EXPLAIN语法类似
                    explain_query = text(f"EXPLAIN {query}")

                # 执行EXPLAIN查询，如果查询无效，此处会抛出异常

                connection.execute(explain_query)
                return "SQL查询语法正确（已通过数据库EXPLAIN验证"

        except Exception as e:

            logger.exception("验证查询时发生错误")

            return f"SQL语法错误: {str(e)}"





if __name__ == "__main__":
    # 配置数据库连接信息
    DB_CONFIG = {
        "host": "localhost",
        "port": 3306,
        "user": "root",
        "password": "12345678",
        "database": "stock"
    }

    manager = MySQLDatabaseManger(connection_string=f"mysql+pymysql://{DB_CONFIG['user']}:{DB_CONFIG['password']}@{DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['database']}")

    # print(manager.get_table_names())
    # print(manager.get_table_with_comments())
    # print(manager.get_table_schema())
    # print(manager.execute_query("select * from row_table_df limit 10"))
