@echo off
title K-DOG Install
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
set "status=%errorlevel%"
pause
exit /b %status%
