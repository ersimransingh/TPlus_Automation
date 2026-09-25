@echo off
setlocal
echo ============================================================
echo   TPlus Automation - Production EXE Build
echo ============================================================

REM --- 1. Ensure venv exists (run setup once if missing) ---
if not exist venv\Scripts\pyinstaller.exe (
    echo [INFO] venv or PyInstaller missing - running setup.bat first...
    call setup.bat
    if errorlevel 1 (
        echo [ERROR] Setup failed. Fix the errors above and retry.
        exit /b 1
    )
)

REM --- 2. Clean previous build artifacts ---
echo [1/4] Cleaning old build artifacts...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist activity\build rmdir /s /q activity\build

REM --- 3. Build engine exe (activity.py -> activity.exe) ---
echo [2/4] Building activity.exe ...
pushd activity
..\venv\Scripts\pyinstaller.exe activity.spec --clean --noconfirm --distpath ..\dist --workpath ..\build\activity
if errorlevel 1 (
    popd
    echo [ERROR] activity.exe build failed.
    exit /b 1
)
popd

REM --- 4. Build scheduler exe (manager.py -> manager.exe) ---
echo [3/4] Building manager.exe ...
venv\Scripts\pyinstaller.exe manager.spec --clean --noconfirm --distpath dist --workpath build\manager
if errorlevel 1 (
    echo [ERROR] manager.exe build failed.
    exit /b 1
)

REM --- 5. Arrange production folder ---
echo [4/4] Arranging dist folder...
if not exist dist\activity mkdir dist\activity
if exist dist\activity.exe move /y dist\activity.exe dist\activity\activity.exe >nul

REM Copy configs next to the exes (only if they exist - they are gitignored)
if exist activity\activity.json copy /y activity\activity.json dist\activity\activity.json >nul
if not exist dist\activity\activity.json if exist activity\activity_local.json copy /y activity\activity_local.json dist\activity\activity.json >nul
if exist scheduler.json copy /y scheduler.json dist\scheduler.json >nul

echo ============================================================
echo   BUILD COMPLETE - production folder: dist\
echo     dist\manager.exe           (daily scheduler)
echo     dist\scheduler.json
echo     dist\activity\activity.exe (automation engine)
echo     dist\activity\activity.json
echo.
echo   Reminder: target machine needs Tesseract OCR at
echo   C:\Program Files\Tesseract-OCR\tesseract.exe and MS Edge.
echo ============================================================
endlocal
