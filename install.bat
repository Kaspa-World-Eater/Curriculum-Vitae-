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
echo.
echo Done. Double-click "PixelForge Studio.bat" to start.
echo Blender (free, blender.org) is only needed for the 3D animation path.
pause
