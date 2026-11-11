@echo off
setlocal
cd /d "%~dp0"
echo === WaveRescue Windows EXE Builder ===
echo Requires Python 3.10+ installed on this BUILD computer only.
py -3 -m venv .venv
if errorlevel 1 goto failed
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
if errorlevel 1 goto failed
python -m pip install -r requirements.txt
if errorlevel 1 goto failed
python -m PyInstaller --noconfirm --clean --onefile --windowed --name WaveRescue app.py
if errorlevel 1 goto failed
echo.
echo SUCCESS: dist\WaveRescue.exe
start "" "%~dp0dist"
pause
exit /b 0
:failed
echo Build failed. Review messages above.
pause
exit /b 1
