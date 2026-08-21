@echo off
setlocal
cd /d "%~dp0"
echo =============================================
echo   GameCoin Mainnet v1.0.0 Builder
echo =============================================
echo.
where py >nul 2>nul
if errorlevel 1 (
  echo Python launcher ^(py^) was not found.
  echo Install Python first, then rerun this file.
  pause
  exit /b 1
)

echo Building GameCoin executables and installer...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_tools\build_windows.ps1"
if errorlevel 1 (
  echo.
  echo BUILD FAILED. Scroll up for the error message.
  pause
  exit /b 1
)

echo.
for /f "tokens=*" %%H in ('powershell -NoProfile -Command "(Get-FileHash ''%~dp0dist\GameCoin-Setup-v1.0.0-Mainnet.exe'' -Algorithm SHA256).Hash.ToLower()"') do set SHA=%%H
echo %SHA%  GameCoin-Setup-v1.0.0-Mainnet.exe> "%~dp0dist\GameCoin-Setup-v1.0.0-Mainnet.sha256.txt"
echo.
echo =============================================
echo BUILD COMPLETE
echo =============================================
echo Installer:
echo %~dp0dist\GameCoin-Setup-v1.0.0-Mainnet.exe
echo.
echo SHA256:
echo %SHA%
echo.
explorer "%~dp0dist"
pause
