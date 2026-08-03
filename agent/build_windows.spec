# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for BuildHarvey Windows build.
#
# Usage:
#   pyinstaller --clean build_windows.spec
#
# Prerequisites:
#   1. Install requirements_windows.txt in the active venv.
#   2. Stage Tesseract at vendor/tesseract/ (tesseract.exe + DLLs + tessdata/eng.traineddata).
#      The GitHub Actions workflow does this automatically.
#      Locally: run build_windows.ps1 which handles it, or see inline instructions.
#   3. Place icon at assets/icon.ico.
#
# spaCy is intentionally excluded. Claude Vision handles all episode classification.
# The regex-only entity extraction in entities.py works without spaCy.

from pathlib import Path

block_cipher = None

a = Analysis(
    ['app_windows.py'],
    pathex=[str(Path('.').resolve())],
    binaries=[],
    datas=[
        ('vendor/tesseract', 'vendor/tesseract'),
        ('assets/icon.ico', 'assets'),
    ],
    hiddenimports=[
        # Windows native APIs
        'win32api', 'win32con', 'win32gui', 'win32process', 'pywintypes',
        # Credential storage
        'keyring', 'keyring.backends.Windows',
        # Screen capture, imaging, OCR
        'psutil', 'mss', 'pytesseract', 'PIL',
        # Windows accessibility (browser URL extraction)
        'pywinauto',
        # Realtime WebSocket client (optional — browser controls)
        'websockets', 'websockets.asyncio.server',
        'realtime', 'realtime.client', 'realtime.channel', 'realtime.types',
    ],
    hookspath=[],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name='BuildHarvey',
    icon='assets/icon.ico',
    console=False,  # no terminal window shown to end user
)

coll = COLLECT(
    exe, a.binaries, a.zipfiles, a.datas,
    name='BuildHarvey',
)
