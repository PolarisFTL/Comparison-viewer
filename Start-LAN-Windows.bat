@echo off
call "%~dp0Start-Windows.bat" --lan %*
exit /b %errorlevel%
