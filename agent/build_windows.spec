# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for BuildHarvey Windows build.
#
# Usage:
#   pyinstaller --clean build_windows.spec
#
# Prerequisites:
#   1. Install requirements_windows.txt in the active venv.
#   2. Place Tesseract binary at vendor/tesseract/tesseract.exe
#      and tessdata/ alongside it (download from UB-Mannheim GitHub).
#   3. Place en_core_web_sm model at vendor/en_core_web_sm/
#      (copy from venv/Lib/site-packages/en_core_web_sm/).
#   4. Place icon at assets/icon.ico.

from pathlib import Path

block_cipher = None

a = Analysis(
    ['app_windows.py'],
    pathex=[str(Path('.').resolve())],
    binaries=[],
    datas=[
        ('vendor/tesseract', 'vendor/tesseract'),
        ('vendor/en_core_web_sm', 'vendor/en_core_web_sm'),
        ('assets/icon.ico', 'assets'),
    ],
    hiddenimports=[
        'spacy', 'thinc', 'cymem', 'preshed', 'murmurhash', 'blis',
        'win32api', 'win32con', 'win32gui', 'win32process', 'pywintypes',
        'keyring', 'keyring.backends.Windows',
        'psutil', 'mss', 'pytesseract', 'PIL',
        'anthropic', 'pywinauto',
        'websockets', 'websockets.asyncio.server',
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
