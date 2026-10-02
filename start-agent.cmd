@echo off
rem zsync agent launcher (runs minimized; serves local zcode projects to the central server web UI).
rem Keep this file ASCII-only: cmd parses it with the OEM codepage (e.g. 936/GBK on zh-CN
rem Windows), and any non-ASCII bytes get mis-split into bogus commands.
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo [zsync] python not found. Install Python 3.10+ first, or use the desktop client exe.
  pause
  exit /b 1
)
start "zsync-agent" /min python "%~dp0client\zsync-client.py" agent %*
