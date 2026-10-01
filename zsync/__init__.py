"""zsync - zcode 开发环境备份与同步工具。

模块:
  zclayout  zcode 数据目录布局探测、project_id / memory slug 推导
  dbio      会话数据库按项目导出 / 导入(含路径重映射)
  bundle    归档构建 / 恢复
  jobs      后台任务管理
  watcher   实时备份轮询
  server    HTTP 服务 + REST API + Web GUI
  client    远程 push/pull
"""

__version__ = "0.1.0"
