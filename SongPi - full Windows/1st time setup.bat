@echo off

REM Check if Python is installed
python --version >nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
    echo Python is not installed. Please install Python from https://www.python.org/downloads/
    exit /b 1
)

REM Create a virtual environment
python -m venv Files\venv
IF %ERRORLEVEL% NEQ 0 (
    echo Failed to create virtual environment
    exit /b 1
)

REM Activate the virtual environment
call Files\venv\Scripts\activate
IF %ERRORLEVEL% NEQ 0 (
    echo Failed to activate virtual environment
    exit /b 1
)

REM Install required packages
pip install pyaudio shazamio requests pillow screeninfo
IF %ERRORLEVEL% NEQ 0 (
    echo Failed to install required packages
    exit /b 1
)

echo Virtual environment set up successfully and required packages installed
exit /b 0
