# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 스펙 (Excel Paster). 사용: pyinstaller excelpaster.spec
import sys
from pathlib import Path

APP_NAME = "Excel Paster"
ROOT = Path(SPECPATH)
ASSETS = ROOT / "excelpaster" / "assets"
icon = None
if sys.platform == "win32":
    icon = str(ASSETS / "icon.ico")
elif sys.platform == "darwin" and (ASSETS / "icon.icns").exists():
    icon = str(ASSETS / "icon.icns")

a = Analysis(
    ["paster_main.py"],
    pathex=[str(ROOT)],
    datas=[(str(ASSETS / "icon.png"), "excelpaster/assets")],
    hiddenimports=[],
    excludes=["pymupdf", "fitz", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
              "PySide6.QtPdf", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.Qt3DCore",
              "PySide6.QtMultimedia", "pymupdf4llm", "pymupdf_layout", "tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)

if sys.platform == "darwin":
    exe = EXE(pyz, a.scripts, exclude_binaries=True, name=APP_NAME, console=False, icon=icon)
    coll = COLLECT(exe, a.binaries, a.datas, name=APP_NAME)
    app = BUNDLE(
        coll,
        name=f"{APP_NAME}.app",
        icon=icon,
        bundle_identifier="dev.local.excelpaster",
        info_plist={
            "CFBundleDisplayName": APP_NAME,
            "CFBundleShortVersionString": "1.0.0",
            "NSHighResolutionCapable": True,
            "NSRequiresAquaSystemAppearance": False,
        },
    )
else:
    exe = EXE(
        pyz, a.scripts, a.binaries, a.datas, [],
        name=APP_NAME, console=False, icon=icon, upx=False,
    )
