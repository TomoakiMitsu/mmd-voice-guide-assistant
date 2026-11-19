@echo off
cd /d "%~dp0"
where pythonw >nul 2>nul
if errorlevel 1 (
  python launcher.py
  pause
) else (
  start "" pythonw launcher.py
)
