@echo off
rem zsync 客户端 agent 启动器(最小化窗口运行, 供中央服务器 Web 页面读取本机 zcode 项目)
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo [zsync] 未找到 python, 请先安装 Python 或使用内嵌运行时
  pause
  exit /b 1
)
start "zsync-agent" /min python zsync.py serve --agent %*
