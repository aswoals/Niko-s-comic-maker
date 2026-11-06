@echo off
REM nk command wrapper. usage (PowerShell):  .\nk.bat gen --preset mystyle --n 5
REM Python: set NK_PYTHON to your python.exe (for example the kohya_ss venv). Otherwise C:\kohya_ss\venv is tried, then "python" on PATH.
set "PY=%NK_PYTHON%"
if "%PY%"=="" if exist "C:\kohya_ss\venv\Scripts\python.exe" set "PY=C:\kohya_ss\venv\Scripts\python.exe"
if "%PY%"=="" set "PY=python"
"%PY%" -c "import yaml" >nul 2>&1
if errorlevel 1 "%PY%" -m pip install -q pyyaml
"%PY%" "%~dp0nk.py" %*
