@echo off
setlocal
cd /d "%~dp0"
where py.exe >nul 2>nul
if not errorlevel 1 (
  py.exe -3 -c "import sys,struct; assert sys.version_info >= (3,10) and struct.calcsize('P') == 8, '64-bit Python 3.10+ required'"
  if errorlevel 1 goto failed
  py.exe -3 -m venv .venv
  goto packages
)
where python.exe >nul 2>nul
if errorlevel 1 goto missing
python.exe -c "import sys,struct; assert sys.version_info >= (3,10) and struct.calcsize('P') == 8, '64-bit Python 3.10+ required'"
if errorlevel 1 goto failed
python.exe -m venv .venv
:packages
if errorlevel 1 goto failed
"%~dp0.venv\Scripts\python.exe" -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 goto failed
"%~dp0.venv\Scripts\python.exe" "%~dp0puzzle_solver.py" --self-test
if errorlevel 1 goto failed
echo Installation complete. Run START-SERVER.cmd.
pause
exit /b 0
:missing
echo Install 64-bit Python 3.10 or newer, then run INSTALL.cmd again.
:failed
echo Setup failed. Read the error above.
pause
exit /b 1
