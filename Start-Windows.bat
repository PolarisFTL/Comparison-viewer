@echo off
setlocal
cd /d "%~dp0"
if exist "%~dp0RGBTViewer.exe" (
  start "" "%~dp0RGBTViewer.exe" %*
  exit /b 0
)
where py >nul 2>nul
if not errorlevel 1 (
  py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)" >nul 2>nul
  if not errorlevel 1 (
    py -3 "%~dp0desktop.py" %*
    goto finish
  )
)
where python >nul 2>nul
if not errorlevel 1 (
  python -c "import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)" >nul 2>nul
  if not errorlevel 1 (
    python "%~dp0desktop.py" %*
    goto finish
  )
)
echo Python 3.9 or newer was not found.
echo Install Python, or use a published Windows portable package containing RGBTViewer.exe.
pause
exit /b 1
:finish
if errorlevel 1 (
  echo The viewer stopped with an error. Please read the message above.
  pause
  exit /b 1
)
exit /b 0
