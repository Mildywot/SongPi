@echo off
cls

REM Get the directory of the currently executing script (Project Root)
SET "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

REM Define paths relative to the Project Root (ensure quotes)
SET "VENV_PYTHONW=%SCRIPT_DIR%Files\venv\Scripts\pythonw.exe"
SET "PYTHON_SCRIPT=%SCRIPT_DIR%Files\SongPi.py"

REM Check if windowed Python executable exists
IF NOT EXIST "%VENV_PYTHONW%" (
    echo ERROR: Windowed Python executable not found at %VENV_PYTHONW%.
    echo Please run setup.bat first.
    pause
    exit /b 1
)

REM Check if Python script exists
IF NOT EXIST "%PYTHON_SCRIPT%" (
    echo ERROR: Main script %PYTHON_SCRIPT% not found!
    pause
    exit /b 1
)

REM --- Launch Python GUI script using pythonw.exe via start ---
REM Using 'start' can sometimes help detach properly. The title "SongPi" is required.
echo Launching SongPi (no console)...
start "SongPi" /D "%SCRIPT_DIR%Files" "%VENV_PYTHONW%" "%PYTHON_SCRIPT%"

REM Check if start command itself failed (unlikely but possible)
IF %ERRORLEVEL% NEQ 0 (
    echo ERROR: Failed to start the Python process using 'start'. Error code: %ERRORLEVEL%
    pause
    exit /b 1
)

echo SongPi process launched. The batch file will now exit.
exit /b 0
