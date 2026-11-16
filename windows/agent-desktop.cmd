@echo off
rem agent-desktop for the G14: runs agent-desktop.ps1 next to this file on Windows PowerShell 5.1 and returns its exit code.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0agent-desktop.ps1" %*
exit /b %ERRORLEVEL%
