@echo off
setlocal
REM Read the selected immutable runtime; FL_SETTINGS must follow custom installs.
set "FLMCP_MANIFEST=%~dp0..\.flmcp-runtime.json"
if not exist "%FLMCP_MANIFEST%" (
  echo Run scripts\install_windows.bat first.
  exit /b 1
)
for /f "usebackq delims=" %%D in (`powershell -NoProfile -Command "(Get-Content -LiteralPath $env:FLMCP_MANIFEST -Raw ^| ConvertFrom-Json).daemon"`) do set "DAEMON=%%D"
for /f "usebackq delims=" %%D in (`powershell -NoProfile -Command "(Get-Content -LiteralPath $env:FLMCP_MANIFEST -Raw ^| ConvertFrom-Json).settings"`) do set "FL_SETTINGS=%%D"
if not defined DAEMON exit /b 1
"%DAEMON%"
exit /b %errorlevel%
