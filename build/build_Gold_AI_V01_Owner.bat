@echo off
setlocal
cd /d "%~dp0\.."

echo ==========================================
echo   GOLD_AI V0.1 - OWNER EDITION BUILDER
echo ==========================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo [1/5] Creating virtual environment...
    py -m venv .venv
    if errorlevel 1 goto :fail
)

echo [2/5] Installing/updating build dependencies...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :fail
".venv\Scripts\python.exe" -m pip install -r requirements-build.txt
if errorlevel 1 goto :fail

echo [3/5] Cleaning previous build...
if exist build\pyi rmdir /s /q build\pyi
if exist dist\Gold_AI_V01_Owner.exe del /q dist\Gold_AI_V01_Owner.exe

echo [4/5] Compiling Gold_AI_V01_Owner.exe...
pushd build
"..\.venv\Scripts\python.exe" -m PyInstaller --clean --noconfirm --distpath "..\dist" --workpath "pyi" GOLD_AI_V01_Owner.spec
set BUILD_RC=%ERRORLEVEL%
popd
if not "%BUILD_RC%"=="0" goto :fail
if errorlevel 1 goto :fail

copy /Y "build\GOLD_AI_V01_Owner.env.example" "dist\GOLD_AI_V01_Owner.env.example" >nul
echo [5/5] Build complete.
echo.
echo EXE:
echo %CD%\dist\Gold_AI_V01_Owner.exe
echo.
echo IMPORTANT:
echo - Keep MT5 installed and logged in.
echo - Keep your .env beside the EXE or run with the same environment variables.
echo - API keys and Telegram tokens are NOT compiled into the executable.
echo.
pause
exit /b 0

:fail
echo.
echo BUILD FAILED.
pause
exit /b 1
