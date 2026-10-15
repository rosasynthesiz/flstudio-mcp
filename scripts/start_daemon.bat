@echo off
REM Start the flstudio-mcp bridge daemon in this window. Keep it open while you
REM use FL Studio with Claude; close the window or press Ctrl+C to stop it.
title flstudio-mcp daemon
set "DAEMON=%~dp0..\.venv\Scripts\fl-studio-mcp-daemon.exe"
if not exist "%DAEMON%" (
  echo Daemon not found at:
  echo   %DAEMON%
  echo Run scripts\install_windows.bat first.
  pause
  exit /b 1
)
"%DAEMON%"
echo.
echo The daemon has stopped.
pause
