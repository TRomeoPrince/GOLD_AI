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

".venv\Scripts\python.exe" -m pip install --upgrade pyinstaller
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
pause
