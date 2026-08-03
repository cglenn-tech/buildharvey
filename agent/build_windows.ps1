#Requires -Version 5.1
<#
.SYNOPSIS
    BuildHarvey Windows build script.

.DESCRIPTION
    Automates the full Windows build:
      1. Checks Python
      2. Creates/reuses the virtual environment
      3. Installs Python dependencies
      4. Locates or installs Tesseract OCR
      5. Stages Tesseract files into vendor/tesseract/
      6. Verifies Inno Setup
      7. Runs PyInstaller
      8. Runs the Inno Setup compiler
      9. Verifies the installer output

.PARAMETER Version
    Version string embedded in the installer filename (default: 1.0.0).

.PARAMETER SkipVenv
    Skip virtual environment creation; use the existing .venv.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File build_windows.ps1 -Version 1.2.0
#>

param(
    [string]$Version   = "1.0.0",
    [switch]$SkipVenv
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot   # agent/ directory

# ── Pinned Tesseract version ─────────────────────────────────────────────────
$TESSERACT_VERSION = "5.3.3.20231005"
$TESSERACT_DIR     = "C:\Program Files\Tesseract-OCR"

# ── Inno Setup ───────────────────────────────────────────────────────────────
$ISCC = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"

function Write-Step([string]$msg) {
    Write-Host "`n==> $msg" -ForegroundColor Cyan
}

function Assert-File([string]$path, [string]$description) {
    if (!(Test-Path $path)) {
        Write-Error "$description not found: $path"
    }
}

# ─────────────────────────────────────────────────────────────────────────────
Write-Host "BuildHarvey Windows Build $Version" -ForegroundColor Green
Set-Location $Root

# ── 1. Check Python ───────────────────────────────────────────────────────────
Write-Step "Checking Python"
$pythonExe = (Get-Command python -ErrorAction SilentlyContinue)?.Source
if (!$pythonExe) {
    Write-Error "Python not found in PATH.`nDownload from https://python.org and add to PATH."
}
$pyVer = python --version
Write-Host "Found: $pythonExe ($pyVer)"

# ── 2. Virtual environment ────────────────────────────────────────────────────
Write-Step "Setting up virtual environment"
$Venv   = "$Root\.venv"
$Pip    = "$Venv\Scripts\pip.exe"
$Python = "$Venv\Scripts\python.exe"
$PyInst = "$Venv\Scripts\pyinstaller.exe"

if ($SkipVenv -and (Test-Path $Venv)) {
    Write-Host "Using existing .venv (--SkipVenv)"
} else {
    if (Test-Path $Venv) { Remove-Item $Venv -Recurse -Force }
    python -m venv $Venv
    Write-Host "Created .venv"
}

# ── 3. Install Python dependencies ───────────────────────────────────────────
Write-Step "Installing Python dependencies"
& $Pip install --upgrade pip --quiet
& $Pip install -r "$Root\requirements_windows.txt"
if ($LASTEXITCODE -ne 0) { Write-Error "pip install failed" }
Write-Host "Dependencies installed."

# ── 4. Tesseract ─────────────────────────────────────────────────────────────
Write-Step "Locating Tesseract OCR"
$tessExe = "$TESSERACT_DIR\tesseract.exe"

if (!(Test-Path $tessExe)) {
    Write-Host "Tesseract not found at $TESSERACT_DIR"
    $choice = Read-Host "Install Tesseract $TESSERACT_VERSION automatically? [y/N]"
    if ($choice -imatch '^y') {
        Write-Host "Downloading Tesseract $TESSERACT_VERSION from UB-Mannheim..."
        $url = "https://github.com/UB-Mannheim/tesseract/releases/download/v$TESSERACT_VERSION/tesseract-ocr-w64-setup-$TESSERACT_VERSION.exe"
        Invoke-WebRequest -Uri $url -OutFile "$Root\_tesseract-setup.exe" -UseBasicParsing
        Write-Host "Running installer silently..."
        $proc = Start-Process -FilePath "$Root\_tesseract-setup.exe" `
            -ArgumentList "/S" -Wait -PassThru -NoNewWindow
        Remove-Item "$Root\_tesseract-setup.exe" -Force -ErrorAction SilentlyContinue
        if ($proc.ExitCode -ne 0) {
            Write-Error "Tesseract installer failed (exit code $($proc.ExitCode))"
        }
        Write-Host "Tesseract installed."
    } else {
        Write-Error @"
Tesseract not found. Install options:
  Automatic:  choco install tesseract -y
  Manual:     https://github.com/UB-Mannheim/tesseract/releases/tag/v$TESSERACT_VERSION
Expected path: $TESSERACT_DIR
"@
    }
}

Assert-File $tessExe "tesseract.exe"
$tessVer = & $tessExe --version 2>&1 | Select-Object -First 1
Write-Host "Tesseract: $tessVer"

# ── 5. Stage Tesseract vendor files ──────────────────────────────────────────
Write-Step "Staging Tesseract into vendor/tesseract/"
$dst = "$Root\vendor\tesseract"
New-Item -ItemType Directory -Force -Path "$dst\tessdata" | Out-Null

Copy-Item "$TESSERACT_DIR\tesseract.exe"            $dst -Force
Copy-Item "$TESSERACT_DIR\*.dll"                    $dst -Force -ErrorAction SilentlyContinue
Copy-Item "$TESSERACT_DIR\tessdata\eng.traineddata" "$dst\tessdata\" -Force

Assert-File "$dst\tesseract.exe"              "Staged tesseract.exe"
Assert-File "$dst\tessdata\eng.traineddata"   "Staged eng.traineddata"
$dllCount = @(Get-ChildItem "$dst\*.dll").Count
if ($dllCount -eq 0) { Write-Error "No DLLs staged from $TESSERACT_DIR" }
Write-Host "Staged: tesseract.exe + $dllCount DLLs + tessdata/eng.traineddata"

# ── 6. Verify Inno Setup ─────────────────────────────────────────────────────
Write-Step "Checking Inno Setup"
if (!(Test-Path $ISCC)) {
    Write-Host "Inno Setup not found at $ISCC"
    Write-Host "Install with:"
    Write-Host "    choco install innosetup -y"
    Write-Error "ISCC.exe not found. Install Inno Setup and re-run."
}
Write-Host "Inno Setup found: $ISCC"

# ── 7. PyInstaller ───────────────────────────────────────────────────────────
Write-Step "Building with PyInstaller"
& $PyInst --clean "$Root\build_windows.spec"
if ($LASTEXITCODE -ne 0) { Write-Error "PyInstaller failed" }

$exePath = "$Root\dist\BuildHarvey\BuildHarvey.exe"
Assert-File $exePath "BuildHarvey.exe"
$exeMB = [math]::Round((Get-Item $exePath).Length / 1MB, 1)
Write-Host "BuildHarvey.exe produced ($exeMB MB)"

# ── 8. Inno Setup compiler ───────────────────────────────────────────────────
Write-Step "Building installer with Inno Setup"
& $ISCC "/DMyAppVersion=$Version" "$Root\installer.iss"
if ($LASTEXITCODE -ne 0) { Write-Error "Inno Setup build failed" }

$installer = "$Root\Output\BuildHarveySetup-$Version.exe"
Assert-File $installer "BuildHarveySetup-$Version.exe"

# ── 9. Checksum and summary ───────────────────────────────────────────────────
$hash   = (Get-FileHash $installer -Algorithm SHA256).Hash.ToLower()
$sizeMB = [math]::Round((Get-Item $installer).Length / 1MB, 1)
"$hash  BuildHarveySetup-$Version.exe" |
    Out-File "$Root\Output\BuildHarveySetup-$Version.sha256" -Encoding ascii

Write-Host "`n" -NoNewline
Write-Host "Build complete." -ForegroundColor Green
Write-Host ""
Write-Host "Installer : $installer ($sizeMB MB)"
Write-Host "SHA-256   : $hash"
Write-Host ""
Write-Host "Customer installs one file: BuildHarveySetup-$Version.exe"
