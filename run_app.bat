@echo off
setlocal
cd /d "%~dp0"

REM Prefer Python 3 via the launcher; no PATH required
py -3 app.py
exit /b %errorlevel%
