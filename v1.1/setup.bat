@echo off
cls
echo ==================================
echo      SongPi Setup Script
echo ==================================
echo.
echo This script will set up the Python virtual environment
echo and install the necessary packages for SongPi.
echo It should only need to be run once.
echo.
echo IMPORTANT: Please ensure you have Python 3 installed and
echo            that it is added to your system's PATH.
echo            (You can download Python from python.org)
echo.
pause
echo.

REM --- Get Script Directory (Project Root) ---
SET "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

REM --- Define Paths ---
SET "VENV_DIR=%SCRIPT_DIR%Files\venv"
SET "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"
SET "VENV_PIP=%VENV_DIR%\Scripts\pip.exe"
SET "REQUIREMENTS_FILE=%SCRIPT_DIR%Files\requirements.txt"

REM --- Check for Python ---
echo Checking for Python installation...
python --version >nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
    echo ERROR: Python command not found.
    echo Please install Python 3 and ensure it's added to your system PATH.
    echo Setup cannot continue.
    echo.
    pause
    exit /b 1
)
echo Python found.

REM --- Create venv if it doesn't exist ---
IF EXIST "%VENV_DIR%\Scripts\activate.bat" (
    echo Virtual environment already seems to exist in '%VENV_DIR%'.
    echo If you need to reinstall packages, delete the '%VENV_DIR%' folder first.
) ELSE (
    echo.
    echo Creating Python virtual environment in "%VENV_DIR%"...
    python -m venv "%VENV_DIR%"
    IF %ERRORLEVEL% NEQ 0 (
        echo ERROR: Failed to create virtual environment in '%VENV_DIR%'.
        echo Check permissions or if Python's venv module is working correctly.
        echo Setup cannot continue.
        echo.
        pause
        exit /b 1
    )
    echo Virtual environment created successfully.
)

REM --- Check if venv pip exists before trying to use it ---
IF NOT EXIST "%VENV_PIP%" (
    echo ERROR: Pip executable not found in the virtual environment at '%VENV_PIP%'.
    echo The virtual environment might be corrupted. Try deleting 'Files\venv' and running setup again.
    echo.
    pause
    exit /b 1
)

REM --- Upgrade Pip directly using venv pip ---
echo.
echo Upgrading pip package manager in venv (recommended)...
"%VENV_PYTHON%" -m pip install --upgrade pip
IF %ERRORLEVEL% NEQ 0 (
    echo WARNING: Failed to upgrade pip using '%VENV_PIP%'. Installation might still work but could use older versions.
)

REM --- Install Packages from requirements.txt directly using venv pip ---
echo.
echo Installing required Python packages from %REQUIREMENTS_FILE%...
IF NOT EXIST "%REQUIREMENTS_FILE%" (
    echo ERROR: %REQUIREMENTS_FILE% not found!
    echo Cannot install required packages.
    echo.
    pause
    exit /b 1
)
"%VENV_PIP%" install -r "%REQUIREMENTS_FILE%"
IF %ERRORLEVEL% NEQ 0 (
    echo ERROR: Failed to install one or more required packages using '%VENV_PIP%'.
    echo Please check the error messages above.
    echo Common issues:
    echo   - No internet connection.
    echo   - Problems installing 'pyaudio'. It might require build tools or specific wheels.
    echo.
    pause
    exit /b 1
)
echo Packages installed successfully.


REM --- Final Section ---
echo.
echo ==================================
echo      SETUP COMPLETE!
echo ==================================
echo You can now run SongPi using the 'SongPi.bat' file, enjoy!
echo.

REM --- Final Pause ---
echo Press any key to exit...
pause > nul
exit /b 0
