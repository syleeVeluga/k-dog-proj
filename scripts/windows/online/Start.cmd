@echo off
title K-DOG
setlocal
cd /d "%~dp0backend"
set "PYTHONHOME="
set "PYTHONPATH="
if not exist ".venv\Scripts\python.exe" (
  echo K-DOG is not installed yet. Run Install.cmd first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -X utf8 -m app.launcher %*
set "status=%errorlevel%"
if not "%status%"=="0" pause
exit /b %status%
