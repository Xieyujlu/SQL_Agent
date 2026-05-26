import sys, os
from loguru import logger

# 获得当前项目的绝对路径
root_dir = os.path.dirname(os.path.abspath(__file__))
log_dir = os.path.join(root_dir, "logs") # 存放项目日志目录的绝对路径

if not os.path.exists(log_dir): # 如果目录不存在，则创建目录

    os.makedirs(log_dir)

class MyLogger:
    def __init__(self):
        self.logger = logger # 写日志的对象
        # 清空所有设置
        self.logger.remove()
        # 添加控制台输出的格式，sys.stdout为输出到屏幕
        self.logger.add(sys.stdout, level="DEBUG",
                        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | " # 颜色>时间
                        "{process.name} | " # 进程名
                        "{thread.name} | " # 线程名
                        "<cyan>{module}</cyan>.<cyan>{function}</cyan>" # 模块名.方法名
                        ":<cyan>{line}</cyan> |" # 行号
                        "<level>{level}</level>" # 等级
                        "<level>{message}</level>" # 日志内容
                        )
        # 输出到文件的格式，注释下面的add，则关闭日志写入
        # self.logger.add(log_file_path, level="DEBUG", encoding="utf-8",
        #                 format='{time:YYYY-MM-DD HH:mm:ss} - ' # 时间
        #                 "{process.name} | " # 进程名
        #                 "{thread.name} | " # 线程名
        #                 '{module}.{function}:{line} - {level} - {message}' # 模块名.方法名
        #                 rotation="100 MB", # 日志文件生成的规则
        #                 retention=20, # 保留日志文件的规则
        #                 )
    def get_logger(self):
        return self.logger

log = MyLogger().get_logger()