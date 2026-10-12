@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>&1
if errorlevel 1 (
  echo Python Launcher not found. Install Python 3.11+ for Windows and try again.
  pause
  exit /b 1
)

if not exist ".build-venv\Scripts\python.exe" (
  py -3 -m venv .build-venv
  if errorlevel 1 goto :failed
)

call ".build-venv\Scripts\activate.bat"
python -m pip install --upgrade pip
if errorlevel 1 goto :failed
python -m pip install -r requirements.txt pyinstaller
if errorlevel 1 goto :failed

python -m PyInstaller --clean --noconfirm --onefile --windowed --name FicsitOps ^
  --add-data "index.html;." ^
  --add-data "app.js;." ^
  --add-data "styles.css;." ^
  --add-data "pilot\goal.txt;pilot" ^
  --collect-all pynput ^
  --collect-all mss ^
  --collect-all pyautogui ^
  --collect-all pygetwindow ^
  ficsit_ops.py
if errorlevel 1 goto :failed

echo.
echo Build complete: dist\FicsitOps.exe
echo Copy the EXE to a folder on the Windows PC and run it. Ollama/vision model is configured separately.
pause
exit /b 0

:failed
echo.
echo Build failed. Review the error output above.
pause
exit /b 1
