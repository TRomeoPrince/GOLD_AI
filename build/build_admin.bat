@echo off
setlocal
cd /d "%~dp0\.."

echo ==========================================
echo   AZT ADMIN BUILDER
echo ==========================================

if not exist ".venv\Scripts\python.exe" (
  echo Missing owner virtual environment.
  exit /b 1
)

tasklist /FI "IMAGENAME eq AZT_Admin.exe" 2>nul | find /I "AZT_Admin.exe" >nul
if not errorlevel 1 (
  echo Close AZT Admin before rebuilding.
  exit /b 1
)

".venv\Scripts\python.exe" -m pip install -r requirements-build.txt
if errorlevel 1 exit /b 1

".venv\Scripts\python.exe" -m PyInstaller --clean --noconfirm --distpath "dist" --workpath "build\admin_pyi" "build\GOLD_AI_Admin.spec"
set BUILD_RC=%ERRORLEVEL%

if not "%BUILD_RC%"=="0" exit /b 1

echo.
echo Built:
echo %CD%\dist\AZT_Admin.exe
