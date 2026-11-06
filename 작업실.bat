@echo off
REM comic workshop page: opens http://127.0.0.1:8765 in the browser. Close this window to stop the page.
cd /d "%~dp0"
call "%~dp0nk.bat" ep web
pause
