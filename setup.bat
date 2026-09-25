@echo off
setlocal
echo ============================================================
echo   TPlus Automation - One-Time Setup
echo ============================================================

REM --- 1. Check Python ---
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found in PATH. Install Python 3.10+ and retry.
    exit /b 1
)

REM --- 2. Create virtual environment (skip if exists) ---
if not exist venv (
    echo [1/4] Creating virtual environment...
    python -m venv venv
) else (
    echo [1/4] Virtual environment already exists, skipping.
)

REM --- 3. Install dependencies ---
echo [2/4] Installing Python packages...
call venv\Scripts\activate.bat
python -m pip install --upgrade pip --quiet
pip install --quiet pywinauto pywin32 pillow pytesseract opencv-python pyautogui numpy schedule requests mss comtypes pyinstaller

REM --- 4. Check Tesseract OCR (external dependency, not pip-installable) ---
echo [3/4] Checking Tesseract OCR...
if exist "C:\Program Files\Tesseract-OCR\tesseract.exe" (
    echo       Tesseract found.
) else (
    echo [WARN] Tesseract NOT found at C:\Program Files\Tesseract-OCR\
    echo        Download and install: https://github.com/UB-Mannheim/tesseract/wiki
)

REM --- 5. Check config files ---
echo [4/4] Checking config files...
if exist "activity\activity.json" (
    echo       activity\activity.json found.
) else (
    echo [WARN] activity\activity.json missing - copy your client config there
    echo        ^(it is gitignored, so it does not come with git pull^).
)
if not exist "scheduler.json" echo [WARN] scheduler.json missing at project root.

echo ============================================================
echo   Setup complete.
echo   Run scheduler : scheduler.exe        ^(or: venv\Scripts\python manager.py^)
echo   Run one task  : venv\Scripts\python activity\activity.py --config activity\activity.json --process process_01
echo ============================================================
endlocal
