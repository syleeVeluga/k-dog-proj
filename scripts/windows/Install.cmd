@echo off
title K-DOG Install
setlocal
cd /d "%~dp0"
set "PYTHONHOME="
set "PYTHONPATH="
if not exist "runtime\python\python.exe" (
  echo Extract all files from the ZIP first, then run Install.cmd in the extracted folder.
  pause
  exit /b 1
)
"runtime\python\python.exe" -X utf8 "installer\kdog_install.py" %*
set "status=%errorlevel%"
pause
exit /b %status%
