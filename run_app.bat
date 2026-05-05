@echo off
setlocal
cd /d "%~dp0"

REM Prefer Python 3 via the launcher; no PATH required
py -3 -m waitress --host=0.0.0.0 --port=5002 app:app
exit /b %errorlevel%
