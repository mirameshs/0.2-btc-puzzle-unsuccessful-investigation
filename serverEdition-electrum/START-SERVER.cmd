@echo off
setlocal
cd /d "%~dp0"
if not exist "%~dp0.venv\Scripts\python.exe" (
  echo First run INSTALL.cmd in this folder.
  pause
  exit /b 1
)
"%~dp0.venv\Scripts\python.exe" -u "%~dp0puzzle_solver.py" %*
set "PUZZLE_EXIT=%ERRORLEVEL%"
echo.
echo Search ended. Check the status above. Ctrl+C pauses; running again resumes.
pause
exit /b %PUZZLE_EXIT%
