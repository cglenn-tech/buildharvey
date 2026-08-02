@echo off
setlocal

set VERSION=%1
if "%VERSION%"=="" set VERSION=1.0.0

echo Building BuildHarvey %VERSION% for Windows...
echo.

echo [1/2] Building with PyInstaller...
pyinstaller --clean build_windows.spec
if errorlevel 1 (
    echo ERROR: PyInstaller failed.
    exit /b 1
)

echo [2/2] Creating portable zip...
if not exist Output mkdir Output
powershell -Command "Compress-Archive -Force -Path dist\BuildHarvey -DestinationPath Output\BuildHarvey-%VERSION%-portable.zip"
if errorlevel 1 (
    echo ERROR: Zip creation failed.
    exit /b 1
)

echo.
echo Done: Output\BuildHarvey-%VERSION%-portable.zip
echo.
echo Instructions: Extract the zip and run BuildHarvey.exe to start a work session.
echo No installation required. No startup entries created.
echo.
echo NOTE: Windows SmartScreen will warn on first run.
echo       Click "More info" then "Run anyway" to proceed.

endlocal
