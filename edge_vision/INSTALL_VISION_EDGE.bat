@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "QUIET=0"
if /I "%~1"=="/quiet" set "QUIET=1"
set "NEXIS_RUNTIME=%LOCALAPPDATA%\NEXis\VisionEdge"
set "NEXIS_VENV=%NEXIS_RUNTIME%\venv"
set "NEXIS_PY=%NEXIS_VENV%\Scripts\python.exe"
set "NEXIS_INSTALL_LOG=%NEXIS_RUNTIME%\install.log"
if not exist "%NEXIS_RUNTIME%" mkdir "%NEXIS_RUNTIME%" >nul 2>&1
> "%NEXIS_INSTALL_LOG%" echo [%date% %time%] NEXis Vision dependency setup

if exist "%NEXIS_PY%" (
  "%NEXIS_PY%" -c "import sys; print(sys.version)" >> "%NEXIS_INSTALL_LOG%" 2>&1
  if not errorlevel 1 goto :have_python
  echo [WARN] Existing Vision environment is not usable. Rebuilding it.>> "%NEXIS_INSTALL_LOG%"
  rmdir /s /q "%NEXIS_VENV%" >> "%NEXIS_INSTALL_LOG%" 2>&1
)

where py >nul 2>&1
if not errorlevel 1 (
  py -3.12 -m venv "%NEXIS_VENV%" >> "%NEXIS_INSTALL_LOG%" 2>&1
  if not errorlevel 1 goto :have_python
  py -3.11 -m venv "%NEXIS_VENV%" >> "%NEXIS_INSTALL_LOG%" 2>&1
  if not errorlevel 1 goto :have_python
  py -3 -m venv "%NEXIS_VENV%" >> "%NEXIS_INSTALL_LOG%" 2>&1
  if not errorlevel 1 goto :have_python
)
where python >nul 2>&1
if not errorlevel 1 (
  python -m venv "%NEXIS_VENV%" >> "%NEXIS_INSTALL_LOG%" 2>&1
  if not errorlevel 1 goto :have_python
)
where python3 >nul 2>&1
if not errorlevel 1 (
  python3 -m venv "%NEXIS_VENV%" >> "%NEXIS_INSTALL_LOG%" 2>&1
  if not errorlevel 1 goto :have_python
)

echo [ERROR] No working Python installation could create the Vision environment.>> "%NEXIS_INSTALL_LOG%"
echo [ERROR] No working Python installation was found.
if "%QUIET%"=="0" pause
exit /b 1

:have_python
if not exist "%NEXIS_PY%" (
  echo [ERROR] Vision Python executable was not created.>> "%NEXIS_INSTALL_LOG%"
  exit /b 1
)

"%NEXIS_PY%" -m ensurepip --upgrade >> "%NEXIS_INSTALL_LOG%" 2>&1
"%NEXIS_PY%" -m pip install --upgrade pip setuptools wheel >> "%NEXIS_INSTALL_LOG%" 2>&1
if errorlevel 1 (
  echo [ERROR] pip bootstrap failed.>> "%NEXIS_INSTALL_LOG%"
  if "%QUIET%"=="0" type "%NEXIS_INSTALL_LOG%"
  exit /b 1
)

"%NEXIS_PY%" -m pip install -r "%~dp0requirements_core.txt" >> "%NEXIS_INSTALL_LOG%" 2>&1
if errorlevel 1 (
  echo [ERROR] Core Vision packages failed to install.>> "%NEXIS_INSTALL_LOG%"
  if "%QUIET%"=="0" type "%NEXIS_INSTALL_LOG%"
  exit /b 1
)
"%NEXIS_PY%" -c "import cv2,numpy,requests,cv2_enumerate_cameras; print('core-ok', cv2.__version__)" >> "%NEXIS_INSTALL_LOG%" 2>&1
if errorlevel 1 (
  echo [ERROR] Core Vision packages could not be imported.>> "%NEXIS_INSTALL_LOG%"
  if "%QUIET%"=="0" type "%NEXIS_INSTALL_LOG%"
  exit /b 1
)

"%NEXIS_PY%" -m pip install "ultralytics>=8.3,<9" >> "%NEXIS_INSTALL_LOG%" 2>&1
if errorlevel 1 echo [WARN] YOLO is unavailable; camera, ROI, and motion features remain available.>> "%NEXIS_INSTALL_LOG%"
"%NEXIS_PY%" -m pip install "mediapipe>=0.10.14,<0.11" >> "%NEXIS_INSTALL_LOG%" 2>&1
if errorlevel 1 echo [WARN] MediaPipe is unavailable; the motion/skin hand fallback remains available.>> "%NEXIS_INSTALL_LOG%"

> "%NEXIS_VENV%\.nexis_vision_deps_ready" echo ready
echo [OK] NEXis Vision core dependencies are ready.
if "%QUIET%"=="0" (
  echo Log: %NEXIS_INSTALL_LOG%
  pause
)
exit /b 0
