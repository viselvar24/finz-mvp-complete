@echo off
REM Perfient MVP - Local Development Startup Script (Windows)

echo 🚀 Starting Perfient MVP in Mock Mode...
echo.

REM Check if .env exists
if not exist ".env" (
    echo ⚠️  .env file not found. Creating from template...
    echo MOCK_MODE=true > .env
    echo TIINGO_API_KEY=12a4b6199b51d43953b990b9ec734b451e05d8e1 >> .env
    echo ✅ .env file created
)

REM Check MOCK_MODE setting
findstr /C:"MOCK_MODE=true" .env >nul
if %errorlevel% equ 0 (
    echo ✅ Mock Mode enabled - using dummy data ^(no Firestore^)
) else (
    echo ⚠️  Warning: MOCK_MODE is not set to 'true'
    echo    Set MOCK_MODE=true in .env for local development
)

echo.
echo 📦 Checking Python environment...

REM Check if virtual environment exists, create if not
if not exist "venv" (
    echo Creating virtual environment...
    python -m venv venv
    if %errorlevel% neq 0 (
        echo ❌ Failed to create virtual environment
        echo Make sure Python is installed and in PATH
        pause
        exit /b 1
    )
    echo ✅ Virtual environment created
)

REM Activate virtual environment
echo Activating virtual environment...
call venv\Scripts\activate.bat
if %errorlevel% neq 0 (
    echo ❌ Failed to activate virtual environment
    pause
    exit /b 1
)

REM Check if streamlit is installed
python -c "import streamlit" 2>nul
if %errorlevel% neq 0 (
    echo ⚠️  Streamlit not found. Installing dependencies...
    pip install -r requirements.txt
    if %errorlevel% neq 0 (
        echo ❌ Failed to install dependencies
        pause
        exit /b 1
    )
    echo ✅ Dependencies installed
)

echo.
echo 🌐 Starting Streamlit app...
echo    App will open at: http://localhost:8501
echo.
echo 💡 Tip: Keep this window open while using the app
echo    Press Ctrl+C to stop
echo.

cd /d "%~dp0"
python -m streamlit run app\Chat.py
