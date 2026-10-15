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

echo.
echo  Before you start, make sure that:
echo    - FL Studio has been opened at least once
echo    - loopMIDI is running with two ports named exactly:
echo        FLStudioMCP RX
echo        FLStudioMCP TX
echo      (type the name in "New port-name" and click +; default names won't work)
echo  Step 4 checks the ports and tells you what is missing.

REM FL's own user data folder setting.
if not defined FL_SETTINGS (
  for /f "usebackq delims=" %%D in (`powershell -NoProfile -Command "$p = (Get-ItemProperty 'HKCU:\Software\Image-Line\Shared\Paths' -ErrorAction SilentlyContinue).'Shared data'; if ($p) { $s = Join-Path $p 'FL Studio\Settings'; if (Test-Path $s) { $s } }"`) do set "FL_SETTINGS=%%D"
)
REM Real Documents folder (OneDrive, localized names).
set "DOCS="
for /f "usebackq delims=" %%D in (`powershell -NoProfile -Command "[Environment]::GetFolderPath('MyDocuments')"`) do set "DOCS=%%D"
if not defined DOCS set "DOCS=%USERPROFILE%\Documents"
if not defined FL_SETTINGS set "FL_SETTINGS=%DOCS%\Image-Line\FL Studio\Settings"
echo.
echo  FL Studio user data: %FL_SETTINGS%
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
echo [2/4] Installing the MCP server into a virtual environment (.venv)...
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
REM python-rtmidi has Windows wheels only up to 3.12; newer Pythons need a C compiler
REM (a MinGW build crashed on import). A repo-local venv also fixes the command paths.
set "BASE_PY="
for %%V in (3.12 3.11 3.10) do (
  if not defined BASE_PY (
    py -%%V -c "pass" >nul 2>nul && set "BASE_PY=py -%%V"
  )
)
if not defined BASE_PY (
  where python >nul 2>nul || ( echo   Python not found. Install Python 3.12 and re-run. & exit /b 1 )
  set "BASE_PY=python"
  echo   WARNING: Python 3.10-3.12 not found; using the default python. If MIDI
  echo   fails to load, install Python 3.12 from python.org and re-run.
)
echo   Using: !BASE_PY!
for %%I in ("%REPO_ROOT%\.venv") do set "VENV=%%~fI"
if not exist "%VENV%\Scripts\python.exe" (
  !BASE_PY! -m venv "%VENV%"
  if errorlevel 1 ( echo   Could not create the virtual environment. & exit /b 1 )
)
set "PY=%VENV%\Scripts\python.exe"
pushd "%REPO_ROOT%"
"%PY%" -m pip install --upgrade pip >nul
"%PY%" -m pip install -e .
if errorlevel 1 ( echo   pip install failed. See output above. & popd & exit /b 1 )
popd
"%PY%" -c "import rtmidi" >nul 2>nul
if errorlevel 1 echo   WARNING: the MIDI library (python-rtmidi) fails to load. Install Python 3.12, delete .venv and re-run.

REM Optional audio features, two questions. Preset FLMCP_EXTRAS to skip them:
REM all, none, or any of: audio accurate chords.
echo.
set "WANT_AUDIO=" & set "WANT_ACCURATE=" & set "WANT_CHORDS="
if not defined FLMCP_EXTRAS (
  echo   Optional, you can re-run this installer later to add these.
  echo   1/2 Audio analysis, about 100 MB, no AI models:
  echo       tempo and key detection, drums to MIDI, melody to MIDI ^(light^),
  echo       reference match.
  choice /C YN /N /M "   Install audio analysis? [Y/N] "
  if !errorlevel! EQU 1 set "FLMCP_EXTRAS=audio"
  echo   2/2 AI audio to MIDI, about 650 MB, downloads AI models:
  echo       accurate melody to MIDI ^(CREPE^), chords to MIDI ^(Basic Pitch^).
  choice /C YN /N /M "   Install AI audio to MIDI? [Y/N] "
  if !errorlevel! EQU 1 set "FLMCP_EXTRAS=!FLMCP_EXTRAS! accurate chords"
  if not defined FLMCP_EXTRAS set "FLMCP_EXTRAS=none"
)
echo !FLMCP_EXTRAS! | find /I "all" >nul && set "FLMCP_EXTRAS=audio accurate chords"
echo !FLMCP_EXTRAS! | find /I "audio" >nul && set "WANT_AUDIO=1"
echo !FLMCP_EXTRAS! | find /I "accurate" >nul && set "WANT_ACCURATE=1"
echo !FLMCP_EXTRAS! | find /I "chords" >nul && set "WANT_CHORDS=1"
if defined WANT_ACCURATE set "WANT_AUDIO=1"
set "EXTRAS="
if defined WANT_AUDIO set "EXTRAS=audio"
if defined WANT_ACCURATE set "EXTRAS=!EXTRAS!,audio-accurate"
if defined WANT_CHORDS (
  if defined EXTRAS ( set "EXTRAS=!EXTRAS!,audio-chords" ) else ( set "EXTRAS=audio-chords" )
)
if defined EXTRAS (
  echo   Installing extras: !EXTRAS!
  pushd "%REPO_ROOT%"
  "%PY%" -m pip install -e ".[!EXTRAS!]"
  if errorlevel 1 echo   WARNING: installing the extras failed. See output above.
  popd
)
if defined WANT_CHORDS (
  REM Skip Basic Pitch's TensorFlow pin; we run its ONNX model.
  "%PY%" -m pip install --no-deps "basic-pitch==0.4.0"
  "%PY%" -c "from fl_studio_mcp.tools.audio import chords_available as c; print('   Chords to MIDI: ready' if c() else '   WARNING: chords to MIDI is not working, see output above')"
)
if not defined EXTRAS echo   No optional audio features installed.

set "DAEMON_CMD=%VENV%\Scripts\fl-studio-mcp-daemon.exe"
set "SERVER_CMD=%VENV%\Scripts\fl-studio-mcp.exe"

echo.
echo [3/4] Seeding the note-bridge pyscript (MCP_Apply)...
"%PY%" -c "import os, fl_studio_mcp.pyscript_gen as g; os.makedirs(g.PIANO_ROLL_SCRIPTS_DIR, exist_ok=True); print('   seeded ' + g.write_apply_script([], mode='append'))"
if errorlevel 1 echo   Note: could not pre-seed MCP_Apply (FL Piano roll scripts folder missing?). Non-fatal -- the daemon writes it on the first note-write.

echo.
echo [4/4] Checking loopMIDI ports...
"%PY%" -c "import mido; names=set(mido.get_output_names())|set(mido.get_input_names()); req=('FLStudioMCP RX','FLStudioMCP TX'); missing=[n for n in req if not any(n.lower() in x.lower() for x in names)]; print('   All required ports present.') if not missing else print('   MISSING ports: ' + ', '.join(missing) + chr(10) + '   Ports found now: ' + (', '.join(sorted(names)) or 'none') + chr(10) + '   Fix: open loopMIDI, remove ports with default names (loopMIDI Port ...),' + chr(10) + '   then type FLStudioMCP RX in New port-name and click +, and the same for FLStudioMCP TX.')"

echo.
echo ============================================================================
echo  Done. Next steps (see README for detail):
echo ============================================================================
echo   1. loopMIDI: if a port was MISSING above, create EXACTLY these two and re-run:
echo        "FLStudioMCP RX"   and   "FLStudioMCP TX"
echo        ( https://www.tobias-erichsen.de/software/loopmidi.html )
echo   2. FL Studio ^> Options ^> MIDI Settings:
echo        Input  ^> "FLStudioMCP RX": Enable, Controller type = FLStudioMCP, Port = 42
echo        Output ^> "FLStudioMCP TX": Port = 42  (the SAME number; setting the port
echo          enables it, there is no Enable button; leave "Send master sync" off)
echo        View ^> Script output should show  [FLStudioMCP] Ready
echo   3. Start the bridge daemon and keep it running:
echo        double-click scripts\start_daemon.bat  (or run "!DAEMON_CMD!")
echo   4. Register the server with your Claude app:
echo        Claude Code: just ask Claude:
echo          "Add the fl-studio MCP server for all my projects: !SERVER_CMD!
echo           with env FLSTUDIO_MCP_TRANSPORT=tcp"
echo        Claude Desktop: add this under "mcpServers" in
echo          %%APPDATA%%\Claude\claude_desktop_config.json
"%PY%" -c "import json, sys; print('          \"fl-studio\": ' + json.dumps({'command': sys.argv[1], 'env': {'FLSTUDIO_MCP_TRANSPORT': 'tcp'}}))" "!SERVER_CMD!"
echo   5. Each session: in the Piano roll menu choose Tools ^> Scripting ^> MCP ^> MCP Apply
echo        once (this arms note-writing). Then ask Claude to call fl_ping.
echo.
echo  Added optional features? Restart Claude (or run /mcp in Claude Code) so it
echo  picks them up.
echo.
endlocal
