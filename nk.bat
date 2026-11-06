@echo off
REM nk command wrapper. usage (PowerShell):  .\nk.bat gen --preset mystyle --n 5
REM Python: NK_PYTHON (path to python.exe) if set. Otherwise "python" on PATH if it has the nk packages (requirements.txt),
REM then the kohya_ss venv (C:\kohya_ss\venv), then plain "python".
set "PY=%NK_PYTHON%"
if "%PY%"=="" (
  python -c "import numpy, cv2, PIL" >nul 2>&1 && set "PY=python"
)
if "%PY%"=="" if exist "C:\kohya_ss\venv\Scripts\python.exe" set "PY=C:\kohya_ss\venv\Scripts\python.exe"
if "%PY%"=="" set "PY=python"
"%PY%" -c "import yaml" >nul 2>&1
if errorlevel 1 "%PY%" -m pip install -q pyyaml
"%PY%" "%~dp0nk.py" %*
