@echo off
setlocal
cd /d "%~dp0"
if exist "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" (
  set "PUZZLE_PY=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
  goto run
)
where py.exe >nul 2>nul
if not errorlevel 1 (
  py.exe -3 -u "%~dp0puzzle_solver.py" %*
  goto finished
)
where python.exe >nul 2>nul
if not errorlevel 1 (
  python.exe -u "%~dp0puzzle_solver.py" %*
  goto finished
)
echo Python 3.10 or newer was not found. Install Python and cryptography first.
goto finished
:run
"%PUZZLE_PY%" -u "%~dp0puzzle_solver.py" %*
:finished
echo.
echo The search process has ended. Read the status above.
pause
