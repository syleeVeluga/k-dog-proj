@echo off
setlocal
cd /d "%~dp0"
set "PYTHONHOME="
set "PYTHONPATH="
if not exist "runtime\python\python.exe" (
  echo K-DOG runtime is missing. Extract the whole ZIP again or reinstall K-DOG.
  pause
  exit /b 1
)
"runtime\python\python.exe" -X utf8 -m app.launcher %*
set "status=%errorlevel%"
if not "%status%"=="0" pause
exit /b %status%
