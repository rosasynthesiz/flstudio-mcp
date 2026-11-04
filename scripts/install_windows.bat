@echo off
REM ============================================================================
REM  flstudio-mcp -- Windows installer
REM    [1] controller script  -> FL Settings\Hardware\FLStudioMCP\
REM    [2] MCP server          -> pip install -e . into .venv
REM    [3] note-bridge script  -> seeds MCP_Apply.pyscript in Piano roll scripts\
REM    [4] loopMIDI port check
REM
REM  FL data folder: FL's registry setting, else the real Documents folder.
REM  Override with FL_SETTINGS=<folder>\FL Studio\Settings.
REM ============================================================================
setlocal enabledelayedexpansion

REM Refuse before modifying any installed controller or Python files.
tasklist /FI "IMAGENAME eq fl-studio-mcp-daemon.exe" 2>nul | find /I "fl-studio-mcp-daemon.exe" >nul
if not errorlevel 1 (
  echo   The daemon is running, and Windows locks its files during the install.
  echo   Close the daemon window ^(or press Ctrl+C in it^), then re-run this script.
  exit /b 1
)
tasklist /FI "IMAGENAME eq fl-studio-mcp.exe" 2>nul | find /I "fl-studio-mcp.exe" >nul
if not errorlevel 1 (
  echo   The MCP server is running inside Claude Desktop or Claude Code, and Windows
  echo   locks its files during the install. Quit Claude Desktop / Claude Code,
  echo   then re-run this script.
  exit /b 1
)

REM All validation and staging happen before installed controller files change.
set "BASE_PY="
for %%V in (3.12 3.11 3.10) do (
  if not defined BASE_PY (
    py -%%V -c "pass" >nul 2>nul && set "BASE_PY=py -%%V"
  )
)
if not defined BASE_PY set "BASE_PY=python"
!BASE_PY! "%~dp0install.py" %*
exit /b !errorlevel!
