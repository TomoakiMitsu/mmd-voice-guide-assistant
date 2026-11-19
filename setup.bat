@echo off
cd /d "%~dp0"
where pythonw >nul 2>nul
if errorlevel 1 (
  python setup_wizard.py
  pause
) else (
  start "" pythonw setup_wizard.py
)
