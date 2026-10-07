@echo off
set "R=%LOCALAPPDATA%\NEXis\VisionEdge"
echo ===== LAUNCHER =====
type "%R%\launcher.log" 2>nul
echo.
echo ===== INSTALL =====
type "%R%\install.log" 2>nul
echo.
echo ===== EDGE STDERR =====
type "%R%\edge-error.log" 2>nul
echo.
echo ===== EDGE STDOUT =====
type "%R%\edge.log" 2>nul
echo.
pause
