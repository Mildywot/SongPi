@echo off

REM Get the directory of the currently executing script
SET SCRIPT_DIR=%~dp0

REM Change to the script directory
cd /d "%SCRIPT_DIR%"

REM Check if the virtual environment exists
IF NOT EXIST "venv\Scripts\activate.bat" (
    echo Virtual environment not found. Please run 1st_time_setup.bat first.
    exit /b 1
)

REM Activate the virtual environment
call venv\Scripts\activate
IF %ERRORLEVEL% NEQ 0 (
    echo Failed to activate virtual environment
    exit /b 1
)

REM Run the Python script
python shazam.py
IF %ERRORLEVEL% NEQ 0 (
    echo Failed to run the Python script
    call venv\Scripts\deactivate
    exit /b 1
)

REM Deactivate the virtual environment
call venv\Scripts\deactivate
IF %ERRORLEVEL% NEQ 0 (
    echo Failed to deactivate virtual environment
    exit /b 1
)

echo Script executed successfully and virtual environment deactivated
exit /b 0
