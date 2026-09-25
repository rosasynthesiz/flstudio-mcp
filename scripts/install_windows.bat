@echo off
REM ============================================================================
REM  flstudio-mcp -- Windows installer
REM    [1] controller script  -> FL Settings\Hardware\FLStudioMCP\
REM    [2] MCP server          -> pip install -e .
REM    [3] note-bridge script  -> seeds MCP_Apply.pyscript in Piano roll scripts\
REM    [4] loopMIDI port check
REM
REM  FL user-data location: read from FL's own registry record
REM  (HKCU\Software\Image-Line\Shared\Paths "Shared data"), which follows a
REM  Documents folder redirected to OneDrive or renamed by the OS language.
REM  Falls back to %USERPROFILE%\Documents\Image-Line\FL Studio\Settings.
REM  To force a location, set FL_SETTINGS before running this script.
REM ============================================================================
setlocal enabledelayedexpansion

if not defined FL_SETTINGS (
  set "FL_DATA="
  for /f "tokens=3,*" %%A in ('reg query "HKCU\Software\Image-Line\Shared\Paths" /v "Shared data" 2^>nul ^| findstr /c:"REG_SZ"') do set "FL_DATA=%%B"
  if not defined FL_DATA set "FL_DATA=%USERPROFILE%\Documents\Image-Line"
  if "!FL_DATA:~-1!"=="\" set "FL_DATA=!FL_DATA:~0,-1!"
  set "FL_SETTINGS=!FL_DATA!\FL Studio\Settings"
)
set "HW_TARGET=%FL_SETTINGS%\Hardware\FLStudioMCP"
set "SCRIPT_DIR=%~dp0"
set "REPO_ROOT=%SCRIPT_DIR%.."

echo.
echo [1/4] Installing FL Studio controller script...
if not exist "%FL_SETTINGS%\Hardware" (
  echo   FL Studio Settings\Hardware folder not found at:
  echo     %FL_SETTINGS%\Hardware
  echo   Open FL Studio at least once, then re-run this script.
  exit /b 1
)
if not exist "%HW_TARGET%" mkdir "%HW_TARGET%"
copy /Y "%REPO_ROOT%\fl_controller\FLStudioMCP\device_FLStudioMCP.py" "%HW_TARGET%\" >nul
if errorlevel 1 ( echo   Copy failed. Aborting. & exit /b 1 )
echo   Installed to %HW_TARGET%

echo.
echo [2/4] Installing the MCP server (editable)...
where python >nul 2>nul
if errorlevel 1 ( echo   Python not found on PATH. Install Python 3.12 and re-run. & exit /b 1 )
pushd "%REPO_ROOT%"
python -m pip install --upgrade pip >nul
python -m pip install -e .
if errorlevel 1 ( echo   pip install failed. See output above. & popd & exit /b 1 )
popd

echo.
echo [3/4] Seeding the note-bridge pyscript (MCP_Apply)...
python -c "import os, fl_studio_mcp.pyscript_gen as g; os.makedirs(g.PIANO_ROLL_SCRIPTS_DIR, exist_ok=True); print('   seeded ' + g.write_apply_script([], mode='append'))"
if errorlevel 1 echo   Note: could not pre-seed MCP_Apply (FL Piano roll scripts folder missing?). Non-fatal -- the daemon writes it on the first note-write.

echo.
echo [4/4] Checking loopMIDI ports...
python -c "import mido; names=set(mido.get_output_names())|set(mido.get_input_names()); req=('FLStudioMCP RX','FLStudioMCP TX'); missing=[n for n in req if not any(n.lower() in x.lower() for x in names)]; print('   All required ports present.') if not missing else print('   MISSING ports: %s -- create them in loopMIDI.' % missing)"

echo.
echo ============================================================================
echo  Done. Next steps (see README for detail):
echo ============================================================================
echo   1. loopMIDI: if a port was MISSING above, create EXACTLY these two and re-run:
echo        "FLStudioMCP RX"   and   "FLStudioMCP TX"
echo        ( https://www.tobias-erichsen.de/software/loopmidi.html )
echo   2. FL Studio ^> Options ^> MIDI Settings:
echo        Input  ^> "FLStudioMCP RX": Enable, Controller type = FLStudioMCP, Port = 42
echo        Output ^> "FLStudioMCP TX": Enable, Port = 42  (the SAME number)
echo        View ^> Script output should show  [FLStudioMCP] Ready
echo   3. Start the bridge daemon and keep it running:
echo        fl-studio-mcp-daemon
echo   4. Register with Claude Desktop  (%%APPDATA%%\Claude\claude_desktop_config.json):
echo        "fl-studio": { "command": "fl-studio-mcp", "env": { "FLSTUDIO_MCP_TRANSPORT": "tcp" } }
echo   5. Each session: open the Piano roll, and from its Scripting menu run "MCP_Apply"
echo        once (this arms note-writing). Then ask Claude to call fl_ping.
echo.
echo  Optional audio features:   pip install -e ".[audio]"      (tempo/key + melody)
echo                             pip install -e ".[audio,audio-accurate]"  (+ CREPE)
echo.
endlocal
