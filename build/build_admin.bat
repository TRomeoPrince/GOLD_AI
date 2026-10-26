@echo off
setlocal
cd /d "%~dp0\.."

echo ==========================================
echo   GOLD_AI ADMIN BUILDER
echo ==========================================

if not exist ".venv\Scripts\python.exe" (
  echo Missing owner virtual environment.
  exit /b 1
)

tasklist /FI "IMAGENAME eq GOLD_AI_Admin.exe" 2>nul | find /I "GOLD_AI_Admin.exe" >nul
if not errorlevel 1 (
  echo Close GOLD_AI Admin before rebuilding.
  exit /b 1
)

".venv\Scripts\python.exe" -m pip install -r requirements.txt -r server\requirements.txt -r requirements-build.txt
if errorlevel 1 exit /b 1

if exist build\admin_pyi rmdir /s /q build\admin_pyi
if exist dist\GOLD_AI_Admin.exe del /q dist\GOLD_AI_Admin.exe

pushd build
"..\.venv\Scripts\python.exe" -m PyInstaller --clean --noconfirm --distpath "..\dist" --workpath "admin_pyi" GOLD_AI_Admin.spec
set BUILD_RC=%ERRORLEVEL%
popd

if not "%BUILD_RC%"=="0" exit /b 1

echo.
echo Built:
echo %CD%\dist\GOLD_AI_Admin.exe
