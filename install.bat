@echo off
setlocal
cd /d "%~dp0"
echo PixelForge Studio - install
echo.
where py >nul 2>nul && (set PY=py -3) || (set PY=python)
%PY% --version >nul 2>nul || (
  echo Python was not found. Install Python 3.11+ from https://www.python.org/downloads/
  echo and tick "Add Python to PATH" in the installer, then run this again.
  pause & exit /b 1
)
if not exist .venv (
  echo Creating a private Python environment...
  %PY% -m venv .venv || (echo venv failed & pause & exit /b 1)
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip >nul
echo Installing PixelForge (a minute or two)...
pip install -e . || (echo install failed & pause & exit /b 1)
pip install mcp >nul 2>nul
echo Creating the desktop shortcut...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ws = New-Object -ComObject WScript.Shell; $d = [Environment]::GetFolderPath('Desktop');" ^
  "$s = $ws.CreateShortcut((Join-Path $d 'PixelForge Studio.lnk'));" ^
  "$s.TargetPath = (Join-Path '%CD%' '.venv\Scripts\pythonw.exe');" ^
  "$s.Arguments = '-m pixelforge.cli studio'; $s.WorkingDirectory = '%CD%';" ^
  "$s.IconLocation = (Join-Path '%CD%' 'assets\pixelforge.ico') + ',0';" ^
  "$s.Description = 'PixelForge Studio - pixel art sprite pipeline'; $s.Save()" ^
  && echo   Desktop shortcut created. || echo   (could not create the shortcut; use "PixelForge Studio.bat")
echo.
echo Done. Double-click the "PixelForge Studio" icon on your desktop to start.
echo Blender (free, blender.org) is only needed for the 3D animation path.
pause
