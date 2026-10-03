@echo off
rem zsync agent launcher (runs minimized; serves local zcode projects to the central server web UI).
rem Keep this file ASCII-only: cmd parses it with the OEM codepage (e.g. 936/GBK on zh-CN
rem Windows), and any non-ASCII bytes get mis-split into bogus commands.
cd /d "%~dp0"
rem Prefer a bundled single-file client exe (tool.zip?bin=... drops one here) - no Python needed.
set "ZEXE="
for %%F in ("%~dp0zsync-client*.exe") do if not defined ZEXE set "ZEXE=%%~fF"
if defined ZEXE (
  start "zsync-agent" /min "%ZEXE%" agent %*
  exit /b 0
)
where python >nul 2>nul
if errorlevel 1 (
  echo [zsync] python not found. Install Python 3.10+ first, download the client exe from the server web UI, or get tool.zip?bin=win.
  pause
  exit /b 1
)
start "zsync-agent" /min python "%~dp0client\zsync-client.py" agent %*
