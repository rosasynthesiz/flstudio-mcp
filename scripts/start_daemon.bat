@echo off
setlocal
REM Read the selected immutable runtime; FL_SETTINGS must follow custom installs.
set "FLMCP_MANIFEST=%~dp0..\.flmcp-runtime.json"
if not exist "%FLMCP_MANIFEST%" (
  echo Run scripts\install_windows.bat first.
  exit /b 1
)
set "DAEMON="
set "FL_SETTINGS="
for /f "usebackq delims=" %%D in (`powershell -NoProfile -Command "(ConvertFrom-Json -InputObject ([IO.File]::ReadAllText($env:FLMCP_MANIFEST))).daemon"`) do set "DAEMON=%%D"
for /f "usebackq delims=" %%D in (`powershell -NoProfile -Command "(ConvertFrom-Json -InputObject ([IO.File]::ReadAllText($env:FLMCP_MANIFEST))).settings"`) do set "FL_SETTINGS=%%D"
if not defined DAEMON exit /b 1
if not defined FL_SETTINGS exit /b 1
"%DAEMON%"
exit /b %errorlevel%
