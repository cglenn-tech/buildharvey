@echo off
setlocal

set VERSION=%1
if "%VERSION%"=="" set VERSION=1.0.0

echo Building BuildHarvey %VERSION% for Windows...
echo.

echo [1/3] Building with PyInstaller...
pyinstaller --clean build_windows.spec
if errorlevel 1 (
    echo ERROR: PyInstaller failed.
    exit /b 1
)

echo [2/3] Creating portable zip...
if not exist Output mkdir Output
powershell -Command "Compress-Archive -Force -Path dist\BuildHarvey -DestinationPath Output\BuildHarvey-%VERSION%-portable.zip"
if errorlevel 1 (
    echo ERROR: Zip creation failed.
    exit /b 1
)

echo [3/3] Building installer with Inno Setup...
where iscc >nul 2>&1
if errorlevel 1 (
    echo WARNING: iscc not found in PATH — skipping installer step.
    echo          Install Inno Setup from https://jrsoftware.org/isinfo.php and add to PATH.
    echo          Then run: iscc /DMyAppVersion=%VERSION% installer.iss
) else (
    iscc /DMyAppVersion=%VERSION% installer.iss
    if errorlevel 1 (
        echo ERROR: Inno Setup installer build failed.
        exit /b 1
    )
    echo Done: Output\BuildHarveySetup-%VERSION%.exe
)

echo.
echo Artifacts in Output\:
echo   BuildHarvey-%VERSION%-portable.zip  (portable, no admin required)
if exist "Output\BuildHarveySetup-%VERSION%.exe" (
    echo   BuildHarveySetup-%VERSION%.exe      (installer, recommended for end users)
)
echo.
echo NOTE: Windows SmartScreen will warn on first run of unsigned builds.
echo       Click "More info" then "Run anyway" to proceed.

endlocal
