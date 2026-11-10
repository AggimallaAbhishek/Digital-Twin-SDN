@echo off
rem Double-click this file (or run it in Command Prompt) to check the project on Windows.
rem It starts run_windows.ps1 and keeps the window open so you can read the result.
rem Add -Tests to also run the unit tests:   run_windows.bat -Tests
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_windows.ps1" %*
echo.
pause
