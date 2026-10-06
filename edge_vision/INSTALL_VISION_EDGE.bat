@echo off
setlocal EnableExtensions
set "BASE=%~dp0"
set "RUNTIME=%LOCALAPPDATA%\NEXis\VisionEdge"
set "VENV=%RUNTIME%\venv"
if not exist "%RUNTIME%" mkdir "%RUNTIME%" >nul 2>&1

set "PYTHON="
for %%P in (py.exe python.exe) do (
  if not defined PYTHON (
    where %%P >nul 2>&1 && set "PYTHON=%%P"
  )
)
if not defined PYTHON (
  echo [ERROR] Python 3.11 or 3.12 is required.
  exit /b 2
)

if not exist "%VENV%\Scripts\python.exe" (
  if /I "%PYTHON%"=="py.exe" (
    py -3.12 -m venv "%VENV%" >nul 2>&1 || py -3.11 -m venv "%VENV%" >nul 2>&1 || py -3 -m venv "%VENV%"
  ) else (
    python -m venv "%VENV%"
  )
  if errorlevel 1 exit /b 3
)

"%VENV%\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 exit /b 4
"%VENV%\Scripts\python.exe" -m pip install -r "%BASE%requirements.txt"
if errorlevel 1 exit /b 5
"%VENV%\Scripts\python.exe" -c "import cv2,numpy,requests,ultralytics,mediapipe as mp; assert hasattr(mp, 'solutions')"
if errorlevel 1 exit /b 6
exit /b 0
