@echo off
title Josh's Media Library
echo.
echo  ==========================================
echo    Josh's Media Library - Starting up...
echo  ==========================================
echo.

:: Check if Python is installed
echo  Checking for Python...
python --version
if errorlevel 1 (
    echo.
    echo  ERROR: Python not found or not in PATH
    echo.
    echo  Please install Python from: https://python.org/downloads
    echo  IMPORTANT: Check "Add Python to PATH" during installation!
    echo.
    pause
    exit /b
)

:: Install Flask if not already installed
echo.
echo  Checking dependencies...
pip show flask >nul 2>&1
if errorlevel 1 (
    echo  Installing Flask...
    pip install flask --quiet
    if errorlevel 1 (
        echo.
        echo  ERROR: Failed to install Flask
        echo  Try running this in Command Prompt:
        echo    pip install flask
        echo.
        pause
        exit /b
    )
)

echo.
echo  Launching media library...
echo  Your browser will open automatically.
echo.
echo  Press Ctrl+C here to shut down the server when done.
echo.

:: Create desktop shortcut on first run
if not exist "%USERPROFILE%\Desktop\Media Library.lnk" (
    powershell -NoProfile -Command ^
      "$ws = New-Object -ComObject WScript.Shell;" ^
      "$s  = $ws.CreateShortcut('%USERPROFILE%\Desktop\Media Library.lnk');" ^
      "$s.TargetPath      = '%~dp0Start Media Library.bat';" ^
      "$s.IconLocation    = '%~dp0MediaLibrary.ico';" ^
      "$s.Description     = 'Josh''s Media Library';" ^
      "$s.WorkingDirectory= '%~dp0';" ^
      "$s.Save()"
    echo  Desktop shortcut created!
)

:: Run from the folder where the bat file lives
cd /d "%~dp0"
start "" pythonw media_library.py

:: pythonw runs Python with no console window — this window will close on its own.
:: To stop the server later, end the "pythonw.exe" process in Task Manager.
::
:: To debug startup errors, comment out the start line above and uncomment these two:
:: python media_library.py
:: pause
